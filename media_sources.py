"""Licensed and public-domain visual discovery for Fact Voltage."""

from __future__ import annotations

import hashlib
import os
import pathlib
import random
import re
from urllib.parse import quote

import requests


SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "FactVoltageBot/1.0 (automated educational video creator)"})

GENERIC_QUERY_WORDS = {
    "ancient", "animation", "aerial", "cinematic", "close", "footage", "framing",
    "giant", "great", "human", "large", "macro", "motion", "planet", "scientific",
    "setting", "shot", "slow", "technology", "video", "view",
}

QUALITY_PRIORITY = {"4K": 0, "1080p": 1, "720p": 2}


def quality_label(width: object, height: object) -> str | None:
    """Map a source resolution to an accepted delivery tier."""
    try:
        short, long = sorted((int(width), int(height)))
    except (TypeError, ValueError):
        return None
    if short >= 2160 and long >= 3840:
        return "4K"
    if short >= 1080 and long >= 1920:
        return "1080p"
    if short >= 720 and long >= 1280:
        return "720p"
    return None


def _quality_key(item: dict) -> tuple[int, float, int]:
    width = int(item.get("width") or 0)
    height = int(item.get("height") or 0)
    label = quality_label(width, height)
    aspect_distance = abs((width / max(height, 1)) - 0.5625) if width and height else 2.0
    return QUALITY_PRIORITY.get(label or "", 3), aspect_distance, -(width * height)


def _clean_query(query: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", query)
    return " ".join(words[:10])


def _pexels(query: str) -> list[dict]:
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        return []
    response = SESSION.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": key},
        params={"query": query, "per_page": 15, "orientation": "portrait", "size": "large"},
        timeout=(8, 12),
    )
    response.raise_for_status()
    output = []
    for video in response.json().get("videos", []):
        files = sorted([
            item for item in video.get("video_files", [])
            if item.get("link") and quality_label(item.get("width"), item.get("height"))
        ], key=_quality_key)
        if files:
            output.append({
                "source": "Pexels", "id": str(video["id"]), "kind": "video", "url": files[0]["link"],
                "width": files[0].get("width"), "height": files[0].get("height"),
                "quality": quality_label(files[0].get("width"), files[0].get("height")),
                "search_text": video.get("url", ""),
                "attribution": f"Pexels video by {video.get('user', {}).get('name', 'contributor')}",
                "license": "Pexels License",
            })
    return output


def _pixabay(query: str) -> list[dict]:
    key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not key:
        return []
    response = SESSION.get(
        "https://pixabay.com/api/videos/",
        params={"key": key, "q": query, "per_page": 20, "safesearch": "true"},
        timeout=(8, 25),
    )
    response.raise_for_status()
    output = []
    for video in response.json().get("hits", []):
        variants = video.get("videos", {})
        accepted = [
            variant for variant in variants.values()
            if variant and variant.get("url") and quality_label(variant.get("width"), variant.get("height"))
        ]
        variant = sorted(accepted, key=_quality_key)[0] if accepted else None
        if variant and variant.get("url"):
            output.append({
                "source": "Pixabay", "id": str(video["id"]), "kind": "video", "url": variant["url"],
                "width": variant.get("width"), "height": variant.get("height"),
                "quality": quality_label(variant.get("width"), variant.get("height")),
                "search_text": video.get("tags", ""),
                "attribution": f"Pixabay video by {video.get('user', 'contributor')}",
                "license": "Pixabay Content License",
            })
    return output


def _wikimedia(query: str) -> list[dict]:
    simple = " ".join(query.split()[:3])
    def search(value: str) -> dict:
        response = SESSION.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": f"{value} filetype:video", "gsrnamespace": 6, "gsrlimit": 12,
                "prop": "videoinfo", "viprop": "url|mime|extmetadata|derivatives|size",
            },
            timeout=(8, 25),
        )
        response.raise_for_status()
        return response.json()

    payload = search(simple)
    if not payload.get("query", {}).get("pages"):
        payload = search(query.split()[0])
    output = []
    for page in payload.get("query", {}).get("pages", {}).values():
        info = (page.get("videoinfo") or [{}])[0]
        mime = info.get("mime", "")
        derivatives = [
            item for item in info.get("derivatives", [])
            if item.get("src") and item.get("type", "").startswith("video/")
            and quality_label(item.get("width"), item.get("height"))
        ]
        derivatives.sort(key=_quality_key)
        original = {
            "src": info.get("url", ""), "width": info.get("width"), "height": info.get("height")
        }
        chosen = derivatives[0] if derivatives else original
        url = chosen.get("src", "")
        if not url or mime not in {"video/webm", "video/ogg", "video/mp4", "application/ogg"}:
            continue
        meta = info.get("extmetadata", {})
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "Wikimedia contributor"))
        license_name = meta.get("LicenseShortName", {}).get("value", "Wikimedia Commons license")
        output.append({
            "source": "Wikimedia Commons", "id": str(page.get("pageid")), "kind": "video", "url": url,
            "width": chosen.get("width"), "height": chosen.get("height"),
            "quality": quality_label(chosen.get("width"), chosen.get("height")),
            "attribution": f"{page.get('title', 'Wikimedia video')} — {artist}", "license": license_name,
            "search_text": page.get("title", ""),
        })
    return output


def _wikimedia_images(query: str) -> list[dict]:
    """Keyless Commons still-image fallback when no usable video exists."""
    simple = " ".join(query.split()[:4])

    def search(value: str) -> dict:
        response = SESSION.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": f"{value} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 20,
                "prop": "imageinfo", "iiprop": "url|mime|extmetadata|size", "iiurlwidth": 3840,
            },
            timeout=(8, 25),
        )
        response.raise_for_status()
        return response.json()

    payload = search(simple)
    if not payload.get("query", {}).get("pages"):
        payload = search(" ".join(query.split()[:2]))
    output = []
    for page in payload.get("query", {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in {"image/jpeg", "image/png", "image/webp"}:
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        meta = info.get("extmetadata", {})
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "Wikimedia contributor"))
        license_name = meta.get("LicenseShortName", {}).get("value", "Wikimedia Commons license")
        output.append({
            "source": "Wikimedia Commons", "id": str(page.get("pageid")), "kind": "image", "url": url,
            "width": info.get("thumbwidth") or info.get("width"),
            "height": info.get("thumbheight") or info.get("height"),
            "quality": quality_label(
                info.get("thumbwidth") or info.get("width"), info.get("thumbheight") or info.get("height")
            ),
            "attribution": f"{page.get('title', 'Wikimedia image')} — {artist}", "license": license_name,
            "search_text": page.get("title", ""),
        })
    return output


def _nasa(query: str) -> list[dict]:
    simple = " ".join(query.split()[:4])
    response = SESSION.get(
        "https://images-api.nasa.gov/search",
        params={"q": simple, "media_type": "video,image", "page_size": 20},
        timeout=(8, 25),
    )
    response.raise_for_status()
    output = []
    for item in response.json().get("collection", {}).get("items", []):
        data = (item.get("data") or [{}])[0]
        nasa_id = data.get("nasa_id")
        media_type = data.get("media_type")
        links = item.get("links") or []
        if not nasa_id:
            continue
        if media_type == "image" and links:
            output.append({
                "source": "NASA", "id": nasa_id, "kind": "image", "url": links[0].get("href"),
                "attribution": f"NASA: {data.get('title', nasa_id)}", "license": "NASA Media Usage Guidelines",
                "search_text": data.get("title", ""),
            })
        elif media_type == "video":
            try:
                assets = SESSION.get(f"https://images-api.nasa.gov/asset/{quote(nasa_id)}", timeout=(8, 20)).json()
                urls = [entry.get("href", "") for entry in assets.get("collection", {}).get("items", [])]
                mp4s = [url for url in urls if url.lower().endswith(".mp4")]
                mp4s.sort(key=lambda url: (
                    0 if re.search(r"~(?:orig|original)\.mp4$", url, re.I) else
                    1 if re.search(r"~large\.mp4$", url, re.I) else
                    2 if re.search(r"~medium\.mp4$", url, re.I) else
                    3 if re.search(r"~small\.mp4$", url, re.I) else 2,
                    len(url),
                ))
                if mp4s:
                    output.append({
                        "source": "NASA", "id": nasa_id, "kind": "video", "url": mp4s[0],
                        "attribution": f"NASA: {data.get('title', nasa_id)}", "license": "NASA Media Usage Guidelines",
                        "search_text": data.get("title", ""),
                    })
            except requests.RequestException:
                continue
    return output


def _openverse(query: str) -> list[dict]:
    response = SESSION.get(
        "https://api.openverse.org/v1/images/",
        params={"q": query, "page_size": 20, "mature": "false", "license_type": "commercial"},
        timeout=(8, 30),
    )
    response.raise_for_status()
    output = []
    for item in response.json().get("results", []):
        url = item.get("url") or item.get("thumbnail")
        if url:
            output.append({
                "source": "Openverse", "id": str(item.get("id")), "kind": "image", "url": url,
                "width": item.get("width"), "height": item.get("height"),
                "quality": quality_label(item.get("width"), item.get("height")),
                "attribution": f"{item.get('title') or 'Openverse image'} — {item.get('creator') or 'unknown creator'}",
                "license": str(item.get("license") or "Creative Commons").upper(),
                "search_text": item.get("title") or "",
            })
    return output


def _art_institute(query: str) -> list[dict]:
    if not any(term in query.casefold() for term in (
        "ancient", "history", "roman", "oxford", "pyramid", "antikythera", "printing", "art"
    )):
        return []
    response = SESSION.get(
        "https://api.artic.edu/api/v1/artworks/search",
        params={
            "q": query, "limit": 15,
            "fields": "id,title,artist_display,image_id,is_public_domain",
        },
        timeout=(8, 25),
    )
    response.raise_for_status()
    output = []
    for item in response.json().get("data", []):
        if item.get("is_public_domain") and item.get("image_id"):
            output.append({
                "source": "Art Institute of Chicago", "id": str(item["id"]), "kind": "image",
                "url": f"https://www.artic.edu/iiif/2/{item['image_id']}/full/2160,/0/default.jpg",
                "attribution": f"{item.get('title', 'Artwork')} — {item.get('artist_display', 'unknown artist')}",
                "license": "CC0 Public Domain",
                "search_text": item.get("title", ""),
            })
    return output


SEARCHERS = (_pexels, _pixabay, _wikimedia, _nasa, _openverse, _wikimedia_images, _art_institute)


SEARCH_ALIASES = {"fibre": "fiber", "colour": "color"}


def _normalized_search(value: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    return " ".join(SEARCH_ALIASES.get(token, token) for token in tokens)


def _query_terms(query: str) -> list[str]:
    return [
        term for term in _normalized_search(query).split()
        if (len(term) >= 4 or term in {"gps", "qr"}) and term not in GENERIC_QUERY_WORDS
    ]


def _relevance(query: str, item: dict) -> int:
    text = _normalized_search(str(item.get("search_text") or item.get("attribution", "")))
    terms = _query_terms(query)
    return sum(1 for term in terms[:5] if term[:5] in text)


def _subject_matches(query: str, item: dict) -> bool:
    """Require the query's lead subject, not just a secondary keyword."""
    terms = _query_terms(query)
    if not terms:
        return False
    text = _normalized_search(str(item.get("search_text") or item.get("attribution", "")))
    return terms[0][:5] in text


def candidates(query: str) -> list[dict]:
    """Return shuffled candidates while isolating individual source failures."""
    clean = _clean_query(query)
    found: list[dict] = []
    for searcher in SEARCHERS:
        try:
            found.extend(searcher(clean))
        except Exception as error:
            print(f"[MEDIA] {searcher.__name__[1:]} unavailable ({type(error).__name__})")
    # Stock APIs already rank their own output. Public catalogs are filtered by
    # visible title so a technically valid but unrelated search result cannot win.
    priority = {"Pexels": 0, "Pixabay": 1, "Wikimedia Commons": 2, "NASA": 3, "Openverse": 4, "Art Institute of Chicago": 5}
    ranked = []
    for item in found:
        score = _relevance(clean, item)
        if score == 0 or not _subject_matches(clean, item):
            continue
        item["relevance"] = score
        ranked.append(item)
    return sorted(
        ranked,
        key=lambda item: (
            0 if item["kind"] == "video" else 1,
            -item["relevance"],
            _quality_key(item),
            priority.get(item["source"], 9),
        ),
    )


def download(item: dict, directory: pathlib.Path, max_bytes: int = 180_000_000) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    suffix = pathlib.Path(item["url"].split("?")[0]).suffix.lower()
    if suffix not in {".mp4", ".webm", ".ogv", ".ogg", ".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".mp4" if item["kind"] == "video" else ".jpg"
    name = hashlib.sha256(f"{item['source']}:{item['id']}".encode()).hexdigest()[:18] + suffix
    path = directory / name
    with SESSION.get(item["url"], stream=True, timeout=(10, 90)) as response:
        response.raise_for_status()
        declared = int(response.headers.get("content-length", 0) or 0)
        if declared > max_bytes:
            raise ValueError("media file exceeds size limit")
        size = 0
        with path.open("wb") as handle:
            for chunk in response.iter_content(1024 * 256):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("media download exceeded size limit")
                handle.write(chunk)
    return path
