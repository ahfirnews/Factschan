"""Rendering, narration fallback, caption, and audio utilities for Fact Voltage."""

from __future__ import annotations

import json
import os
import pathlib
import random
import re
import subprocess

import requests


FREESOUND_API_KEY = os.getenv("FREESOUND_API_KEY", "").strip()
JAMENDO_CLIENT_ID = os.getenv("JAMENDO_CLIENT_ID", "").strip()
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "").strip()

WORK_DIR = pathlib.Path(os.getenv("WORK_DIR", ".fact_voltage_work"))
MUSIC_DIR = WORK_DIR / "music"
for directory in (WORK_DIR, MUSIC_DIR):
    directory.mkdir(parents=True, exist_ok=True)

NORM_WIDTH = 1080
NORM_HEIGHT = 1920
NORM_FPS = 30
VIDEO_BITRATE = "12000k"


def get_duration(path: str | pathlib.Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        return 0.0


def _ff(args: list[str], label: str = "", timeout: int = 300) -> None:
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"[{label}] timed out after {timeout}s") from error
    if result.returncode != 0:
        raise RuntimeError(f"[{label}]: {result.stderr[:400]}")


def extract_keywords(text: str) -> list[str]:
    stop = {
        "about", "after", "again", "also", "before", "between", "could", "each",
        "fact", "facts", "from", "have", "into", "just", "make", "more", "most",
        "number", "only", "other", "people", "should", "some", "than", "that", "their",
        "these", "thing", "things", "this", "those", "through", "very", "where", "which",
        "while", "with", "would", "your",
    }
    words = re.findall(r"\b\w+\b", text.casefold())
    keywords = [word for word in words if word not in stop and len(word) > 3]
    keywords.sort(key=len, reverse=True)
    return list(dict.fromkeys(keywords))[:4]


_HIGHLIGHT_PATTERNS = re.compile(
    r"\b("
    r"\d[\d,.]*\s*(?:million|billion|trillion|thousand|hundred|km|mph|kg|lbs|"
    r"tonnes?|years?|days?|hours?|seconds?|metres?|feet|miles?|volts?|watts?|%|x)?\b"
    r"|number\s+\d+|#\d+|1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th"
    r"|never|impossible|forever|fastest|largest|smallest|deadliest|hottest|coldest"
    r"|oldest|youngest|rarest|strongest|heaviest|most\s+\w+|least\s+\w+"
    r"|INSANE|MIND-BLOWING|BAFFLED|SHOCKING|TERRIFYING|INCREDIBLE|RIGHT NOW"
    r"|FOREVER|ZERO|NONE|EVERY|ALL)\b",
    re.IGNORECASE,
)


def _tag_highlights(line: str) -> str:
    return _HIGHLIGHT_PATTERNS.sub(
        lambda match: f"⟦HIGHLIGHT⟧{match.group()}⟦/HIGHLIGHT⟧", line
    )


def _caption_phrases(words: list[str], max_words: int = 6, max_chars: int = 34) -> list[tuple[int, int]]:
    """Split captions into short, readable ranges of word indexes."""
    phrases: list[tuple[int, int]] = []
    start = 0
    while start < len(words):
        end = start
        length = 0
        while end < len(words):
            candidate = length + len(words[end]) + (1 if end > start else 0)
            if end > start and (end - start >= max_words or candidate > max_chars):
                break
            length = candidate
            end += 1
            if end - start >= 3 and re.search(r"[.!?]$", words[end - 1]):
                break
        phrases.append((start, max(start + 1, end)))
        start = max(start + 1, end)
    return phrases


def _balanced_caption_lines(words: list[str]) -> list[list[str]]:
    """Balance a short phrase across at most two centered lines."""
    if len(" ".join(words)) <= 18 or len(words) < 3:
        return [words]
    split = min(
        range(1, len(words)),
        key=lambda index: abs(len(" ".join(words[:index])) - len(" ".join(words[index:]))),
    )
    return [words[:split], words[split:]]


def _ass_escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")")


def add_captions(
    video_path: pathlib.Path,
    audio_path: pathlib.Path,
    lines: list[str],
    word_timings: list[dict],
    output_path: pathlib.Path,
) -> None:
    """Burn phrase captions with an exact active-word highlight."""
    video_duration = get_duration(video_path)
    source_text = " ".join(re.sub(r"⟦[^⟧]*⟧", "", line) for line in lines)
    source_words = source_text.split()
    timing_words = [
        str(item.get("punctuated_word") or item.get("word") or "").strip()
        for item in word_timings
    ]
    display_words = source_words if len(source_words) == len(word_timings) else timing_words
    count = min(len(display_words), len(word_timings))
    if count == 0:
        raise RuntimeError("No word timings are available for captions")
    display_words = display_words[:count]
    word_timings = word_timings[:count]
    phrases = _caption_phrases(display_words)

    def styled_word(word: str, active: bool) -> str:
        clean = _ass_escape(word)
        if active:
            return rf"{{\c&H0000E6FF&\bord8}}{clean}{{\c&H00FFFFFF&\bord7}}"
        if _HIGHLIGHT_PATTERNS.search(word):
            return rf"{{\c&H00FFE500&}}{clean}{{\c&H00FFFFFF&}}"
        return clean

    def phrase_text(start: int, end: int, active: int) -> str:
        rendered = [styled_word(display_words[index], index == active) for index in range(start, end)]
        raw_lines = _balanced_caption_lines(display_words[start:end])
        first_length = len(raw_lines[0])
        if len(raw_lines) == 1:
            return " ".join(rendered)
        return " ".join(rendered[:first_length]) + r"\N" + " ".join(rendered[first_length:])

    def ass_time(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}:{minutes:02d}:{seconds % 60:05.2f}"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {NORM_WIDTH}
PlayResY: {NORM_HEIGHT}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Montserrat-Bold,76,&H00FFFFFF,&H0000E6FF,&H00000000,&H68000000,1,0,0,0,100,100,0.5,0,1,7,3,2,55,55,220,1
Style: Hook,Montserrat-Bold,84,&H00FFFFFF,&H0000E6FF,&H00000000,&H68000000,1,0,0,0,100,100,0.5,0,1,8,3,2,55,55,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass_path = WORK_DIR / f"captions_{output_path.stem}.ass"
    event_count = 0
    with ass_path.open("w", encoding="utf-8") as handle:
        handle.write(header)
        for phrase_number, (phrase_start, phrase_end) in enumerate(phrases):
            style = "Hook" if phrase_number == 0 else "Caption"
            for active in range(phrase_start, phrase_end):
                start = max(0.0, float(word_timings[active]["start"]))
                word_end = max(start + 0.03, float(word_timings[active]["end"]))
                if active + 1 < count:
                    # ASS renders two events at a shared timestamp on the same
                    # frame. Leave one centisecond between events so their
                    # outlines cannot collide and hide parts of the phrase.
                    next_start = float(word_timings[active + 1]["start"])
                    end = max(start + 0.01, next_start - 0.011)
                else:
                    end = word_end
                end = min(video_duration, end)
                if end <= start:
                    continue
                text = phrase_text(phrase_start, phrase_end, active)
                handle.write(
                    f"Dialogue: 0,{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}\n"
                )
                event_count += 1
    print(
        f"[CAPTIONS] {count} exact word timings → {len(phrases)} short phrases "
        f"({event_count} active-word events)"
    )
    escaped_ass = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
    try:
        _ff(
            ["-i", str(video_path.resolve()), "-i", str(audio_path.resolve()),
             "-t", str(video_duration), "-map", "0:v:0", "-map", "1:a:0",
             "-vf", f"ass='{escaped_ass}'", "-c:v", "libx264", "-preset", "slow",
             "-b:v", VIDEO_BITRATE, "-c:a", "aac", "-b:a", "192k", "-pix_fmt",
             "yuv420p", "-movflags", "+faststart", "-crf", "18", "-shortest",
             str(output_path.resolve())],
            label="add_captions", timeout=300,
        )
    finally:
        ass_path.unlink(missing_ok=True)


def create_video_from_image(image_path: pathlib.Path, duration: int) -> pathlib.Path:
    output = image_path.parent / f"image_segment_{random.randint(10000, 99999)}.mp4"
    _ff(
        ["-loop", "1", "-i", str(image_path.resolve()), "-vf",
         f"scale={NORM_WIDTH}:{NORM_HEIGHT}:force_original_aspect_ratio=increase,"
         f"crop={NORM_WIDTH}:{NORM_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
         f"zoompan=z='min(zoom+0.001,1.1)':d={duration * NORM_FPS}:"
         f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
         f"s={NORM_WIDTH}x{NORM_HEIGHT}:fps={NORM_FPS}",
         "-c:v", "libx264", "-preset", "slow", "-b:v", VIDEO_BITRATE,
         "-r", str(NORM_FPS), "-t", str(duration), "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", "-crf", "18", str(output.resolve())],
        label="create_video_from_image", timeout=300,
    )
    return output


def generate_voiceover(text: str, output_path: pathlib.Path) -> tuple[pathlib.Path, list[dict]]:
    """Deepgram narration fallback used only when Edge TTS is unavailable."""
    if not DEEPGRAM_API_KEY:
        raise RuntimeError("DEEPGRAM_API_KEY is not configured")
    response = requests.post(
        "https://api.deepgram.com/v1/speak?model=aura-2-thalia-en",
        headers={"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": "application/json"},
        json={"text": text}, timeout=120,
    )
    response.raise_for_status()
    output_path.write_bytes(response.content)
    with output_path.open("rb") as audio:
        transcript = requests.post(
            "https://api.deepgram.com/v1/listen?smart_format=true&punctuate=true&model=nova-2",
            headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
            files={"audio": audio}, timeout=120,
        )
    transcript.raise_for_status()
    words = transcript.json()["results"]["channels"][0]["alternatives"][0]["words"]
    if not words:
        raise RuntimeError("Deepgram returned no word timings")
    return output_path, words


def generate_sound_effects(
    keywords: list[str], duration: int, output_path: pathlib.Path
) -> pathlib.Path | None:
    if not FREESOUND_API_KEY:
        return None
    base = keywords[0] if keywords else "ambient"
    try:
        for query in (f"{base} ambient", f"{base} dramatic", "cinematic hit", "whoosh transition"):
            response = requests.get(
                "https://freesound.org/apiv2/search/text/",
                params={"query": query, "token": FREESOUND_API_KEY,
                        "fields": "previews,duration,name,tags",
                        "filter": "duration:[3 TO 15]", "page_size": 10},
                timeout=30,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            if not results:
                continue
            sound = random.choice(results)
            media = requests.get(sound["previews"]["preview-hq-mp3"], timeout=60)
            media.raise_for_status()
            output_path.write_bytes(media.content)
            if get_duration(output_path) < duration:
                looped = output_path.parent / f"looped_{output_path.name}"
                _ff(["-stream_loop", "-1", "-i", str(output_path.resolve()),
                     "-t", str(duration), str(looped.resolve())], label="loop_sfx", timeout=60)
                output_path.unlink(missing_ok=True)
                return looped
            return output_path
    except Exception as error:
        print(f"    Freesound SFX unavailable ({type(error).__name__})")
    return None


def get_background_music(duration: int) -> pathlib.Path:
    if JAMENDO_CLIENT_ID:
        try:
            for tag in ("epic", "cinematic", "upbeat", "dramatic", "tension"):
                response = requests.get(
                    "https://api.jamendo.com/v3.0/tracks/",
                    params={"client_id": JAMENDO_CLIENT_ID, "limit": 20, "tags": tag,
                            "format": "json", "audiodownloadformat": "mp32"},
                    timeout=30,
                )
                response.raise_for_status()
                tracks = [item for item in response.json().get("results", []) if item.get("duration", 0) >= 30]
                if not tracks:
                    continue
                track = random.choice(tracks)
                url = track.get("audiodownload") or track.get("audio")
                if not url:
                    continue
                media = requests.get(url, timeout=60)
                media.raise_for_status()
                original = MUSIC_DIR / f"music_{random.randint(10000, 99999)}.mp3"
                trimmed = MUSIC_DIR / f"trimmed_{original.name}"
                original.write_bytes(media.content)
                _ff(["-i", str(original.resolve()), "-t", str(duration), str(trimmed.resolve())],
                    label="trim_music", timeout=60)
                original.unlink(missing_ok=True)
                return trimmed
        except Exception as error:
            print(f"    Jamendo unavailable ({type(error).__name__})")
    print("    Generating cinematic drone (no music API)...")
    output = MUSIC_DIR / f"drone_{random.randint(10000, 99999)}.mp3"
    _ff(["-f", "lavfi", "-i", "anoisesrc=color=pink:sample_rate=44100",
         "-af", "volume=0.15,highpass=f=60,lowpass=f=300,aecho=0.8:0.7:40:0.4",
         "-t", str(duration), str(output.resolve())], label="generate_drone", timeout=60)
    return output


def normalise_video(video_path: pathlib.Path, video_duration: int, norm_path: pathlib.Path) -> None:
    filters = (
        f"scale={NORM_WIDTH}:{NORM_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={NORM_WIDTH}:{NORM_HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    inputs = ["-i", str(video_path.resolve())]
    if get_duration(video_path) < video_duration:
        inputs = ["-stream_loop", "-1", *inputs]
    _ff([*inputs, "-t", str(video_duration), "-vf", filters, "-c:v", "libx264",
         "-preset", "slow", "-b:v", VIDEO_BITRATE, "-r", str(NORM_FPS), "-an",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-crf", "18",
         str(norm_path.resolve())], label="normalise_video", timeout=300)


def mix_audio(
    sfx_path: pathlib.Path | None,
    bgm_path: pathlib.Path,
    out_path: pathlib.Path,
    vo_path: pathlib.Path | None = None,
) -> None:
    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    if vo_path and vo_path.exists():
        inputs += ["-i", str(vo_path.resolve())]
        filters.append(f"[{len(labels)}:a]volume=1.0[vo]")
        labels.append("[vo]")
    inputs += ["-i", str(bgm_path.resolve())]
    filters.append(f"[{len(labels)}:a]volume=0.18[bgm]")
    labels.append("[bgm]")
    if sfx_path and sfx_path.exists():
        inputs += ["-i", str(sfx_path.resolve())]
        filters.append(f"[{len(labels)}:a]volume=0.08[sfx]")
        labels.append("[sfx]")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:dropout_transition=2")
    _ff([*inputs, "-filter_complex", ";".join(filters), "-c:a", "libmp3lame",
         "-b:a", "192k", str(out_path.resolve())], label="mix_audio", timeout=120)


def verify_video_for_shorts(video_path: pathlib.Path) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height:format=duration",
             "-of", "json", str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(result.stdout)
        stream = next((item for item in info.get("streams", []) if item.get("width") and item.get("height")), None)
        if not stream:
            return False
        width, height = int(stream["width"]), int(stream["height"])
        duration = float(info.get("format", {}).get("duration", 0))
        ratio = width / height if height else 0
        print(f"    Resolution  : {width}x{height}")
        print(f"    Aspect ratio: {ratio:.3f}  (target 0.5625)")
        print(f"    Duration    : {duration:.1f}s  (target 21-58s)")
        valid = width == NORM_WIDTH and height == NORM_HEIGHT and 0.55 <= ratio <= 0.58 and 20 < duration < 59
        print("    [OK] Passes YouTube Shorts criteria" if valid else "    [FAIL] Invalid Shorts output")
        return valid
    except Exception as error:
        print(f"    [ERROR] Verification failed: {error}")
        return False
