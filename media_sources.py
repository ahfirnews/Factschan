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
    "animation", "aerial", "cinematic", "close", "footage", "framing", "macro",
    "motion", "scientific", "setting", "shot", "slow", "technology", "video", "view",
}


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
        params={"query": query, "per_page": 15, "orientation": "portrait", "size": "medium"},
        timeout=(8, 12),
    )
    response.raise_for_status()
    output = []
    for video in response.json().get("videos", []):
        files = sorted(
            [item for item in video.get("video_files", []) if item.get("link") and item.get("width")],
            key=lambda item: abs((item.get("width", 0) / max(item.get("height", 1), 1)) - 0.5625),
        )
        if files:
            output.append({
                "source": "Pexels", "id": str(video["id"]), "kind": "video", "url": files[0]["link"],
                "width": files[0].get("width"), "height": files[0].get("height"),
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
        variant = variants.get("medium") or variants.get("small") or variants.get("large")
        if variant and variant.get("url"):
            output.append({
                "source": "Pixabay", "id": str(video["id"]), "kind": "video", "url": variant["url"],
                "width": variant.get("width"), "height": variant.get("height"),
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
                "prop": "videoinfo", "viprop": "url|mime|extmetadata|derivatives",
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
            if item.get("src") and "video/webm" in item.get("type", "") and item.get("height", 0) <= 720
        ]
        derivatives.sort(key=lambda item: item.get("height", 0), reverse=True)
        url = derivatives[0]["src"] if derivatives else info.get("url", "")
        if not url or mime not in {"video/webm", "video/ogg", "video/mp4", "application/ogg"}:
            continue
        meta = info.get("extmetadata", {})
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "Wikimedia contributor"))
        license_name = meta.get("LicenseShortName", {}).get("value", "Wikimedia Commons license")
        output.append({
            "source": "Wikimedia Commons", "id": str(page.get("pageid")), "kind": "video", "url": url,
            "width": derivatives[0].get("width") if derivatives else info.get("width"),
            "height": derivatives[0].get("height") if derivatives else info.get("height"),
            "attribution": f"{page.get('title', 'Wikimedia video')} — {artist}", "license": license_name,
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
                mp4s = [url for url in urls if re.search(r"~(?:small|medium)\.mp4$", url, re.I)]
                if not mp4s:
                    mp4s = [url for url in urls if url.lower().endswith(".mp4")]
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
        timeout=(8, 12),
    )
    response.raise_for_status()
    output = []
    for item in response.json().get("results", []):
        url = item.get("url") or item.get("thumbnail")
        if url:
            output.append({
                "source": "Openverse", "id": str(item.get("id")), "kind": "image", "url": url,
                "width": item.get("width"), "height": item.get("height"),
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
                "url": f"https://www.artic.edu/iiif/2/{item['image_id']}/full/843,/0/default.jpg",
                "attribution": f"{item.get('title', 'Artwork')} — {item.get('artist_display', 'unknown artist')}",
                "license": "CC0 Public Domain",
                "search_text": item.get("title", ""),
            })
    return output


SEARCHERS = (_pexels, _pixabay, _wikimedia, _nasa, _openverse, _art_institute)


def _relevance(query: str, item: dict) -> int:
    text = re.sub(r"[^a-z0-9]+", " ", str(item.get("search_text") or item.get("attribution", "")).casefold())
    terms = [
        term for term in re.findall(r"[a-z0-9]+", query.casefold())
        if len(term) >= 4 and term not in GENERIC_QUERY_WORDS
    ]
    return sum(1 for term in terms[:5] if term[:5] in text)


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
        if item["source"] not in {"Pexels", "Pixabay"} and score == 0:
            continue
        item["relevance"] = score
        ranked.append(item)
    return sorted(
        ranked,
        key=lambda item: (
            0 if item["kind"] == "video" else 1,
            -item["relevance"],
            abs(
                (float(item.get("width") or 0) / max(float(item.get("height") or 0), 1.0)) - 0.5625
            ) if item.get("width") and item.get("height") else 2.0,
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
