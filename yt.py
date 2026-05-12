#!/usr/bin/env python3
"""
YouTube Shorts Pipeline — Countdown / Comparison Niche
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Niche  : Countdown / Comparison  (MrBeast-style viral formula)
Format : Hook → Amplify → 3 ranked facts → Payoff → CTA
Captions: Montserrat-Bold, white body + #FFE600 keyword highlights
Duration: 21–58 s  (never exactly 60 — algorithm edge case)
Upload : Public immediately, Education category, optimised metadata
"""

import os
import re
import json
import random
import sqlite3
import pathlib
import subprocess
import time
from datetime import datetime, timedelta
import requests

try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    pass

# ══════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════
PIXABAY_API_KEY   = os.getenv("PIXABAY_API_KEY", "")
PEXELS_API_KEY    = os.getenv("PEXELS_API_KEY", "")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "") or os.getenv("CLAUDE_API_KEY", "")
FREESOUND_API_KEY = os.getenv("FREESOUND_API_KEY", "")
JAMENDO_CLIENT_ID = os.getenv("JAMENDO_CLIENT_ID", "")
REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY", "")
DEEPGRAM_API_KEY  = os.getenv("DEEPGRAM_API_KEY", "")

OUTPUT_DIR = pathlib.Path("output")
AUDIO_DIR  = pathlib.Path("audio")
MUSIC_DIR  = pathlib.Path("music")
DB_PATH    = pathlib.Path("shorts_db.db")

FFMPEG_TIMEOUT     = 600
MIN_VIDEO_DURATION = 21
MAX_VIDEO_DURATION = 58   # Never exactly 60 — algorithm edge case

NORM_WIDTH    = 1080
NORM_HEIGHT   = 1920
NORM_FPS      = 30
VIDEO_BITRATE = "12000k"

for d in (OUTPUT_DIR, AUDIO_DIR, MUSIC_DIR):
    d.mkdir(exist_ok=True)

# ── AI models ────────────────────────────────────────────────
GROQ_MODELS  = ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"]
GEMINI_MODEL = "gemini-1.5-flash-001"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# ── Countdown niche: topic buckets that reliably go viral ────
COUNTDOWN_TOPICS = [
    # ── Science / Nature extremes ─────────────────────────
    "the most extreme animals on Earth",
    "the deadliest natural disasters ever recorded",
    "the most venomous creatures on the planet",
    "the weirdest deep-sea creatures discovered",
    "the fastest animals that ever lived",
    "the largest living organisms on Earth",
    "the most dangerous places on Earth",
    "the strangest weather phenomena ever recorded",
    # ── Human body / brain ────────────────────────────────
    "the most shocking things the human brain does",
    "the most bizarre human body facts",
    "the most extreme human survival stories",
    "the weirdest things the human body can survive",
    # ── History / Dark knowledge ──────────────────────────
    "the most mind-blowing ancient civilisation facts",
    "the most shocking historical coincidences",
    "the strangest historical events nobody taught you",
    "the most extreme things people did throughout history",
    # ── Space / Universe ─────────────────────────────────
    "the most terrifying facts about space",
    "the most extreme planets ever discovered",
    "the most mind-blowing facts about our solar system",
    "the strangest things found in space",
    # ── Technology / Science ─────────────────────────────
    "the most extreme scientific experiments ever conducted",
    "the most mind-blowing technology facts",
    "the most shocking AI capabilities that exist right now",
    "the most extreme engineering feats ever built",
    # ── Money / Records ──────────────────────────────────
    "the most insane world records ever set",
    "the most shocking money facts billionaires know",
    "the most extreme things money can buy",
    "the weirdest things that are worth millions",
]

# ── Viral hook templates (MrBeast DNA) ───────────────────────
# {n} = number, {topic} = topic keyword, {superlative} = extreme adjective
HOOK_TEMPLATES = [
    "You won't believe the {n} most {superlative} facts about {topic}.",
    "{n} facts about {topic} that will completely change how you see the world.",
    "Most people never know the {n} most {superlative} things about {topic}.",
    "The {n} most {superlative} {topic} facts scientists don't want you to know.",
    "Scientists are BAFFLED by these {n} facts about {topic}.",
    "{n} {topic} facts so extreme they barely seem real.",
    "Nobody tells you the {n} most shocking facts about {topic}.",
    "These {n} facts about {topic} will keep you up at night.",
    "Wait — do you actually know the {n} most {superlative} things about {topic}?",
    "The {n} most mind-blowing {topic} facts, ranked from wild to INSANE.",
]

SUPERLATIVES = [
    "mind-blowing", "extreme", "shocking", "terrifying",
    "incredible", "insane", "jaw-dropping", "unbelievable",
]


# ══════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════
def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS used_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, video_id TEXT, url TEXT,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(source, video_id))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS used_scripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fact TEXT, script TEXT,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(fact))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fact TEXT, script TEXT,
            title TEXT, length_seconds INTEGER, file_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        if DB_PATH.exists():
            DB_PATH.unlink()
        init_db()


def is_video_used(source, video_id):
    conn = sqlite3.connect(DB_PATH)
    r = conn.execute(
        "SELECT 1 FROM used_videos WHERE source=? AND video_id=?",
        (source, video_id)
    ).fetchone()
    conn.close()
    return r is not None


def mark_video_used(source, video_id, url):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO used_videos (source, video_id, url) VALUES (?,?,?)",
            (source, video_id, url)
        )
        conn.commit()
    finally:
        conn.close()


def is_script_used(fact):
    conn = sqlite3.connect(DB_PATH)
    r = conn.execute(
        "SELECT 1 FROM used_scripts WHERE fact=?", (fact,)
    ).fetchone()
    conn.close()
    return r is not None


def mark_script_used(fact, script=""):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO used_scripts (fact, script) VALUES (?,?)",
            (fact, script)
        )
        conn.commit()
    finally:
        conn.close()


def clear_old_db_entries(days_to_keep=7):
    conn = sqlite3.connect(DB_PATH)
    try:
        cutoff = datetime.now().replace(microsecond=0) - timedelta(days=days_to_keep)
        conn.execute("DELETE FROM used_scripts WHERE used_at < ?", (cutoff,))
        conn.execute("DELETE FROM used_videos  WHERE used_at < ?", (cutoff,))
        conn.commit()
        print(f"  Cleared entries older than {days_to_keep} days")
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════
def get_duration(path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30
        )
        return float(r.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        return 0.0


def _ff(args, label="", timeout=300):
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error"] + args,
            capture_output=True, text=True, timeout=timeout
        )
        if r.returncode != 0:
            raise RuntimeError(f"[{label}]: {r.stderr[:400]}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"[{label}] timed out after {timeout}s")


def _format_srt_time(seconds: float) -> str:
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def extract_keywords(text: str) -> list[str]:
    stop = {
        "the","a","an","is","are","was","were","be","been","being","have","has",
        "had","do","does","did","will","would","could","should","may","might",
        "must","shall","can","to","of","in","for","on","with","at","by","from",
        "as","into","through","during","before","after","above","below","between",
        "under","again","further","then","once","here","there","when","where",
        "why","how","all","each","few","more","most","other","some","such","no",
        "nor","not","only","own","same","so","than","too","very","just","and",
        "but","if","or","because","until","while","about","it","its","this",
        "that","these","those","one","two","three","four","five","six","seven",
        "eight","nine","ten","your","their","our","my","his","her","people",
        "make","get","use","see","find","know","think","take","come","number",
        "fact","facts","things","thing"
    }
    words = re.findall(r'\b\w+\b', text.lower())
    kw = [w for w in words if w not in stop and len(w) > 3]
    kw.sort(key=len, reverse=True)
    return list(dict.fromkeys(kw))[:4]


# ══════════════════════════════════════════════════════════════
# SCRIPT GENERATION  (Countdown / Comparison niche)
# ══════════════════════════════════════════════════════════════

# Compact system prompt — all AI providers receive this verbatim
_SCRIPT_SYSTEM = """You are a viral YouTube Shorts scriptwriter specialising in Countdown / Comparison videos.
Your scripts follow the MrBeast formula:
  1. HOOK (0-3 s)   — Lead with the most shocking stat or claim. Second-person, direct.
  2. AMPLIFY (3-6 s) — Double down. "And most people have NO idea." / "Scientists are still baffled."
  3. RANK-3 (6-11 s) — Third most extreme fact. Short, punchy.
  4. RANK-2 (11-17 s) — Second most extreme fact. One surprising number or comparison.
  5. RANK-1 (17-23 s) — The #1 most mind-blowing fact. Save the best for last.
  6. CTA (23-26 s)  — "Follow for more facts that will blow your mind." — at peak dopamine.

Rules:
- Every sentence must earn its place. Zero filler words.
- Use NUMBERS wherever possible — they stop the scroll.
- Write in plain spoken English, not essay English.
- Total script: 280-380 characters (readable in 21-25 s at 15 chars/s).
- Return ONLY the script text. No labels, no markdown, no intro."""


def _call_groq(prompt: str) -> str | None:
    if not GROQ_API_KEY:
        return None
    model = random.choice(GROQ_MODELS)
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SCRIPT_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                "max_tokens": 300,
                "temperature": 0.9,
            },
            timeout=30,
        )
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"    Groq error: {e}")
        return None


def _call_gemini(prompt: str) -> str | None:
    if not GEMINI_API_KEY:
        return None
    full_prompt = f"{_SCRIPT_SYSTEM}\n\n{prompt}"
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": full_prompt}]}]},
            timeout=30,
        )
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"    Gemini error: {e}")
        return None


def _call_claude(prompt: str) -> str | None:
    if not ANTHROPIC_API_KEY:
        return None
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 300,
                "system": _SCRIPT_SYSTEM,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        data = r.json()
        return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"    Claude error: {e}")
        return None


def generate_countdown_script() -> tuple[str, str]:
    """
    Returns (script_text, topic_string).
    script_text is the full voiceover / caption text.
    """
    topic       = random.choice(COUNTDOWN_TOPICS)
    n           = random.choice([3, 5, 7, 10])
    superlative = random.choice(SUPERLATIVES)
    hook_tmpl   = random.choice(HOOK_TEMPLATES)
    hook        = hook_tmpl.format(n=n, topic=topic, superlative=superlative)

    prompt = (
        f"Topic: {topic}\n"
        f"Number of items: {n}\n"
        f"Hook to open with: \"{hook}\"\n\n"
        f"Write the full {n}-item countdown script using the exact structure from your instructions. "
        f"The hook is already written — continue from AMPLIFY. "
        f"Total script including the hook must be 280-380 characters."
    )

    # Try providers in order: Groq (fastest) → Gemini → Claude
    script = None
    for caller in (_call_groq, _call_gemini, _call_claude):
        result = caller(prompt)
        if result and len(result) >= 80 and not is_script_used(result[:60]):
            script = result
            break

    if not script:
        script = _fallback_script(topic, n)

    # Prepend hook if not already in the script
    if hook.lower()[:30] not in script.lower():
        script = f"{hook} {script}"

    # Deduplicate
    key = script[:80]
    if is_script_used(key):
        topic = random.choice(COUNTDOWN_TOPICS)
    mark_script_used(key, script)

    return script, topic


# ── Fallback scripts (covers offline / all-API-fail scenarios) ─
_FALLBACK_SCRIPTS = [
    (
        "space",
        "You won't believe the 5 most terrifying facts about space. "
        "And most people have absolutely no idea these are real. "
        "Number 3: a neutron star is so dense that one teaspoon weighs 10 million tonnes. "
        "Number 2: there are more stars in the universe than grains of sand on every beach on Earth — combined. "
        "Number 1: the universe is expanding faster than the speed of light RIGHT NOW. "
        "Follow for more facts that will blow your mind."
    ),
    (
        "animals",
        "Most people never know the 5 most extreme animal facts on Earth. "
        "Scientists are still baffled by some of these. "
        "Number 3: a mantis shrimp punch is faster than a bullet. "
        "Number 2: tardigrades can survive in the vacuum of outer space. "
        "Number 1: the immortal jellyfish literally reverses its age and lives forever. "
        "Follow for more facts that will blow your mind."
    ),
    (
        "human body",
        "These 5 facts about the human body will completely change how you see yourself. "
        "And most people have no idea any of this is happening right now. "
        "Number 3: your brain generates 25 watts of electricity — enough to power a light bulb. "
        "Number 2: you have 60,000 miles of blood vessels — enough to circle the Earth twice. "
        "Number 1: every atom in your body is billions of years old and was forged inside a dying star. "
        "Follow for more facts that will blow your mind."
    ),
    (
        "history",
        "Nobody tells you the 5 most shocking historical coincidences. "
        "Number 3: Abraham Lincoln and JFK were both succeeded by a vice-president named Johnson. "
        "Number 2: Oxford University is older than the Aztec empire. "
        "Number 1: Cleopatra lived closer in time to the Moon landing than to the building of the Great Pyramid. "
        "Follow for more facts that will blow your mind."
    ),
    (
        "money",
        "The 5 most insane money facts billionaires already know. "
        "And most people will never learn these. "
        "Number 3: if you earned $5,000 a day since the year 0 AD you still wouldn't be a billionaire yet. "
        "Number 2: the US has more empty houses than it has homeless people. "
        "Number 1: Jeff Bezos earns more money per second than most people earn in a year. "
        "Follow for more facts that will blow your mind."
    ),
]


def _fallback_script(topic: str, n: int) -> str:
    for t, s in _FALLBACK_SCRIPTS:
        if t in topic.lower():
            return s
    random.shuffle(_FALLBACK_SCRIPTS)
    return _FALLBACK_SCRIPTS[0][1]


# ══════════════════════════════════════════════════════════════
# CAPTION ENGINE  (yellow keyword highlights)
# ══════════════════════════════════════════════════════════════

# Words/patterns to highlight in yellow (#FFE600)
_HIGHLIGHT_PATTERNS = re.compile(
    r'\b('
    # Numbers with optional units
    r'\d[\d,\.]*\s*(?:million|billion|trillion|thousand|hundred|'
    r'km|mph|mph|kg|lbs|tonnes?|years?|days?|hours?|seconds?|'
    r'metres?|feet|miles?|volts?|watts?|%|x)?\b'
    # Ordinal rank words (countdown-specific)
    r'|number\s+\d+'
    r'|#\d+'
    r'|1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th'
    # Absolute superlatives
    r'|never|impossible|forever|fastest|largest|smallest|deadliest'
    r'|hottest|coldest|oldest|youngest|rarest|strongest|heaviest'
    r'|most\s+\w+|least\s+\w+'
    # Impact words
    r'|INSANE|MIND-BLOWING|BAFFLED|SHOCKING|TERRIFYING|INCREDIBLE'
    r'|RIGHT NOW|FOREVER|ZERO|NONE|EVERY|ALL'
    r')\b',
    re.IGNORECASE
)


def _tag_highlights(line: str) -> str:
    """Wrap highlight-worthy tokens with custom markers resolved at render time."""
    return _HIGHLIGHT_PATTERNS.sub(
        lambda m: f"\u27e6HIGHLIGHT\u27e7{m.group()}\u27e6/HIGHLIGHT\u27e7",
        line
    )


def process_captions(script: str, video_duration: int) -> list[str]:
    """
    Split script into lines of 32-42 chars.
    Tags key words for yellow highlight rendering.
    Returns list of display lines.
    """
    target_chars = min(380, max(280, int(video_duration * 15)))
    if len(script) > target_chars:
        trimmed = script[:target_chars]
        last_period = max(trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"))
        script = trimmed[:last_period + 1] if last_period > 200 else trimmed

    words = script.split()
    lines, cur, cur_len = [], [], 0
    for word in words:
        wl = len(word)
        new_len = cur_len + (1 if cur else 0) + wl
        if new_len <= 42:
            cur.append(word)
            cur_len = new_len
        else:
            if cur:
                lines.append(" ".join(cur))
            cur, cur_len = [word], wl
    if cur:
        lines.append(" ".join(cur))

    # Merge short lines (< 28 chars) with next to reduce flicker
    i = 0
    while i < len(lines) - 1:
        if len(lines[i]) < 28:
            merged = f"{lines[i]} {lines[i+1]}"
            if len(merged) <= 44:
                lines[i] = merged
                lines.pop(i + 1)
                continue
        i += 1

    lines = [_tag_highlights(ln) for ln in lines]
    return lines


# ══════════════════════════════════════════════════════════════
# CAPTION RENDERER  (word-timestamp sync via Deepgram timings)
# ══════════════════════════════════════════════════════════════

def add_captions(
    video_path: pathlib.Path,
    audio_path: pathlib.Path,
    lines: list[str],
    word_timings: list[dict],
    output_path: pathlib.Path,
):
    """
    Burn captions into video with PERFECT sync to the voiceover.
    Each 2-line display block is timed to the exact word timestamps
    returned by Deepgram, so captions appear/disappear as each word
    is spoken — never drifting from the audio.

    Style: Montserrat-Bold 68px, white body + #FFE600 yellow highlights,
           black outline, bottom-third placement, max 2 lines at once.
    """
    video_duration = get_duration(str(video_path))

    # Group lines into 2-line display blocks
    blocks = []
    for i in range(0, len(lines), 2):
        blocks.append(lines[i:i + 2])

    # ── Map each block to Deepgram word timestamps ────────────
    # Strip highlight markers to count real words per block,
    # then index into word_timings for start/end of that block.
    timings = []
    word_index = 0

    for block in blocks:
        clean_text = " ".join(
            re.sub(r'\u27e6[^⟧]*\u27e7', '', ln)
            for ln in block
        )
        block_words = (
            clean_text
            .replace(".", "").replace(",", "")
            .replace("!", "").replace("?", "")
            .split()
        )
        num_words = len(block_words)

        if word_index >= len(word_timings):
            # Ran out of timestamps — extend last block to video end
            if timings:
                last_start = timings[-1][0]
                timings[-1] = (last_start, video_duration)
            break

        start   = word_timings[word_index]["start"]
        end_idx = min(word_index + num_words - 1, len(word_timings) - 1)
        end     = word_timings[end_idx]["end"]

        timings.append((start, end))
        word_index += num_words

    # Clamp last block to video duration
    if timings:
        last_start, last_end = timings[-1]
        timings[-1] = (last_start, min(last_end, video_duration))

    # ── ASS colour override codes ─────────────────────────────
    # #FFE600 in ASS BGR format = &H00E6FF&
    YELLOW_ASS = r"{\c&H00E6FF&}"
    WHITE_ASS  = r"{\c&H00FFFFFF&}"

    def _to_ass(line: str) -> str:
        return (
            line
            .replace("\u27e6HIGHLIGHT\u27e7", YELLOW_ASS)
            .replace("\u27e6/HIGHLIGHT\u27e7", WHITE_ASS)
        )

    def _fmt_ass_time(s: float) -> str:
        h   = int(s // 3600)
        m   = int((s % 3600) // 60)
        sec = s % 60
        return f"{h}:{m:02d}:{sec:05.2f}"

    # ── Write ASS subtitle file ───────────────────────────────
    font_name = "Montserrat-Bold"
    font_size = 68  # px at 1080×1920; renders ~72pt visually

    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {NORM_WIDTH}
PlayResY: {NORM_HEIGHT}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,5,2,2,40,40,160,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    ass_path = OUTPUT_DIR / "captions.ass"
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        for block, (start, end) in zip(blocks, timings):
            text = r"\N".join(_to_ass(ln) for ln in block)
            f.write(
                f"Dialogue: 0,{_fmt_ass_time(start)},{_fmt_ass_time(end)},"
                f"Default,,0,0,0,,{text}\n"
            )

    # ── Burn captions + mux audio with ffmpeg ─────────────────
    # Windows-safe ASS path: backslash → forward slash, colon → \:
    ass_path_str = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")

    _ff(
        [
            "-i", str(video_path.resolve()),
            "-i", str(audio_path.resolve()),
            "-t", str(video_duration),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-vf", f"ass='{ass_path_str}'",
            "-c:v", "libx264", "-preset", "slow", "-b:v", VIDEO_BITRATE,
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-crf", "18",
            "-shortest",
            str(output_path.resolve()),
        ],
        label="add_captions",
        timeout=300,
    )

    if ass_path.exists():
        ass_path.unlink()


# ══════════════════════════════════════════════════════════════
# YOUTUBE METADATA  (title / description formulas)
# ══════════════════════════════════════════════════════════════

def build_video_title(script: str, topic: str) -> str:
    """
    Generate a viral Shorts title using the countdown formula.
    Rules: ≤60 chars display, ends with #Shorts, uses a number + superlative.
    """
    num_match = re.search(r'\b(\d+)\b', script)
    n = num_match.group(1) if num_match else "5"

    topic_clean = topic.replace("the most ", "").replace("the ", "").title()

    templates = [
        f"{n} {topic_clean} Facts That Will SHOCK You #Shorts",
        f"The {n} Most Extreme {topic_clean} Facts #Shorts",
        f"{n} Mind-Blowing {topic_clean} Facts #Shorts",
        f"You Won't Believe These {n} {topic_clean} Facts #Shorts",
        f"{n} {topic_clean} Facts Nobody Tells You #Shorts",
        f"The {n} Most INSANE {topic_clean} Facts #Shorts",
        f"{n} Shocking {topic_clean} Facts That Change Everything #Shorts",
    ]

    for title in sorted(templates, key=len):
        if len(title) <= 100:
            return title[:100]

    return templates[0][:100]


def build_video_description(script: str, topic: str) -> str:
    """SEO-optimised description: hook line → topic → hashtag block."""
    first_sentence = re.split(r'(?<=[.!?])\s', script)[0]
    kw = extract_keywords(topic + " " + script)[:8]
    kw_tags = " ".join(f"#{w.capitalize()}" for w in kw)

    description = (
        f"{first_sentence}\n\n"
        f"✅ Follow for daily mind-blowing facts!\n"
        f"🔔 Turn on notifications so you never miss one.\n\n"
        f"{kw_tags} "
        f"#Shorts #YouTubeShorts #DidYouKnow #Facts #MindBlowing "
        f"#InterestingFacts #AmazingFacts #Educational #FunFacts "
        f"#Viral #Countdown #TopFacts"
    )
    return description[:5000]


def build_video_tags(script: str, topic: str) -> list[str]:
    """Return up to 30 tags optimised for Shorts discovery."""
    kw = extract_keywords(topic + " " + script)

    base = [
        "shorts", "youtube shorts", "short", "viral",
        "did you know", "facts", "mind blowing facts",
        "interesting facts", "amazing facts", "fun facts",
        "educational", "knowledge", "top facts", "countdown",
        "trending", "learn",
    ]

    topic_tags = [w for w in kw if len(w) > 3]
    all_tags = base + topic_tags
    seen, unique = set(), []
    for t in all_tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique[:30]


# ══════════════════════════════════════════════════════════════
# STOCK VIDEO  (Pexels + Pixabay)
# ══════════════════════════════════════════════════════════════

def get_pexels_videos(query: str, per_page: int = 5) -> list[dict]:
    if not PEXELS_API_KEY:
        return []
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": query, "per_page": per_page, "orientation": "portrait"},
            timeout=30,
        )
        videos = []
        for v in r.json().get("videos", []):
            if not is_video_used("pexels", str(v["id"])):
                portrait_files = [
                    f for f in v["video_files"]
                    if f.get("width", 0) < f.get("height", 1)
                ]
                file_url = (portrait_files or v["video_files"])[0]["link"]
                videos.append({
                    "id": v["id"], "url": file_url,
                    "source": "pexels", "duration": v["duration"],
                })
        return videos
    except Exception as e:
        print(f"    Pexels error: {e}")
        return []


def get_pixabay_videos(query: str, per_page: int = 5) -> list[dict]:
    if not PIXABAY_API_KEY:
        return []
    try:
        r = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": PIXABAY_API_KEY, "q": query,
                    "per_page": per_page, "video_type": "film"},
            timeout=30,
        )
        videos = []
        for v in r.json().get("hits", []):
            if not is_video_used("pixabay", str(v["id"])):
                vfiles = v.get("videos", {})
                url = None
                for sz in ("large", "medium", "small", "tiny"):
                    if sz in vfiles:
                        url = vfiles[sz]["url"]
                        break
                if url:
                    videos.append({
                        "id": v["id"], "url": url,
                        "source": "pixabay", "duration": v.get("duration", 10),
                    })
        return videos
    except Exception as e:
        print(f"    Pixabay error: {e}")
        return []


def download_video(url: str, output_dir: pathlib.Path) -> pathlib.Path:
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    path = output_dir / f"video_{random.randint(10000, 99999)}.mp4"
    with open(path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    return path


def generate_pollinations_image(prompt: str, width: int, height: int) -> pathlib.Path | None:
    try:
        encoded = requests.utils.quote(prompt)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width={width}&height={height}&nologo=true"
        )
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        path = OUTPUT_DIR / f"image_{random.randint(10000, 99999)}.png"
        path.write_bytes(r.content)
        return path
    except Exception as e:
        print(f"    Pollinations error: {e}")
        return None


def create_video_from_image(image_path: pathlib.Path, duration: int) -> pathlib.Path:
    out = OUTPUT_DIR / f"vid_img_{random.randint(10000, 99999)}.mp4"
    _ff([
        "-loop", "1", "-i", str(image_path.resolve()),
        "-vf", (
            f"scale={NORM_WIDTH}:{NORM_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={NORM_WIDTH}:{NORM_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
            f"zoompan=z='min(zoom+0.001,1.1)':d={duration*NORM_FPS}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={NORM_WIDTH}x{NORM_HEIGHT}:fps={NORM_FPS}"
        ),
        "-c:v", "libx264", "-preset", "slow", "-b:v", VIDEO_BITRATE,
        "-r", str(NORM_FPS), "-t", str(duration),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-crf", "18",
        str(out.resolve()),
    ], label="create_video_from_image", timeout=300)
    return out


# ══════════════════════════════════════════════════════════════
# AUDIO  (Voiceover + SFX + Background music)
# ══════════════════════════════════════════════════════════════

def generate_voiceover(
    text: str,
    output_path: pathlib.Path,
) -> tuple[pathlib.Path, list[dict]]:
    """
    Generate AI narration via Deepgram TTS, then transcribe it back
    to get per-word timestamps for perfect caption sync.

    Returns:
        (audio_path, word_timings)
        word_timings: list of {"word": str, "start": float, "end": float}

    Requires: DEEPGRAM_API_KEY in environment.
    """
    if not DEEPGRAM_API_KEY:
        raise ValueError(
            "Missing DEEPGRAM_API_KEY — add it to your .env file. "
            "Get a free key at https://console.deepgram.com"
        )

    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json",
    }

    # ── Step 1: TTS synthesis ─────────────────────────────────
    print("    Synthesising narration (Deepgram TTS)...")
    r = requests.post(
        "https://api.deepgram.com/v1/speak?model=aura-2-thalia-en",
        headers=headers,
        json={"text": text},
        timeout=120,
    )
    r.raise_for_status()
    output_path.write_bytes(r.content)
    vo_dur = get_duration(str(output_path))
    print(f"    Voiceover: {vo_dur:.1f}s")

    # ── Step 2: Transcribe to get word timestamps ─────────────
    print("    Extracting word timestamps...")
    with open(output_path, "rb") as f:
        tr = requests.post(
            "https://api.deepgram.com/v1/listen"
            "?smart_format=true&punctuate=true&model=nova-2",
            headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
            files={"audio": f},
            timeout=120,
        )
    tr.raise_for_status()

    data  = tr.json()
    words = (
        data["results"]["channels"][0]
        ["alternatives"][0]["words"]
    )
    print(f"    {len(words)} word timestamps extracted")
    return output_path, words


def generate_sound_effects(
    keywords: list[str], duration: int, output_path: pathlib.Path
) -> pathlib.Path | None:
    if not FREESOUND_API_KEY:
        return None
    base = keywords[0] if keywords else "ambient"
    queries = [f"{base} ambient", f"{base} dramatic", "cinematic hit",
               "whoosh transition", "impact sound", "dramatic sting"]
    try:
        for q in queries:
            r = requests.get(
                "https://freesound.org/apiv2/search/text/",
                params={
                    "query": q, "token": FREESOUND_API_KEY,
                    "fields": "previews,duration,name,tags",
                    "filter": "duration:[3 TO 15]", "page_size": 10,
                },
                timeout=30,
            )
            results = r.json().get("results", [])
            if results:
                snd = random.choice(results)
                res = requests.get(snd["previews"]["preview-hq-mp3"],
                                   stream=True, timeout=60)
                res.raise_for_status()
                output_path.write_bytes(b"".join(res.iter_content(8192)))
                snd_dur = get_duration(str(output_path))
                if snd_dur < duration:
                    looped = output_path.parent / f"lp_{output_path.name}"
                    _ff(["-stream_loop", "-1", "-i",
                         str(output_path.resolve()), "-c", "copy",
                         "-t", str(duration), str(looped.resolve())],
                        label="loop_sfx", timeout=60)
                    output_path.unlink()
                    return looped
                return output_path
    except Exception as e:
        print(f"    Freesound SFX error: {e}")
    return None


def get_background_music(duration: int) -> pathlib.Path | None:
    """
    Energetic background music for countdown niche.
    Priority: epic / cinematic / upbeat / motivational.
    """
    energetic_tags = [
        "epic", "cinematic", "upbeat", "motivational", "action",
        "dramatic", "powerful", "intense", "adventure", "tension",
    ]

    # ── Jamendo ──────────────────────────────────────────────
    if JAMENDO_CLIENT_ID:
        try:
            for tag in energetic_tags:
                r = requests.get(
                    "https://api.jamendo.com/v3.0/tracks/",
                    params={
                        "client_id": JAMENDO_CLIENT_ID, "limit": 20,
                        "tags": tag, "format": "json",
                        "audiodownloadformat": "mp32",
                    },
                    timeout=30,
                )
                results = r.json().get("results", [])
                valid = [t for t in results if t.get("duration", 0) >= 30]
                if valid:
                    track = random.choice(valid)
                    url = track.get("audiodownload") or track.get("audio")
                    if url:
                        out = MUSIC_DIR / f"music_{random.randint(10000,99999)}.mp3"
                        res = requests.get(url, stream=True, timeout=60)
                        res.raise_for_status()
                        out.write_bytes(b"".join(res.iter_content(8192)))
                        trimmed = MUSIC_DIR / f"trim_{out.name}"
                        _ff(["-i", str(out.resolve()), "-t", str(duration),
                             "-c", "copy", str(trimmed.resolve())],
                            label="trim_music", timeout=60)
                        out.unlink()
                        print(f"    Jamendo: {track.get('name','')}")
                        return trimmed
        except Exception as e:
            print(f"    Jamendo error: {e}")

    # ── Freesound fallback ────────────────────────────────────
    if FREESOUND_API_KEY:
        try:
            for q in ["epic cinematic music", "action music background",
                      "dramatic instrumental"]:
                r = requests.get(
                    "https://freesound.org/apiv2/search/text/",
                    params={
                        "query": q, "token": FREESOUND_API_KEY,
                        "fields": "previews,duration,name",
                        "filter": "duration:[30 TO 300]", "page_size": 10,
                    },
                    timeout=30,
                )
                results = r.json().get("results", [])
                if results:
                    snd = random.choice(results)
                    res = requests.get(snd["previews"]["preview-hq-mp3"],
                                       stream=True, timeout=60)
                    res.raise_for_status()
                    out = MUSIC_DIR / f"music_{random.randint(10000,99999)}.mp3"
                    out.write_bytes(b"".join(res.iter_content(8192)))
                    snd_dur = get_duration(str(out))
                    if snd_dur < duration:
                        lp = out.parent / f"lp_{out.name}"
                        _ff(["-stream_loop", "-1", "-i",
                             str(out.resolve()), "-c", "copy",
                             "-t", str(duration), str(lp.resolve())],
                            label="loop_music", timeout=60)
                        out.unlink()
                        return lp
                    return out
        except Exception as e:
            print(f"    Freesound music error: {e}")

    # ── Last resort: generate tense drone ─────────────────────
    print("    Generating cinematic drone (no music API)...")
    out = MUSIC_DIR / f"drone_{random.randint(10000,99999)}.mp3"
    _ff([
        "-f", "lavfi",
        "-i", "anoisesrc=color=pink:sample_rate=44100",
        "-af", (
            "volume=0.15,"
            "highpass=f=60,lowpass=f=300,"
            "aecho=0.8:0.7:40:0.4"
        ),
        "-t", str(duration),
        str(out.resolve()),
    ], label="generate_drone", timeout=60)
    return out


# ══════════════════════════════════════════════════════════════
# VIDEO NORMALISATION
# ══════════════════════════════════════════════════════════════

def normalise_video(
    video_path: pathlib.Path, video_duration: int, norm_path: pathlib.Path
):
    """Scale + crop to 1080×1920, enforce exact duration."""
    vf = (
        f"scale={NORM_WIDTH}:{NORM_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={NORM_WIDTH}:{NORM_HEIGHT}:(ow-iw)/2:(oh-ih)/2"
    )
    base_args = [
        "-vf", vf,
        "-c:v", "libx264", "-preset", "slow", "-b:v", VIDEO_BITRATE,
        "-r", str(NORM_FPS), "-an",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-crf", "18",
    ]
    v_dur = get_duration(str(video_path))
    if v_dur >= video_duration:
        _ff(["-i", str(video_path.resolve()), "-t", str(video_duration)]
            + base_args + [str(norm_path.resolve())],
            label="normalise_trim", timeout=300)
    else:
        _ff(["-stream_loop", "-1", "-i", str(video_path.resolve()),
             "-t", str(video_duration)] + base_args + [str(norm_path.resolve())],
            label="normalise_loop", timeout=300)


def mix_audio(
    sfx_path: pathlib.Path | None,
    bgm_path: pathlib.Path,
    out_path: pathlib.Path,
    vo_path: pathlib.Path | None = None,
):
    """
    Mix all audio tracks into a single MP3.
    Levels: Voiceover (1.0) → BGM (0.18) → SFX (0.08)
    Voiceover is the dominant track; BGM and SFX are subtle beds.
    """
    inputs       = []
    filter_parts = []
    labels       = []

    # Voiceover — always loudest if present
    if vo_path and vo_path.exists():
        inputs += ["-i", str(vo_path.resolve())]
        idx = len(labels)
        filter_parts.append(f"[{idx}:a]volume=1.0[vo]")
        labels.append("[vo]")

    # Background music
    inputs += ["-i", str(bgm_path.resolve())]
    idx = len(labels)
    filter_parts.append(f"[{idx}:a]volume=0.18[bgm]")
    labels.append("[bgm]")

    # SFX (optional)
    if sfx_path and sfx_path.exists():
        inputs += ["-i", str(sfx_path.resolve())]
        idx = len(labels)
        filter_parts.append(f"[{idx}:a]volume=0.08[sfx]")
        labels.append("[sfx]")

    n              = len(labels)
    mix_inputs_str = "".join(labels)
    filter_complex = (
        ";".join(filter_parts)
        + f";{mix_inputs_str}amix=inputs={n}:duration=first:dropout_transition=2"
    )

    _ff(
        inputs + [
            "-filter_complex", filter_complex,
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(out_path.resolve()),
        ],
        label="mix_audio",
        timeout=120,
    )


# ══════════════════════════════════════════════════════════════
# SHORTS VERIFICATION
# ══════════════════════════════════════════════════════════════

def verify_video_for_shorts(video_path: pathlib.Path) -> bool:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=width,height:format=duration", "-of", "json", str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(r.stdout)
        vs = next(
            (s for s in info.get("streams", []) if s.get("width") and s.get("height")),
            None,
        )
        if not vs:
            print("    [ERROR] No video stream")
            return False

        w, h = int(vs["width"]), int(vs["height"])
        dur  = float(info.get("format", {}).get("duration", 0))
        ar   = w / h if h else 0

        print(f"    Resolution  : {w}x{h}")
        print(f"    Aspect ratio: {ar:.3f}  (target 0.5625)")
        print(f"    Duration    : {dur:.1f}s  (target 21-58s)")

        if w != NORM_WIDTH or h != NORM_HEIGHT:
            print(f"    [FAIL] Resolution not {NORM_WIDTH}x{NORM_HEIGHT}")
            return False
        if not (0.55 <= ar <= 0.58):
            print(f"    [FAIL] Aspect ratio not 9:16")
            return False
        if not (20 < dur < 59):
            print(f"    [FAIL] Duration outside 21-58s")
            return False

        print("    [OK] Passes YouTube Shorts criteria")
        return True
    except Exception as e:
        print(f"    [ERROR] Verification failed: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════

def create_countdown_video() -> tuple[pathlib.Path, str, str, str]:
    """
    Full pipeline for one Countdown / Comparison Short.
    Returns (final_path, script, title, topic).

    Pipeline order:
      1  → Script generation
      1b → Voiceover TTS + word timestamps  (Deepgram)
      2  → Stock video search
      3  → AI image fallback if no video found
      4  → Caption line processing
      5  → Sound effects
      6  → Background music
      7  → Assemble: normalise + mix audio + burn captions
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'='*65}")
    print(f"  Countdown / Comparison Shorts Generator")
    print(f"  Resolution: {NORM_WIDTH}x{NORM_HEIGHT} vertical")
    print(f"{'='*65}")

    # ── 1. Script ─────────────────────────────────────────────
    print("\n[1/7] Generating countdown script...")
    script, topic = generate_countdown_script()
    title         = build_video_title(script, topic)
    print(f"  Topic : {topic}")
    print(f"  Title : {title}")
    print(f"  Script: {script[:120]}...")

    # ── 1b. Voiceover + word timestamps ───────────────────────
    print("\n[1b/7] Generating voiceover + word timestamps...")
    voiceover_path = AUDIO_DIR / f"vo_{ts}.mp3"
    voiceover_path, word_timings = generate_voiceover(script, voiceover_path)
    vo_dur = get_duration(str(voiceover_path))

    # Clamp video duration to voiceover length + 1s breathing room
    video_duration = max(MIN_VIDEO_DURATION, min(int(vo_dur) + 1, MAX_VIDEO_DURATION))
    print(f"  Duration locked to voiceover: {video_duration}s")

    # ── 2. Stock video ────────────────────────────────────────
    print("\n[2/7] Searching stock video...")
    keywords     = extract_keywords(topic + " " + script)
    video_path   = None
    search_terms = []
    if len(keywords) >= 2:
        search_terms.append(f"{keywords[0]} {keywords[1]}")
    search_terms += keywords[:3]
    search_terms += ["cinematic aerial", "nature timelapse", "city timelapse", "cosmos space"]

    for q in search_terms:
        print(f"    Query: '{q}'")
        vids = []
        if PEXELS_API_KEY:
            vids += get_pexels_videos(q)
        if PIXABAY_API_KEY:
            vids += get_pixabay_videos(q)
        if vids:
            try:
                video_path = download_video(vids[0]["url"], OUTPUT_DIR)
                mark_video_used(vids[0]["source"], str(vids[0]["id"]), vids[0]["url"])
                print(f"    Downloaded from {vids[0]['source']}")
                break
            except Exception as e:
                print(f"    Download failed: {e}")

    # ── 3. AI image fallback ──────────────────────────────────
    if not video_path:
        print("\n[3/7] No video found — generating AI image...")
        img_prompt = (
            f"cinematic dramatic {keywords[0] if keywords else topic}, "
            f"4K epic photography, vivid colours, high contrast, "
            f"vertical 9:16 format"
        )
        img = generate_pollinations_image(img_prompt, NORM_WIDTH, NORM_HEIGHT)
        if img:
            video_path = create_video_from_image(img, video_duration)
        else:
            raise ValueError("Could not obtain any video source")
    else:
        print("\n[3/7] Stock video ready.")

    # ── 4. Captions ───────────────────────────────────────────
    print("\n[4/7] Processing captions (yellow highlights enabled)...")
    caption_lines = process_captions(script, video_duration)
    highlight_count = sum(
        ln.count("\u27e6HIGHLIGHT\u27e7") for ln in caption_lines
    )
    print(f"  {len(caption_lines)} caption lines  |  {highlight_count} highlighted tokens")

    # ── 5. Sound effects ──────────────────────────────────────
    print("\n[5/7] Fetching dramatic sound effects...")
    sfx_path = AUDIO_DIR / f"sfx_{random.randint(1000,9999)}.mp3"
    sfx_path = generate_sound_effects(keywords, video_duration, sfx_path)

    # ── 6. Background music ───────────────────────────────────
    print("\n[6/7] Fetching energetic background music...")
    bgm_path = get_background_music(video_duration)
    if not (bgm_path and bgm_path.exists()):
        raise ValueError("Background music unavailable — check API keys or ffmpeg")

    # ── 7. Assemble ───────────────────────────────────────────
    print("\n[7/7] Assembling final video...")
    final_path  = OUTPUT_DIR / f"shorts_{ts}.mp4"
    norm_video  = OUTPUT_DIR / f"norm_{ts}.mp4"
    mixed_audio = AUDIO_DIR  / f"mixed_{ts}.mp3"

    normalise_video(video_path, video_duration, norm_video)
    mix_audio(sfx_path, bgm_path, mixed_audio, vo_path=voiceover_path)
    add_captions(norm_video, mixed_audio, caption_lines, word_timings, final_path)

    # ── Verify ────────────────────────────────────────────────
    print("\n  Verifying Shorts criteria...")
    if not verify_video_for_shorts(final_path):
        raise ValueError("Final video failed Shorts criteria check")

    # ── Cleanup temp files ────────────────────────────────────
    for tmp in [norm_video, mixed_audio, sfx_path, bgm_path, video_path, voiceover_path]:
        try:
            if tmp and pathlib.Path(tmp).exists():
                pathlib.Path(tmp).unlink()
        except Exception:
            pass

    # ── Persist to DB ─────────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO videos (fact, script, title, length_seconds, file_path) "
        "VALUES (?,?,?,?,?)",
        (script[:500], script, title, video_duration, str(final_path)),
    )
    conn.commit()
    conn.close()

    dur  = get_duration(str(final_path))
    size = final_path.stat().st_size / (1024 * 1024)
    print(f"\n{'='*65}")
    print(f"  ✅  DONE")
    print(f"  File    : {final_path}")
    print(f"  Duration: {dur:.0f}s   Size: {size:.0f} MB")
    print(f"  Title   : {title}")
    print(f"{'='*65}\n")

    return final_path, script, title, topic


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    clear_old_db_entries(days_to_keep=7)

    num_videos     = int(os.getenv("NUM_VIDEOS", "3"))
    upload_enabled = os.getenv("UPLOAD_TO_YOUTUBE", "true").lower() == "true"

    print(f"\n{'='*65}")
    print(f"  YouTube Shorts Automation — Countdown / Comparison Niche")
    print(f"  Videos to generate : {num_videos}")
    print(f"  Auto-upload        : {upload_enabled}")
    print(f"{'='*65}\n")

    results: list[tuple[pathlib.Path, str, str, str]] = []

    for i in range(num_videos):
        print(f"\n{'='*65}")
        print(f"  VIDEO {i + 1} / {num_videos}")
        print(f"{'='*65}")
        try:
            res = create_countdown_video()
            results.append(res)
        except Exception as e:
            print(f"\n[ERROR] Video {i+1} failed: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*65}")
    print(f"  {len(results)} / {num_videos} videos generated successfully")
    print(f"{'='*65}\n")

    if upload_enabled and results:
        try:
            from youtube_upload import upload_to_youtube  # type: ignore

            print(f"\n{'='*65}")
            print(f"  Uploading to YouTube Shorts...")
            print(f"{'='*65}\n")

            for idx, (path, script, title, topic) in enumerate(results):
                print(f"\nUploading {idx+1}/{len(results)}: {title}")
                dur  = int(get_duration(str(path)))
                desc = build_video_description(script, topic)
                tags = build_video_tags(script, topic)

                url = upload_to_youtube(
                    file_path        = path,
                    fact             = script,
                    duration_seconds = dur,
                    override_title   = title,
                    override_desc    = desc,
                    override_tags    = tags,
                )
                print(f"  ✅  Live at: {url}")

            print(f"\n{'='*65}")
            print(f"  All Shorts uploaded!")
            print(f"{'='*65}\n")

        except ImportError:
            print("\n[WARNING] youtube_upload.py not found — skipping upload.")
        except Exception as e:
            print(f"\n[ERROR] Upload failed: {e}")
            import traceback
            traceback.print_exc()