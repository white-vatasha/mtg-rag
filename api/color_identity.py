"""Parse and enforce Commander color identity in RAG queries."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

try:
    from ingestion.paths import CARDS_JSON
except ImportError:
    from pathlib import Path

    CARDS_JSON = Path(__file__).resolve().parent.parent / "context" / "AtomicCards.json"

WUBRG = ("W", "U", "B", "R", "G")

GUILD_COLORS: dict[str, frozenset[str]] = {
    "azorius": frozenset({"U", "W"}),
    "orzhov": frozenset({"B", "W"}),
    "boros": frozenset({"R", "W"}),
    "selesnya": frozenset({"G", "W"}),
    "dimir": frozenset({"B", "U"}),
    "izzet": frozenset({"R", "U"}),
    "simic": frozenset({"G", "U"}),
    "rakdos": frozenset({"B", "R"}),
    "golgari": frozenset({"B", "G"}),
    "gruul": frozenset({"G", "R"}),
    "esper": frozenset({"B", "U", "W"}),
    "grixis": frozenset({"B", "R", "U"}),
    "jeskai": frozenset({"R", "U", "W"}),
    "mardu": frozenset({"B", "R", "W"}),
    "sultai": frozenset({"B", "G", "U"}),
    "temur": frozenset({"G", "R", "U"}),
    "abzan": frozenset({"B", "G", "W"}),
    "jund": frozenset({"B", "G", "R"}),
    "naya": frozenset({"G", "R", "W"}),
    "bant": frozenset({"G", "U", "W"}),
}

COLOR_WORDS: dict[str, str] = {
    "white": "W",
    "blue": "U",
    "black": "B",
    "red": "R",
    "green": "G",
}

COLOR_PAIRS: dict[frozenset[str], tuple[str, str]] = {
    frozenset({"R", "U"}): ("Izzet", "NOT Azorius (white-blue)"),
    frozenset({"U", "W"}): ("Azorius", "NOT Izzet (blue-red)"),
    frozenset({"R", "W"}): ("Boros", "NOT Rakdos (black-red)"),
    frozenset({"B", "R"}): ("Rakdos", "NOT Boros (white-red)"),
}

COLOR_TAG = "COLOR_IDENTITY_REQUIRED"
COLOR_TAG_RE = re.compile(
    rf"{COLOR_TAG}:\s*([WUBRG,\s]+)(?:\s*\|\s*guild=([a-z]+))?",
    re.I,
)
IDENTITY_LINE_RE = re.compile(r"Color identity:\s*([WUBRG,\s/]+)", re.I)


@dataclass(frozen=True)
class ColorRequest:
    colors: frozenset[str]
    guild: str | None
    label: str

    @property
    def sorted_str(self) -> str:
        order = {c: i for i, c in enumerate(WUBRG)}
        return ", ".join(sorted(self.colors, key=lambda c: order[c]))


def _color_name(code: str) -> str:
    names = {v: k.title() for k, v in COLOR_WORDS.items()}
    return names.get(code, code)


def _parse_mana_symbols(text: str) -> frozenset[str]:
    return frozenset(m.group(1).upper() for m in re.finditer(r"\{([WUBRG])\}", text, re.I))


def parse_color_request(question: str) -> ColorRequest | None:
    """Detect color identity constraints from a natural-language deck request."""
    q = question.lower()
    colors: set[str] = set()
    guild: str | None = None

    for name, code in COLOR_WORDS.items():
        if re.search(rf"\b{name}\b", q):
            colors.add(code)

    for guild_name, guild_colors in GUILD_COLORS.items():
        if re.search(rf"\b{guild_name}\b", q):
            guild = guild_name
            colors |= set(guild_colors)

    if re.search(r"\b(?:blue[\s\-/]+red|red[\s\-/]+blue)\b", q):
        colors.update({"U", "R"})
    if re.search(r"(?<![a-z])ur(?![a-z])", q):
        colors.update({"U", "R"})
    if re.search(r"(?<![a-z])wu(?![a-z])", q):
        colors.update({"W", "U"})

    colors |= set(_parse_mana_symbols(question))

    if not colors:
        return None

    color_set = frozenset(colors)
    if guild is None:
        for gname, gcolors in GUILD_COLORS.items():
            if gcolors == color_set:
                guild = gname
                break

    label_parts = [_color_name(c) for c in sorted(color_set, key=WUBRG.index)]
    label = "-".join(label_parts)
    if guild:
        label = f"{label} ({guild.title()})"
    pair_hint = COLOR_PAIRS.get(color_set)
    if pair_hint:
        label = f"{label} — {pair_hint[0]}; {pair_hint[1]}"

    return ColorRequest(colors=color_set, guild=guild, label=label)


def augment_query(question: str, color_req: ColorRequest | None) -> str:
    if not color_req:
        return question
    guild_part = f" | guild={color_req.guild}" if color_req.guild else ""
    excluded = [g for g, gc in GUILD_COLORS.items() if gc != color_req.colors]
    exclude_note = ", ".join(excluded[:6])
    return (
        f"{COLOR_TAG}: {color_req.sorted_str}{guild_part}\n"
        f"MANDATORY: Commander and deck must use ONLY these colors: {color_req.sorted_str}. "
        f"{color_req.label}. "
        f"Do NOT recommend guilds/commanders outside this identity (e.g. avoid {exclude_note}).\n"
        f"User question: {question}"
    )


def format_prompt_constraints(color_req: ColorRequest | None) -> str:
    if not color_req:
        return ""
    return (
        f"\nCOLOR CONSTRAINT: The user requires a {color_req.label} deck "
        f"with color identity exactly [{color_req.sorted_str}] only. "
        f"Never substitute a different two-color pair (blue+red is Izzet UR, not Azorius WU). "
        f"Only suggest commanders and cards legal in that identity.\n"
    )


@lru_cache(maxsize=1)
def _card_color_index() -> dict[str, frozenset[str]]:
    if not CARDS_JSON.exists():
        return {}
    with open(CARDS_JSON, encoding="utf-8") as f:
        data = json.load(f)["data"]
    index: dict[str, frozenset[str]] = {}
    for name, versions in data.items():
        ci = versions[0].get("colorIdentity") or []
        index[name] = frozenset(ci)
    return index


def _colors_from_text(text: str) -> frozenset[str] | None:
    match = IDENTITY_LINE_RE.search(text)
    if match:
        raw = match.group(1).replace("/", ",")
        found = {c.strip().upper() for c in re.split(r"[, ]+", raw) if c.strip().upper() in WUBRG}
        if found:
            return frozenset(found)
    return None


def _colors_from_node(text: str, metadata: dict) -> frozenset[str] | None:
    from_text = _colors_from_text(text)
    if from_text:
        return from_text

    ci_meta = metadata.get("color_identity")
    if ci_meta:
        parts = {c.strip().upper() for c in str(ci_meta).split(",") if c.strip().upper() in WUBRG}
        if parts:
            return frozenset(parts)

    commander = metadata.get("commander")
    if commander:
        colors = _card_color_index().get(str(commander))
        if colors:
            return colors

    # Penalize wrong guild names in snippet when we can infer intended colors
    return None


def node_color_score(text: str, metadata: dict, required: frozenset[str]) -> float:
    """Higher = better match. Negative = clearly wrong identity."""
    node_colors = _colors_from_node(text, metadata)
    if node_colors is None:
        return 0.0

    if node_colors == required:
        return 2.0
    if node_colors.issubset(required) and node_colors:
        return 1.0
    if required.issubset(node_colors) and len(node_colors) > len(required):
        return 0.3

    # Wrong identity (e.g. WU deck when UR asked)
    extra = node_colors - required
    missing = required - node_colors
    if extra or missing:
        return -2.0
    return 0.0


def filter_nodes_by_color(nodes: list, required: frozenset[str], keep: int = 10) -> list:
    """Re-rank and drop retrieval nodes that conflict with required colors."""
    if not required or not nodes:
        return nodes

    scored = []
    for node in nodes:
        text = getattr(node, "text", None) or getattr(node, "get_content", lambda: "")()
        meta = dict(getattr(node, "metadata", None) or {})
        score = node_color_score(text, meta, required)
        # Textual guild mismatch penalty
        lower = text.lower()
        for guild, gcolors in GUILD_COLORS.items():
            if guild in lower and gcolors != required:
                score -= 1.5
        scored.append((score, node))

    scored.sort(key=lambda x: x[0], reverse=True)
    # Drop strongly mismatched unless we'd have almost nothing
    filtered = [n for s, n in scored if s >= -1.0]
    if len(filtered) < 3:
        filtered = [n for _, n in scored[:keep]]
    return filtered[:keep]


def parse_colors_from_augmented_query(query: str) -> frozenset[str] | None:
    match = COLOR_TAG_RE.search(query)
    if not match:
        return None
    raw = match.group(1)
    found = {c.strip().upper() for c in re.split(r"[, ]+", raw) if c.strip().upper() in WUBRG}
    return frozenset(found) if found else None


def answer_violates_colors(answer: str, required: frozenset[str]) -> str | None:
    """Return a correction note if the answer names a conflicting guild."""
    lower = answer.lower()
    for guild, gcolors in GUILD_COLORS.items():
        if guild in lower and gcolors != required:
            pair = COLOR_PAIRS.get(required)
            expected = pair[0] if pair else _color_label(required)
            return (
                f"\n\n*Color correction: You asked for {_color_label(required)}. "
                f"{guild.title()} is {_guild_label(gcolors)}, not the same as your request. "
                f"Try commanders in {expected} instead.*"
            )
    return None


def _color_label(colors: frozenset[str]) -> str:
    return ", ".join(_color_name(c) for c in sorted(colors, key=WUBRG.index))


def _guild_label(colors: frozenset[str]) -> str:
    for name, gc in GUILD_COLORS.items():
        if gc == colors:
            return f"{name.title()} ({_color_label(colors)})"
    return _color_label(colors)
