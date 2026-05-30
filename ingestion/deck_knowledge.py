"""Format scraped decks and EDHRec data into RAG-friendly documents."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from llama_index.core import Document

try:
    from ingestion.paths import DECK_DIR, KNOWLEDGE_DIR, MANIFEST_PATH
except ImportError:
    from paths import DECK_DIR, KNOWLEDGE_DIR, MANIFEST_PATH

# Guild/shard names that appear on EDHRec /commanders but are not commanders
_COLOR_SLUGS = {
    "azorius", "boros", "selesnya", "dimir", "izzet", "simic",
    "orzhov", "rakdos", "golgari", "gruul", "jund", "naya", "bant",
    "esper", "grixis", "jeskai", "mardu", "sultai", "temur", "abzan",
    "jund", "naya", "bant", "esper", "grixis", "jeskai", "mardu", "sultai",
    "five-color", "partners", "friends-forever", "doctor-who",
}

SECTION_ORDER = (
    "commander",
    "companion",
    "creature",
    "instant",
    "sorcery",
    "artifact",
    "enchantment",
    "planeswalker",
    "battle",
    "land",
    "sideboard",
    "other",
)


def url_to_id(url: str) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    host = urlparse(url).netloc.split(".")[-2] if urlparse(url).netloc else "deck"
    return f"{host}_{digest}"


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80] or "unknown"


def is_valid_commander_slug(slug: str) -> bool:
    if not slug or slug in _COLOR_SLUGS:
        return False
    if slug.isdigit():
        return False
    # Real commanders usually have a hyphenated name
    return "-" in slug or len(slug) > 12


def detect_source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "mtggoldfish" in host:
        return "mtggoldfish"
    if "tappedout" in host:
        return "tappedout"
    if "moxfield" in host:
        return "moxfield"
    if "archidekt" in host:
        return "archidekt"
    if "edhrec" in host:
        return "edhrec"
    return host.replace("www.", "") or "unknown"


def group_cards_by_section(cards: Iterable[Any]) -> dict[str, list[Any]]:
    sections: dict[str, list[Any]] = defaultdict(list)
    for card in cards:
        tags = getattr(card, "tags", set()) or set()
        if "commander" in tags:
            key = "commander"
        elif "companion" in tags:
            key = "companion"
        elif "sideboard" in tags:
            key = "sideboard"
        elif "creature" in tags:
            key = "creature"
        elif "instant" in tags:
            key = "instant"
        elif "sorcery" in tags:
            key = "sorcery"
        elif "artifact" in tags:
            key = "artifact"
        elif "enchantment" in tags:
            key = "enchantment"
        elif "planeswalker" in tags:
            key = "planeswalker"
        elif "land" in tags:
            key = "land"
        else:
            key = "other"
        sections[key].append(card)
    return sections


def cards_to_record(cards: list[Any], url: str, deck_name: str | None = None) -> dict[str, Any]:
    sections = group_cards_by_section(cards)
    commanders = [c.name for c in sections.get("commander", [])]
    commander = commanders[0] if commanders else None
    total = sum(c.quantity for c in cards)
    return {
        "url": url,
        "source": detect_source(url),
        "deck_name": deck_name or _deck_name_from_url(url),
        "commander": commander,
        "color_identity": None,
        "card_count": total,
        "sections": {
            section: [_card_line(c) for c in section_cards]
            for section, section_cards in sections.items()
        },
    }


def _card_line(card: Any) -> str:
    parts = [str(card.quantity), card.name]
    if getattr(card, "extension", None):
        parts.append(f"({card.extension})")
    tags = getattr(card, "tags", None)
    if tags:
        parts.append(f"[{', '.join(sorted(tags))}]")
    return " ".join(parts)


def _deck_name_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/").split("/")[-1]
    return path.replace("-", " ").title() if path else "Commander Deck"


def format_deck_document(record: dict[str, Any]) -> str:
    lines = [
        "=== Commander Deck Intelligence ===",
        f"Type: Competitive/community Commander decklist",
        f"Source: {record.get('source', 'unknown')}",
        f"URL: {record.get('url', '')}",
        f"Deck name: {record.get('deck_name', 'Unknown')}",
    ]
    if record.get("commander"):
        lines.append(f"Commander: {record['commander']}")
    if record.get("color_identity"):
        lines.append(f"Color identity: {', '.join(record['color_identity'])}")
    lines.append(f"Mainboard size: {record.get('card_count', 0)} cards")
    lines.append("")

    for section in SECTION_ORDER:
        cards = record.get("sections", {}).get(section)
        if not cards:
            continue
        header = section.replace("_", " ").title()
        if section == "commander":
            header = "Commander"
        lines.append(f"--- {header} ({len(cards)}) ---")
        lines.extend(cards)
        lines.append("")

    return "\n".join(lines).strip()


def format_edhrec_document(slug: str, page_data: dict[str, Any]) -> str | None:
    container = page_data.get("container") or {}
    json_dict = container.get("json_dict") or {}
    commander = json_dict.get("card") or {}
    if not commander.get("is_commander"):
        return None

    name = commander.get("name") or slug.replace("-", " ").title()
    lines = [
        "=== EDHRec Commander Meta Intelligence ===",
        f"Type: Aggregated Commander meta statistics (EDHRec)",
        f"Commander: {name}",
        f"EDHRec slug: {slug}",
        f"Color identity: {', '.join(commander.get('color_identity') or [])}",
        f"Card type: {commander.get('type', '')}",
        f"Salt score: {round(commander.get('salt', 0), 2)}",
        f"Decks on EDHRec: {commander.get('num_decks', page_data.get('num_decks_avg', 'unknown'))}",
        f"Global rank: #{commander.get('rank', '?')}",
        "",
    ]

    panels = page_data.get("panels") or {}
    themes = panels.get("taglinks") or []
    if themes:
        lines.append("--- Popular themes & archetypes ---")
        for theme in themes[:20]:
            label = theme.get("value") or theme.get("slug")
            count = theme.get("count", "")
            lines.append(f"- {label} ({count} decks)")
        lines.append("")

    combos = panels.get("combocounts") or []
    if combos:
        lines.append("--- Notable combos ---")
        for combo in combos[:12]:
            lines.append(f"- {combo.get('value', combo)}")
        lines.append("")

    similar = page_data.get("similar")
    if isinstance(similar, list) and similar:
        lines.append("--- Similar commanders ---")
        for sim in similar[:10]:
            if isinstance(sim, dict):
                lines.append(f"- {sim.get('name', sim)}")
            else:
                lines.append(f"- {sim}")
        lines.append("")

    for cardlist in json_dict.get("cardlists") or []:
        header = cardlist.get("header") or cardlist.get("tag") or "Cards"
        cardviews = cardlist.get("cardviews") or []
        if not cardviews:
            continue
        lines.append(f"--- {header} ---")
        for cv in cardviews[:25]:
            cname = cv.get("name", "Unknown")
            syn = cv.get("synergy")
            inc = cv.get("inclusion")
            parts = [f"- {cname}"]
            if syn is not None:
                parts.append(f"synergy {round(float(syn) * 100)}%")
            if inc is not None:
                parts.append(f"in {inc} decks")
            lines.append(" ".join(parts))
        lines.append("")

    return "\n".join(lines).strip()


def save_deck_file(record: dict[str, Any], text: str) -> Path:
    DECK_DIR.mkdir(parents=True, exist_ok=True)
    deck_id = record.get("deck_id") or url_to_id(record["url"])
    base = slugify(record.get("commander") or record.get("deck_name") or deck_id)
    path = DECK_DIR / f"deck_{base}.txt"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if record["url"] in existing:
            return path
        path = DECK_DIR / f"deck_{deck_id}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def save_edhrec_file(slug: str, text: str) -> Path:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    path = KNOWLEDGE_DIR / f"edhrec_{slug}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def load_manifest() -> set[str]:
    if not MANIFEST_PATH.exists():
        return set()
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return set(data.get("indexed_ids", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_manifest(indexed_ids: set[str]) -> None:
    DECK_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "indexed_ids": sorted(indexed_ids),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def enrich_legacy_deck_text(raw: str, file_path: Path) -> str:
    if "=== Commander Deck Intelligence ===" in raw:
        return raw
    slug = file_path.stem.replace("deck_", "").replace("_", " ").title()
    lines = [
        "=== Commander Deck Intelligence ===",
        "Type: Commander decklist (legacy scrape)",
        f"Deck slug: {slug}",
        "",
        "--- Mainboard ---",
        raw.strip(),
    ]
    return "\n".join(lines)


def file_to_document(file_path: Path) -> Document:
    raw = file_path.read_text(encoding="utf-8", errors="replace")
    if file_path.parent.name == "knowledge" or file_path.name.startswith("edhrec_"):
        doc_type = "edhrec_meta"
        text = raw if "===" in raw else enrich_legacy_deck_text(raw, file_path)
        source = "edhrec"
    else:
        doc_type = "decklist"
        text = enrich_legacy_deck_text(raw, file_path)
        source = _extract_field(text, "Source:") or _extract_field(text, "Deck slug:")

    commander = _extract_field(text, "Commander:")
    color_line = _extract_field(text, "Color identity:")
    color_identity = ""
    if color_line:
        parts = re.split(r"[, ]+", color_line.upper())
        color_identity = ",".join(sorted(c for c in parts if c in {"W", "U", "B", "R", "G"}))
    doc_id = file_path.stem

    return Document(
        text=text,
        metadata={
            "is_decklist": doc_type == "decklist",
            "is_edhrec_meta": doc_type == "edhrec_meta",
            "doc_type": doc_type,
            "file_name": file_path.name,
            "commander": commander,
            "source": source,
            "name": commander or file_path.stem,
            "color_identity": color_identity or None,
        },
        id_=doc_id,
    )


def _extract_field(text: str, label: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(label):
            return line.split(":", 1)[-1].strip() or None
    return None


def collect_document_files() -> list[Path]:
    files: list[Path] = []
    if DECK_DIR.exists():
        for path in sorted(DECK_DIR.glob("deck_*.txt")):
            files.append(path)
    if KNOWLEDGE_DIR.exists():
        for path in sorted(KNOWLEDGE_DIR.glob("edhrec_*.txt")):
            files.append(path)
    return files
