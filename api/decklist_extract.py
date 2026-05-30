"""Extract Commander decklists from RAG answers and source documents."""

from __future__ import annotations

import re
from typing import Any

# 1 Sol Ring, 1x Sol Ring, 2 Card Name (SET) [commander]
CARD_LINE_RE = re.compile(
    r"^(\d+)\s*x?\s+(.+?)(?:\s+\(([a-z0-9]+)\))?(?:\s+\[([^\]]+)\])?\s*$",
    re.IGNORECASE,
)
SECTION_RE = re.compile(r"^---\s*(.+?)\s*(?:\(\d+\))?\s*---\s*$", re.IGNORECASE)
MIN_DECK_CARDS = 8


def _clean_card_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"\s+", " ", name)
    return name


def _parse_lines(text: str) -> tuple[list[str], str | None, str | None]:
    """Return (card lines as 'qty name', commander, deck name hint)."""
    commander: str | None = None
    deck_name: str | None = None
    card_lines: list[str] = []
    current_section: str | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.startswith("==="):
            continue

        for label in ("Commander:", "Deck name:", "Deck slug:"):
            if line.startswith(label):
                value = line.split(":", 1)[1].strip()
                if label == "Commander:" and value:
                    commander = value
                elif label.startswith("Deck") and value and not deck_name:
                    deck_name = value
                break

        section_match = SECTION_RE.match(line)
        if section_match:
            current_section = section_match.group(1).lower()
            if "commander" in current_section and not commander:
                current_section = "commander"
            continue

        card_match = CARD_LINE_RE.match(line)
        if card_match:
            qty, name, _set_code, tags = card_match.groups()
            name = _clean_card_name(name)
            if not name or len(name) < 2:
                continue
            tag_str = (tags or "").lower()
            if "commander" in tag_str or current_section == "commander":
                if not commander:
                    commander = name
            card_lines.append(f"{qty} {name}")
            continue

        # Bullet or markdown list: "- 1 Sol Ring" / "* Sol Ring"
        bullet = re.match(r"^[-*•]\s*(?:(\d+)\s*x?\s+)?(.+)$", line, re.I)
        if bullet:
            qty, name = bullet.groups()
            qty = qty or "1"
            name = _clean_card_name(name)
            if name and not name.endswith(":"):
                card_lines.append(f"{qty} {name}")

    return card_lines, commander, deck_name


def _dedupe_card_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.lower()
        if key not in seen:
            seen.add(key)
            out.append(line)
    return out


def _build_result(
    card_lines: list[str],
    commander: str | None,
    deck_name: str | None,
    description: str | None = None,
) -> dict[str, Any] | None:
    card_lines = _dedupe_card_lines(card_lines)
    if len(card_lines) < MIN_DECK_CARDS:
        return None
    cards_text = "\n".join(card_lines)
    if not commander:
        commander = _guess_commander_from_cards(card_lines)
    return {
        "commander": commander,
        "name": deck_name,
        "cards": cards_text,
        "card_count": len(card_lines),
        "description": description,
    }


def _guess_commander_from_cards(card_lines: list[str]) -> str | None:
    for line in card_lines[:5]:
        name = line.split(" ", 1)[-1] if " " in line else line
        if "," in name or "the " in name.lower():
            return name
    return None


def extract_from_text(text: str, description: str | None = None) -> dict[str, Any] | None:
    if not text or "=== EDHRec Commander Meta" in text:
        return None
    card_lines, commander, deck_name = _parse_lines(text)
    return _build_result(card_lines, commander, deck_name, description)


def extract_decklist(
    answer: str,
    sources: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Pull a decklist from deck sources first, then the model answer.
    sources items may include full 'text' (preferred) and 'snippet'.
    """
    deck_sources = [
        s
        for s in sources
        if (s.get("metadata") or {}).get("is_decklist")
        or "Commander Deck Intelligence" in (s.get("text") or s.get("snippet") or "")
    ]

    for src in deck_sources:
        text = src.get("text") or src.get("snippet") or ""
        meta = src.get("metadata") or {}
        commander = meta.get("commander")
        parsed = extract_from_text(text)
        if parsed:
            if commander and not parsed.get("commander"):
                parsed["commander"] = commander
            if meta.get("name") and not parsed.get("name"):
                parsed["name"] = meta.get("name")
            return parsed

    parsed = extract_from_text(answer)
    if parsed:
        return parsed

    # Merge card lines from all sources when answer is prose + lists in context
    combined: list[str] = []
    commander: str | None = None
    for src in sources:
        text = src.get("text") or src.get("snippet") or ""
        lines, cmd, _ = _parse_lines(text)
        combined.extend(lines)
        if cmd and not commander:
            commander = cmd

    return _build_result(combined, commander, None)
