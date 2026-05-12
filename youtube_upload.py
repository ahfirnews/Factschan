#!/usr/bin/env python3
"""
YouTube uploader — Countdown / Comparison niche.
Accepts pre-built title, description and tags from yt.py.
Required env vars: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
"""
import os
import json
import time
import random
import subprocess
import pathlib

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError


SCOPES      = ["https://www.googleapis.com/auth/youtube.upload"]
MAX_RETRIES = 3


# ══════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════

def _get_service():
    creds = Credentials(
        token         = None,
        refresh_token = os.environ.get("YT_REFRESH_TOKEN", ""),
        token_uri     = "https://oauth2.googleapis.com/token",
        client_id     = os.environ.get("YT_CLIENT_ID", ""),
        client_secret = os.environ.get("YT_CLIENT_SECRET", ""),
        scopes        = SCOPES,
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


# ══════════════════════════════════════════════════════════════
# METADATA  (viral Countdown / Comparison formula)
# ══════════════════════════════════════════════════════════════

# Fallback titles if nothing is passed in (e.g. direct CLI use)
_FALLBACK_TITLE_TEMPLATES = [
    "The {n} Most SHOCKING Facts You Never Knew #Shorts",
    "{n} Mind-Blowing Facts That Will Change Your World View #Shorts",
    "You Won't Believe These {n} Incredible Facts #Shorts",
    "The {n} Most EXTREME Facts On Earth #Shorts",
    "{n} Jaw-Dropping Facts Nobody Tells You #Shorts",
]

_FALLBACK_TAGS = [
    "shorts", "youtube shorts", "short", "viral",
    "did you know", "facts", "mind blowing facts",
    "interesting facts", "amazing facts", "fun facts",
    "educational", "knowledge", "top facts", "countdown",
    "trending", "learn",
]


def _build_metadata(
    fact: str,
    duration_seconds: int,
    override_title: str | None = None,
    override_desc:  str | None = None,
    override_tags:  list[str] | None = None,
) -> dict:
    """
    Build YouTube video metadata.
    override_* values come from yt.py's build_video_title / build_video_description /
    build_video_tags.  When absent (CLI use), sensible fallbacks are generated.
    """

    # ── Title ─────────────────────────────────────────────────
    if override_title:
        title = override_title[:100]
    else:
        tmpl = random.choice(_FALLBACK_TITLE_TEMPLATES)
        title = tmpl.format(n=random.choice([3, 5, 7, 10]))[:100]

    # ── Description ───────────────────────────────────────────
    if override_desc:
        description = override_desc[:5000]
    else:
        dur_m = duration_seconds // 60
        dur_s = duration_seconds % 60
        description = (
            f"{fact[:280]}\n\n"
            f"✅ Follow for daily mind-blowing facts!\n"
            f"🔔 Turn on notifications so you never miss one.\n\n"
            f"⏱️ Duration: {dur_m}:{dur_s:02d}\n"
            f"📱 Vertical format for YouTube Shorts\n\n"
            f"#Shorts #YouTubeShorts #DidYouKnow #Facts #MindBlowing "
            f"#InterestingFacts #AmazingFacts #Educational #FunFacts "
            f"#Viral #Countdown #TopFacts"
        )[:5000]

    # ── Tags ──────────────────────────────────────────────────
    tags = (override_tags or _FALLBACK_TAGS)[:30]

    return {
        "snippet": {
            "title":           title,
            "description":     description,
            "tags":            tags,
            "categoryId":      "27",   # Education — highest CPM category
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus":          "public",   # Publish immediately
            "selfDeclaredMadeForKids": False,      # Never True — kills monetisation
            "embeddable":              True,
        },
        # YouTube Shorts detection signals (all three required):
        # 1. #Shorts in the title        ← always present in our titles
        # 2. Vertical 9:16 aspect ratio  ← enforced by yt.py (1080x1920)
        # 3. Duration ≤ 60 s             ← enforced by yt.py (21-58 s)
    }


# ══════════════════════════════════════════════════════════════
# VIDEO VERIFICATION
# ══════════════════════════════════════════════════════════════

def _verify_shorts_criteria(file_path: pathlib.Path) -> dict:
    """Quick ffprobe check before wasting an upload quota call."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(file_path)],
        capture_output=True, text=True, timeout=30,
    )
    info = json.loads(result.stdout)
    vs = next(
        (s for s in info.get("streams", []) if s.get("width") and s.get("height")),
        None,
    )
    dur = float(info.get("format", {}).get("duration", 0))
    w   = int(vs["width"])  if vs else 0
    h   = int(vs["height"]) if vs else 0
    ar  = w / h if h else 0
    return {
        "width": w, "height": h,
        "aspect_ratio": round(ar, 3),
        "duration": round(dur, 1),
        "is_vertical": 0.55 <= ar <= 0.58,
        "is_short":    20 < dur < 59,
    }


# ══════════════════════════════════════════════════════════════
# UPLOAD
# ══════════════════════════════════════════════════════════════

def upload_to_youtube(
    file_path:        str | pathlib.Path,
    fact:             str   = None,
    duration_seconds: int   = None,
    override_title:   str   = None,
    override_desc:    str   = None,
    override_tags:    list  = None,
) -> str:
    """
    Upload a Shorts video to YouTube.

    Parameters
    ----------
    file_path        : Path to the .mp4 file.
    fact             : The script/voiceover text (used for fallback description).
    duration_seconds : Video duration in seconds (auto-detected if None).
    override_title   : Pre-built viral title from yt.py.
    override_desc    : Pre-built SEO description from yt.py.
    override_tags    : Pre-built tag list from yt.py.

    Returns
    -------
    str  : YouTube Short URL  (https://youtu.be/<id>)
    """
    file_path = pathlib.Path(file_path)

    # ── Pre-flight checks ─────────────────────────────────────
    print(f"\n  Pre-flight check: {file_path.name}", flush=True)
    try:
        info = _verify_shorts_criteria(file_path)
        print(f"    {info['width']}x{info['height']}  "
              f"AR={info['aspect_ratio']}  "
              f"Duration={info['duration']}s", flush=True)
        if not info["is_vertical"]:
            print("    [WARNING] Aspect ratio may not trigger Shorts shelf", flush=True)
        if not info["is_short"]:
            print("    [WARNING] Duration outside 21-58s range", flush=True)
        if duration_seconds is None:
            duration_seconds = int(info["duration"])
    except Exception as e:
        print(f"    [WARNING] ffprobe check failed: {e}", flush=True)
        duration_seconds = duration_seconds or 25

    # ── Fallback fact for description ─────────────────────────
    if fact is None:
        # Try to pull from DB
        try:
            import sqlite3
            db = pathlib.Path("shorts_db.db")
            if db.exists():
                conn = sqlite3.connect(db)
                row = conn.execute(
                    "SELECT fact FROM videos WHERE file_path=? ORDER BY id DESC LIMIT 1",
                    (str(file_path),)
                ).fetchone()
                conn.close()
                fact = row[0] if row else "Mind-blowing countdown facts."
        except Exception:
            fact = "Mind-blowing countdown facts."

    # ── Build metadata ────────────────────────────────────────
    body = _build_metadata(
        fact             = fact,
        duration_seconds = duration_seconds,
        override_title   = override_title,
        override_desc    = override_desc,
        override_tags    = override_tags,
    )

    print(f"\n  Uploading to YouTube Shorts...", flush=True)
    print(f"  Title    : {body['snippet']['title']}", flush=True)
    print(f"  Tags     : {', '.join(body['snippet']['tags'][:6])}...", flush=True)

    # ── Resumable upload ──────────────────────────────────────
    yt     = _get_service()
    media  = MediaFileUpload(
        str(file_path),
        chunksize = 8 * 1024 * 1024,   # 8 MB chunks
        resumable = True,
        mimetype  = "video/mp4",
    )
    request = yt.videos().insert(
        part       = "snippet,status",
        body       = body,
        media_body = media,
    )

    response  = None
    retry     = 0
    last_pct  = -1

    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                if pct >= last_pct + 10:
                    print(f"    Progress: {pct}%", flush=True)
                    last_pct = pct
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retry < MAX_RETRIES:
                retry += 1
                wait = 2 ** retry
                print(f"    HTTP {e.resp.status} — retry {retry}/{MAX_RETRIES} in {wait}s",
                      flush=True)
                time.sleep(wait)
            else:
                raise

    video_id = response["id"]
    url = f"https://youtu.be/{video_id}"
    print(f"  ✅  Live: {url}", flush=True)
    return url


# ══════════════════════════════════════════════════════════════
# CLI  (direct test use)
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python youtube_upload.py <video_file> [script_text] [title]")
        sys.exit(1)

    vf     = sys.argv[1]
    script = sys.argv[2] if len(sys.argv) > 2 else None
    t      = sys.argv[3] if len(sys.argv) > 3 else None

    url = upload_to_youtube(vf, fact=script, override_title=t)
    print(f"\nShorts URL: {url}")
