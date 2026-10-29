"""Transactional, single-use offline episode reserve for Fact Voltage."""

from __future__ import annotations

import hashlib
import itertools
import json
import pathlib
import sqlite3
from datetime import datetime, timedelta, timezone

from ai_generator import validate_package


RESERVE_PATH = pathlib.Path("fact_voltage_prompt_reserve.sqlite3")
RESERVE_SIZE = 2304

# Carefully worded evergreen facts. Each generated row combines three different
# subjects, so titles, scripts, and visual plans remain unique.
FACTS = (
    ("Neutron Star", "space", "A teaspoon of neutron-star material would weigh about a billion tons on Earth.", "neutron star space animation close view"),
    ("Venus Day", "space", "Venus takes about 243 Earth days to rotate once, longer than its 225-day year.", "planet Venus rotating scientific animation"),
    ("Sunlight", "space", "Sunlight needs about eight minutes and twenty seconds to reach Earth.", "sunlight traveling from Sun to Earth animation"),
    ("Moon Drift", "space", "Laser measurements show the Moon moves roughly 3.8 centimeters farther from Earth each year.", "Moon Earth distance laser observatory animation"),
    ("Olympus Mons", "space", "Mars's Olympus Mons rises about 22 kilometers, nearly two and a half Everests above its surroundings.", "Olympus Mons Mars volcano orbital view"),
    ("Octopus Hearts", "animals", "An octopus has three hearts, and two pump blood specifically through its gills.", "octopus swimming underwater close up"),
    ("Peregrine Dive", "animals", "A diving peregrine falcon can exceed 320 kilometers per hour.", "peregrine falcon diving slow motion sky"),
    ("Blue Whale Heart", "animals", "A blue whale's heart can weigh around 180 kilograms, about as much as a large motorcycle.", "blue whale swimming ocean cinematic wide shot"),
    ("Hummingbird Wings", "animals", "Some hummingbirds beat their wings more than 50 times each second.", "hummingbird hovering wings slow motion flowers"),
    ("Tardigrade Pause", "animals", "Tardigrades can shut down almost all metabolism and survive for years in a dry state.", "tardigrade microscope scientific footage"),
    ("Blood Vessels", "body", "An adult's blood vessels total roughly 100,000 kilometers, enough to circle Earth more than twice.", "human blood vessels medical animation full body"),
    ("Brain Power", "body", "The human brain runs on roughly 20 watts while coordinating billions of nerve cells.", "human brain neurons electrical medical animation"),
    ("Skin Renewal", "body", "The outer layer of human skin continually renews, with many cells replaced in about a month.", "human skin cells microscope medical animation"),
    ("Blink Time", "body", "A typical blink lasts only a fraction of a second, yet people blink thousands of times daily.", "human eye blinking macro slow motion"),
    ("Lung Surface", "body", "The lungs' gas-exchange surface spans dozens of square meters, packed inside the chest.", "human lungs alveoli medical 3D animation"),
    ("Roman Concrete", "history", "Some Roman marine concrete became more resilient as seawater triggered new mineral growth.", "ancient Roman harbor concrete ruins underwater"),
    ("Oxford Age", "history", "Teaching at Oxford began centuries before the Aztec Empire was founded.", "Oxford medieval college historic aerial"),
    ("Antikythera", "history", "The two-thousand-year-old Antikythera mechanism used intricate gears to model astronomical cycles.", "Antikythera mechanism gears museum close up"),
    ("Great Pyramid", "history", "The Great Pyramid stood as the world's tallest human-made structure for nearly four millennia.", "Great Pyramid Giza cinematic aerial sunrise"),
    ("Printing Speed", "history", "Movable-type printing let one set of letters create many pages instead of carving every page anew.", "Gutenberg printing press movable type close up"),
    ("Deepest Ocean", "ocean", "Challenger Deep lies nearly 11 kilometers below sea level, deeper than Everest is tall.", "Mariana Trench submersible deep ocean animation"),
    ("Ocean Coverage", "ocean", "Ocean covers about 71 percent of Earth's surface.", "Earth oceans satellite view rotating planet"),
    ("Hydrothermal Vents", "ocean", "Hydrothermal-vent ecosystems survive without sunlight by using chemical energy.", "hydrothermal vent black smoker deep sea life"),
    ("Giant Kelp", "ocean", "In ideal conditions, giant kelp can grow more than 30 centimeters in a day.", "giant kelp forest underwater sun rays"),
    ("Lightning Heat", "weather", "A lightning channel can become several times hotter than the surface of the Sun.", "lightning strike super slow motion storm"),
    ("Cloud Weight", "weather", "A modest cumulus cloud can contain hundreds of tons of suspended water droplets.", "large cumulus cloud timelapse blue sky"),
    ("Antarctic Desert", "weather", "Antarctica is Earth's largest desert because its interior receives extremely little precipitation.", "Antarctica dry valleys aerial landscape"),
    ("Raindrop Shape", "weather", "Large falling raindrops flatten underneath like tiny buns; they are not tear-shaped.", "raindrops falling macro high speed camera"),
    ("GPS Relativity", "technology", "GPS satellites need relativity corrections or position errors would grow by kilometers each day.", "GPS satellites orbit Earth technology animation"),
    ("First Computer Bug", "technology", "A moth found in a 1947 relay was taped into a logbook as an actual computer bug.", "Harvard Mark II computer moth logbook archive"),
    ("Fiber Optics", "technology", "A strand of optical fiber guides light through repeated internal reflection.", "fiber optic cables glowing macro technology"),
    ("QR Recovery", "technology", "QR codes use error correction, so many remain readable even when part of the pattern is damaged.", "QR code scanning error correction animation"),
)


def _connect(path: pathlib.Path = RESERVE_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _package(index: int, cards: tuple[tuple[str, str, str, str], ...]) -> dict:
    names = [card[0] for card in cards]
    topic = " • ".join(names)
    title = f"{names[0]} vs {names[1]} vs {names[2]}"
    # Keep the exact rank structure and a locked CTA for validator + narration.
    script = (
        f"These three measurements make normal scale feel broken. "
        f"Watch how fast the scale rises from strange to almost impossible. "
        f"The first sounds wild. The last changes perspective. "
        f"Number 3: {cards[0][2]} Number 2: {cards[1][2]} "
        f"Number 1: {cards[2][2]} Subscribe for another fact surge."
    )
    return validate_package({
        "title": title,
        "script": script,
        "topic": topic,
        "tags": ["facts", "science", "history", "technology", "nature", "comparison", "countdown", "shorts"],
        "visual_queries": [card[3] for card in cards],
        "hook_overlay": "NORMAL SCALE JUST BROKE",
        "hook_accent": "BROKE",
        "source": f"reserve:{index}",
    })


def seed(path: pathlib.Path = RESERVE_PATH, target: int = RESERVE_SIZE) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS prompt_reserve (
        id INTEGER PRIMARY KEY,
        fingerprint TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        normalized_title TEXT NOT NULL UNIQUE,
        package_json TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'available' CHECK(state IN ('available','reserved')),
        reserved_at TEXT
    )""")
    existing = conn.execute("SELECT COUNT(*) FROM prompt_reserve").fetchone()[0]
    if existing < target:
        # A stable hash order avoids adjacent rows sharing the same subjects.
        combinations = list(itertools.combinations(FACTS, 3))
        combinations.sort(key=lambda cards: hashlib.sha256("|".join(c[0] for c in cards).encode()).hexdigest())
        for index, cards in enumerate(combinations[:target], 1):
            package = _package(index, cards)
            blob = json.dumps(package, ensure_ascii=False, sort_keys=True)
            fingerprint = hashlib.sha256(blob.encode()).hexdigest()
            conn.execute(
                "INSERT OR IGNORE INTO prompt_reserve(id,fingerprint,title,normalized_title,package_json) VALUES(?,?,?,?,?)",
                (index, fingerprint, package["title"], package["normalized_title"], blob),
            )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM prompt_reserve").fetchone()[0]
    conn.close()
    return count


def reclaim_stale(path: pathlib.Path = RESERVE_PATH, hours: int = 6) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = _connect(path)
    conn.execute(
        "UPDATE prompt_reserve SET state='available', reserved_at=NULL WHERE state='reserved' AND reserved_at < ?",
        (cutoff,),
    )
    conn.commit()
    conn.close()


def reserve(path: pathlib.Path = RESERVE_PATH) -> tuple[int, dict]:
    seed(path)
    reclaim_stale(path)
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id,package_json FROM prompt_reserve WHERE state='available' ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
        if not row:
            raise RuntimeError("The offline prompt reserve is empty")
        conn.execute(
            "UPDATE prompt_reserve SET state='reserved', reserved_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), row["id"]),
        )
        conn.commit()
        return int(row["id"]), json.loads(row["package_json"])
    finally:
        conn.close()


def release(reserve_id: int, path: pathlib.Path = RESERVE_PATH) -> None:
    conn = _connect(path)
    conn.execute("UPDATE prompt_reserve SET state='available', reserved_at=NULL WHERE id=?", (reserve_id,))
    conn.commit()
    conn.close()


def consume(reserve_id: int, path: pathlib.Path = RESERVE_PATH) -> None:
    """Permanently delete only after the corresponding video is uploaded."""
    conn = _connect(path)
    conn.execute("DELETE FROM prompt_reserve WHERE id=? AND state='reserved'", (reserve_id,))
    conn.commit()
    conn.close()


def stats(path: pathlib.Path = RESERVE_PATH) -> dict[str, int]:
    conn = _connect(path)
    values = {
        "total": conn.execute("SELECT COUNT(*) FROM prompt_reserve").fetchone()[0],
        "available": conn.execute("SELECT COUNT(*) FROM prompt_reserve WHERE state='available'").fetchone()[0],
        "unique_titles": conn.execute("SELECT COUNT(DISTINCT normalized_title) FROM prompt_reserve").fetchone()[0],
        "unique_packages": conn.execute("SELECT COUNT(DISTINCT fingerprint) FROM prompt_reserve").fetchone()[0],
    }
    conn.close()
    return values


if __name__ == "__main__":
    print(json.dumps({"seeded": seed(), **stats()}, indent=2))
