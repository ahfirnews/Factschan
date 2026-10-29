#!/usr/bin/env python3
"""Fact Voltage: resilient, no-black-frame YouTube Shorts automation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import pathlib
import re
import sqlite3
import subprocess
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone

from ai_generator import configured_provider_count, generate_package
from channel_config import CHANNEL_DESCRIPTION, CHANNEL_HANDLE, CHANNEL_NAME, CHANNEL_TAGLINE, TTS_PITCH, TTS_RATE, TTS_VOICE
from media_sources import candidates, download, quality_label
from prompt_reserve import RESERVE_PATH, consume, release, reserve, seed, stats
from youtube_upload import upload_to_youtube

import video_tools


DB_PATH = pathlib.Path(os.getenv("SHORTS_DB_PATH", "shorts_db.db"))
OUTPUT_DIR = pathlib.Path(os.getenv("OUTPUT_DIR", "output"))
WORK_DIR = pathlib.Path(os.getenv("WORK_DIR", ".fact_voltage_work"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
WORK_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Episode:
    path: pathlib.Path
    package: dict
    reserve_id: int | None
    media: list[dict]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db() -> None:
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS used_titles (
            normalized_title TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            youtube_url TEXT NOT NULL,
            used_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS used_scripts_v2 (
            fingerprint TEXT PRIMARY KEY,
            script TEXT NOT NULL,
            youtube_url TEXT NOT NULL,
            used_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS used_media_v2 (
            source TEXT NOT NULL,
            media_id TEXT NOT NULL,
            url TEXT NOT NULL,
            used_at TEXT NOT NULL,
            PRIMARY KEY(source, media_id)
        );
        CREATE TABLE IF NOT EXISTS uploads (
            youtube_url TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            script TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    # Preserve the old channel's deduplication history during the migration.
    now = datetime.now(timezone.utc).isoformat()
    legacy_scripts = conn.execute(
        "SELECT script FROM used_scripts WHERE COALESCE(script,'') <> ''"
    ).fetchall()
    legacy_scripts += conn.execute(
        "SELECT script FROM videos WHERE COALESCE(script,'') <> ''"
    ).fetchall()
    for row in legacy_scripts:
        conn.execute(
            "INSERT OR IGNORE INTO used_scripts_v2(fingerprint,script,youtube_url,used_at) VALUES(?,?,?,?)",
            (_script_fingerprint(row[0]), row[0], "legacy", now),
        )
    for row in conn.execute("SELECT title FROM videos WHERE COALESCE(title,'') <> ''").fetchall():
        normalized = re.sub(r"[^a-z0-9]+", " ", row[0].casefold()).strip()
        conn.execute(
            "INSERT OR IGNORE INTO used_titles(normalized_title,title,youtube_url,used_at) VALUES(?,?,?,?)",
            (normalized, row[0], "legacy", now),
        )
    for row in conn.execute("SELECT source,video_id,url FROM used_videos").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO used_media_v2(source,media_id,url,used_at) VALUES(?,?,?,?)",
            (row[0], str(row[1]), row[2] or "", now),
        )
    conn.commit()
    conn.close()


def _script_fingerprint(script: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", script.casefold()).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def package_used(package: dict) -> bool:
    conn = _connect()
    result = conn.execute(
        "SELECT 1 FROM used_titles WHERE normalized_title=? UNION ALL "
        "SELECT 1 FROM used_scripts_v2 WHERE fingerprint=? LIMIT 1",
        (package["normalized_title"], _script_fingerprint(package["script"])),
    ).fetchone()
    conn.close()
    return result is not None


def media_used(item: dict) -> bool:
    conn = _connect()
    result = conn.execute(
        "SELECT 1 FROM used_media_v2 WHERE source=? AND media_id=?",
        (item["source"], str(item["id"])),
    ).fetchone()
    conn.close()
    return result is not None


def record_success(episode: Episode, youtube_url: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    package = episode.package
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO used_titles(normalized_title,title,youtube_url,used_at) VALUES(?,?,?,?)",
            (package["normalized_title"], package["title"], youtube_url, now),
        )
        conn.execute(
            "INSERT INTO used_scripts_v2(fingerprint,script,youtube_url,used_at) VALUES(?,?,?,?)",
            (_script_fingerprint(package["script"]), package["script"], youtube_url, now),
        )
        for item in episode.media:
            conn.execute(
                "INSERT OR IGNORE INTO used_media_v2(source,media_id,url,used_at) VALUES(?,?,?,?)",
                (item["source"], str(item["id"]), item["url"], now),
            )
        conn.execute(
            "INSERT INTO uploads(youtube_url,title,script,source,created_at) VALUES(?,?,?,?,?)",
            (youtube_url, package["title"], package["script"], package["source"], now),
        )
        conn.commit()
    finally:
        conn.close()
    if episode.reserve_id is not None:
        consume(episode.reserve_id)


def choose_package(pending_titles: set[str], pending_scripts: set[str]) -> tuple[dict, int | None]:
    def rejected(package: dict) -> bool:
        script_hash = _script_fingerprint(package["script"])
        return (
            package["normalized_title"] in pending_titles
            or script_hash in pending_scripts
            or package_used(package)
        )

    package = generate_package(rejected)
    reserve_id = None
    if package is None:
        for _ in range(50):
            reserve_id, package = reserve()
            if not rejected(package):
                break
            release(reserve_id)
        else:
            raise RuntimeError("No unique package is available")
        print(f"[SCRIPT] All live providers unavailable; reserved offline row {reserve_id}")
    pending_titles.add(package["normalized_title"])
    pending_scripts.add(_script_fingerprint(package["script"]))
    return package, reserve_id


async def _edge_voice(text: str, output: pathlib.Path) -> list[dict]:
    import edge_tts

    communicate = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE, pitch=TTS_PITCH)
    timings: list[dict] = []
    sentences: list[dict] = []
    with output.open("wb") as handle:
        async for event in communicate.stream():
            if event["type"] == "audio":
                handle.write(event["data"])
            elif event["type"] == "WordBoundary":
                timings.append({
                    "word": event.get("text", ""),
                    "start": event["offset"] / 10_000_000,
                    "end": (event["offset"] + event["duration"]) / 10_000_000,
                })
            elif event["type"] == "SentenceBoundary":
                sentences.append(event)
    # Current Edge streams expose sentence boundaries on some voices. Expand
    # each sentence deterministically by word length so caption blocks remain
    # locked to the spoken sentence rather than drifting across the whole clip.
    if not timings:
        for sentence in sentences:
            words = sentence.get("text", "").split()
            weights = [max(1, len(re.sub(r"[^A-Za-z0-9]", "", word))) + 1 for word in words]
            start = sentence["offset"] / 10_000_000
            span = sentence["duration"] / 10_000_000
            cursor = start
            total = sum(weights) or 1
            for word, weight in zip(words, weights):
                end = cursor + span * weight / total
                timings.append({"word": word, "start": cursor, "end": end})
                cursor = end
    if not output.exists() or output.stat().st_size < 10_000 or not timings:
        raise RuntimeError("Edge TTS returned incomplete audio")
    return timings


def generate_voice(text: str, output: pathlib.Path) -> tuple[pathlib.Path, list[dict]]:
    try:
        timings = asyncio.run(_edge_voice(text, output))
        print(f"[VOICE] {TTS_VOICE}: {len(timings)} narration-locked word timings")
        return output, timings
    except Exception as error:
        if os.getenv("DEEPGRAM_API_KEY", "").strip():
            print(f"[VOICE] Edge TTS unavailable ({type(error).__name__}); trying Deepgram narration")
            return video_tools.generate_voiceover(text, output)
        raise RuntimeError("Edge TTS failed and no Deepgram fallback is configured") from error


def _visual_has_detail(path: pathlib.Path) -> bool:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vf", "scale=64:64:force_original_aspect_ratio=increase,crop=64:64,format=gray",
        "-frames:v", "4", "-f", "rawvideo", "-",
    ]
    result = subprocess.run(command, capture_output=True, timeout=45)
    if result.returncode != 0:
        return False
    frame_size = 64 * 64
    frames = [result.stdout[index:index + frame_size] for index in range(0, len(result.stdout), frame_size)]
    for frame in frames:
        if len(frame) != frame_size:
            continue
        dynamic_range = max(frame) - min(frame)
        horizontal = sum(
            abs(frame[row * 64 + column] - frame[row * 64 + column - 1])
            for row in range(64) for column in range(1, 64)
        )
        vertical = sum(
            abs(frame[row * 64 + column] - frame[(row - 1) * 64 + column])
            for row in range(1, 64) for column in range(64)
        )
        edge_energy = (horizontal + vertical) / (2 * 64 * 63)
        if dynamic_range >= 24 and edge_energy >= 2.5:
            return True
    return False


def _visual_resolution(path: pathlib.Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return 0, 0
    streams = json.loads(result.stdout or "{}").get("streams", [])
    if not streams:
        return 0, 0
    return int(streams[0].get("width") or 0), int(streams[0].get("height") or 0)


def _make_segment(source: pathlib.Path, kind: str, seconds: float, output: pathlib.Path) -> None:
    if kind == "video":
        video_tools.normalise_video(source, max(3, math.ceil(seconds)), output)
    else:
        created = video_tools.create_video_from_image(source, max(3, math.ceil(seconds)))
        created.replace(output)


def build_visuals(queries: list[str], beat_durations: list[float], token: str) -> tuple[pathlib.Path, list[dict]]:
    selected: list[dict] = []
    segments: list[pathlib.Path] = []
    duration = sum(beat_durations)
    for index, (query, beat) in enumerate(zip(queries, beat_durations)):
        print(f"[VISUAL {index + 1}/3] {query}")
        accepted = False
        for item in candidates(query):
            if media_used(item) or any(x["source"] == item["source"] and x["id"] == item["id"] for x in selected):
                continue
            source = None
            try:
                source = download(item, WORK_DIR)
                width, height = _visual_resolution(source)
                quality = quality_label(width, height)
                if quality is None:
                    raise ValueError(f"source resolution {width}x{height} is below the 720p floor")
                if not _visual_has_detail(source):
                    raise ValueError("visual is blank, flat, or unreadable")
                segment = WORK_DIR / f"segment_{token}_{index}.mp4"
                _make_segment(source, item["kind"], beat, segment)
                item = {**item, "width": width, "height": height, "quality": quality}
                selected.append(item)
                segments.append(segment)
                accepted = True
                print(
                    f"  selected {item['source']}:{item['id']} ({item['kind']}, "
                    f"{quality} source {width}x{height})"
                )
                break
            except Exception as error:
                response = getattr(error, "response", None)
                status = getattr(response, "status_code", None)
                reason = str(error) if isinstance(error, ValueError) else f"HTTP {status}" if status else type(error).__name__
                print(f"  rejected {item['source']}:{item['id']} ({reason})")
            finally:
                if source and source.exists():
                    source.unlink(missing_ok=True)
        if not accepted:
            raise RuntimeError(f"No non-blank licensed visual found for: {query}")

    output = WORK_DIR / f"visuals_{token}.mp4"
    inputs: list[str] = []
    normalized_labels: list[str] = []
    filters: list[str] = []
    for index, segment in enumerate(segments):
        inputs.extend(["-i", str(segment.resolve())])
        filters.append(f"[{index}:v]setsar=1[v{index}]")
        normalized_labels.append(f"[v{index}]")
    filters.append(f"{''.join(normalized_labels)}concat=n=3:v=1:a=0[v]")
    video_tools._ff(
        inputs + [
            "-filter_complex", ";".join(filters),
            "-map", "[v]", "-t", f"{duration:.3f}", "-r", "30",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            str(output.resolve()),
        ],
        label="concat_visual_beats", timeout=480,
    )
    for segment in segments:
        segment.unlink(missing_ok=True)
    if not _visual_has_detail(output):
        raise RuntimeError("Final visual track failed the non-blank quality guard")
    return output, selected


def _ranked_beat_durations(script: str, timings: list[dict], total: float) -> list[float]:
    words = script.split()
    starts: dict[int, float] = {}
    for index, word in enumerate(words[:-1]):
        if word.casefold().rstrip(":") == "number":
            match = re.match(r"([123])", words[index + 1])
            if match and index < len(timings):
                starts[int(match.group(1))] = float(timings[index]["start"])
    start_two = starts.get(2, total / 3)
    start_one = starts.get(1, total * 2 / 3)
    values = [start_two, start_one - start_two, total - start_one]
    if any(value < 3 for value in values):
        return [total / 3] * 3
    return values


def _compact_caption_lines(script: str) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    length = 0
    for word in script.split():
        candidate = length + len(word) + (1 if current else 0)
        if current and candidate > 26:
            lines.append(video_tools._tag_highlights(" ".join(current)))
            current, length = [word], len(word)
        else:
            current.append(word)
            length = candidate
    if current:
        lines.append(video_tools._tag_highlights(" ".join(current)))
    return lines


def _description(package: dict, media: list[dict]) -> str:
    credits = "\n".join(
        f"• {item['attribution']} ({item['license']})" for item in media
    )
    return (
        f"{package['script'].split('Number 3:')[0].strip()}\n\n"
        f"{CHANNEL_DESCRIPTION}\n\nVisual credits:\n{credits}\n\n"
        "#Shorts #FactVoltage #Facts #Science #History #Technology #DidYouKnow"
    )[:5000]


def create_episode(package: dict, reserve_id: int | None) -> Episode:
    token = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    voice = WORK_DIR / f"voice_{token}.mp3"
    voice, timings = generate_voice(package["script"], voice)
    duration = min(55.0, max(24.0, video_tools.get_duration(str(voice)) + 1.0))
    beat_durations = _ranked_beat_durations(package["script"], timings, duration)
    print(f"[EDIT] Voice-aligned scene lengths: {', '.join(f'{value:.1f}s' for value in beat_durations)}")
    visual, media = build_visuals(package["visual_queries"], beat_durations, token)

    caption_lines = _compact_caption_lines(package["script"])
    sfx = video_tools.generate_sound_effects(
        video_tools.extract_keywords(package["topic"]), math.ceil(duration), WORK_DIR / f"sfx_{token}.mp3"
    )
    music = video_tools.get_background_music(math.ceil(duration))
    if music is None:
        raise RuntimeError("No background audio bed was produced")
    mixed = WORK_DIR / f"mix_{token}.mp3"
    video_tools.mix_audio(sfx, music, mixed, vo_path=voice)
    final = OUTPUT_DIR / f"FACT_VOLTAGE_{token}.mp4"
    video_tools.add_captions(visual, mixed, caption_lines, timings, final)
    if not video_tools.verify_video_for_shorts(final) or not _visual_has_detail(final):
        raise RuntimeError("Final video failed Shorts or visual-quality validation")
    for path in (voice, visual, mixed, sfx, music):
        if path:
            pathlib.Path(path).unlink(missing_ok=True)
    return Episode(final, package, reserve_id, media)


def main() -> int:
    init_db()
    reserve_count = seed()
    count = max(1, int(os.getenv("NUM_VIDEOS", "1")))
    upload = os.getenv("UPLOAD_TO_YOUTUBE", "true").casefold() == "true"
    print(f"{CHANNEL_NAME} {CHANNEL_HANDLE} — {CHANNEL_TAGLINE}")
    print(f"Configured AI providers: {configured_provider_count()} | Offline reserve: {reserve_count} | Upload: {upload}")

    episodes: list[Episode] = []
    pending_titles: set[str] = set()
    pending_scripts: set[str] = set()
    for index in range(count):
        package = None
        reserve_id = None
        try:
            package, reserve_id = choose_package(pending_titles, pending_scripts)
            print(f"[EPISODE {index + 1}/{count}] {package['title']} ({package['source']})")
            episodes.append(create_episode(package, reserve_id))
        except Exception as error:
            if reserve_id is not None:
                release(reserve_id)
            print(f"[ERROR] Episode {index + 1} failed: {error}")
            traceback.print_exc()

    if not upload:
        for episode in episodes:
            if episode.reserve_id is not None:
                release(episode.reserve_id)
        print(f"Preview complete: {len(episodes)}/{count}. No upload and no reserve/history consumption.")
        return 0 if len(episodes) == count else 1

    successful = 0
    for episode in episodes:
        package = episode.package
        try:
            title = f"{package['title']} #Shorts"[:100]
            url = upload_to_youtube(
                episode.path,
                fact=package["script"],
                duration_seconds=int(video_tools.get_duration(str(episode.path))),
                override_title=title,
                override_desc=_description(package, episode.media),
                override_tags=["shorts", "fact voltage", *package["tags"]],
            )
            record_success(episode, url)
            successful += 1
        except Exception as error:
            if episode.reserve_id is not None:
                release(episode.reserve_id)
            print(f"[ERROR] Upload failed; uniqueness state was not consumed: {error}")
            traceback.print_exc()
    print(f"Uploaded {successful}/{count}. Reserve state: {json.dumps(stats(), sort_keys=True)}")
    return 0 if successful == count else 1


if __name__ == "__main__":
    raise SystemExit(main())
