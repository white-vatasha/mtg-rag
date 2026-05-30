"""Discover Commander deck URLs and EDHRec commander slugs."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from ingestion.deck_knowledge import detect_source, is_valid_commander_slug
except ImportError:
    from deck_knowledge import detect_source, is_valid_commander_slug

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# High-signal Commander decks (metagame / primers) — always attempted first
SEED_DECK_URLS = [
    "https://www.mtggoldfish.com/deck/5785902",
    "https://www.mtggoldfish.com/deck/5790505",
    "https://www.mtggoldfish.com/deck/5794893",
    "https://www.mtggoldfish.com/deck/5780829",
    "https://tappedout.net/mtg-decks/bragos-ragtime-blinkers/",
    "https://tappedout.net/mtg-decks/14-04-26-winota/",
    "https://tappedout.net/mtg-decks/weaponized-tuberculosis-auntie-ool-primer/",
    "https://tappedout.net/mtg-decks/zurgos-workforce-reduction-plan-zurgo-primer/",
]

# Top-tier commanders for EDHRec meta pages
SEED_EDHREC_SLUGS = [
    "korvold-fae-cursed-king",
    "kinnan-bonder-of-kin",
    "thrasios-triton-hero",
    "najeela-the-harbinger",
    "yuriko-the-tigers-shadow",
    "the-first-sliver",
    "winota-joiner-of-forces",
    "atraxa-praetors-voice",
    "magda-brazen-outlaw",
    "krenko-mob-boss",
    "miirym-baleful-flame",
    "esika-god-of-the-tree",
    "tergrid-god-of-horrors",
    "yawgmoth-thran-physician",
    "krark-the-thumbless",
    "jeska-thrice-reborn",
    "rocco-cabaretti-caterer",
    "malcolm-keen-eyed-navigator",
    "maralen-of-the-mornsong",
    "prossh-skyraider-of-kher",
    "scion-of-the-ur-dragon",
]


def _fetch_html(url: str, session: requests.Session, timeout: int = 20) -> str | None:
    try:
        resp = session.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        print(f"  fetch failed {url}: {exc}")
        return None


def scrape_edhrec_commander_slugs(session: requests.Session, limit: int = 60) -> list[str]:
    """Commander slugs from EDHRec rankings page."""
    slugs: list[str] = []
    html = _fetch_html("https://edhrec.com/commanders", session)
    if not html:
        return slugs

    found = re.findall(r"/commanders/([a-z0-9-]+)", html)
    for slug in found:
        if is_valid_commander_slug(slug) and slug not in slugs:
            slugs.append(slug)
        if len(slugs) >= limit:
            break
    return slugs


def scrape_goldfish_commander_decks(session: requests.Session, limit: int = 80) -> list[str]:
    urls: list[str] = []
    for page_url in (
        "https://www.mtggoldfish.com/metagame/commander",
        "https://www.mtggoldfish.com/metagame/commander/combo",
        "https://www.mtggoldfish.com/metagame/commander/mid",
    ):
        html = _fetch_html(page_url, session)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/deck/" not in href:
                continue
            match = re.search(r"/deck/(\d+)", href)
            if not match:
                continue
            full = urljoin("https://www.mtggoldfish.com", f"/deck/{match.group(1)}")
            if full not in urls:
                urls.append(full)
            if len(urls) >= limit:
                return urls
    return urls


def scrape_tappedout_decks(session: requests.Session, limit: int = 60) -> list[str]:
    urls: list[str] = []
    html = _fetch_html("https://tappedout.net/mtg-decks", session)
    if not html:
        return urls

    soup = BeautifulSoup(html, "html.parser")
    skip = {"deck-update", "deckcycle", "search", "login", "accounts"}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/mtg-decks/" not in href:
            continue
        if any(s in href for s in skip):
            continue
        parts = href.strip("/").split("/")
        if len(parts) < 2 or parts[-1] in ("mtg-decks", "commander"):
            continue
        full = urljoin("https://tappedout.net", href)
        if full not in urls:
            urls.append(full)
        if len(urls) >= limit:
            break
    return urls


def collect_deck_urls(
    session: requests.Session,
    max_urls: int = 120,
) -> list[str]:
    """Merge seed + discovered deck URLs, Commander-relevant hosts only."""
    seen: set[str] = set()
    ordered: list[str] = []

    def add(url: str) -> None:
        if url in seen:
            return
        if not _is_supported_deck_url(url):
            return
        seen.add(url)
        ordered.append(url)

    for url in SEED_DECK_URLS:
        add(url)
    for url in scrape_goldfish_commander_decks(session, limit=max_urls):
        add(url)
    for url in scrape_tappedout_decks(session, limit=max_urls // 2):
        add(url)

    return ordered[:max_urls]


def collect_edhrec_slugs(session: requests.Session, max_slugs: int = 50) -> list[str]:
    slugs: list[str] = []
    seen: set[str] = set()

    def add(slug: str) -> None:
        if slug in seen or not is_valid_commander_slug(slug):
            return
        seen.add(slug)
        slugs.append(slug)

    for slug in SEED_EDHREC_SLUGS:
        add(slug)
    for slug in scrape_edhrec_commander_slugs(session, limit=max_slugs):
        add(slug)
    return slugs[:max_slugs]


def _is_supported_deck_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(
        domain in host
        for domain in ("mtggoldfish.com", "tappedout.net", "moxfield.com", "archidekt.com")
    )


def parse_edhrec_page(html: str) -> dict | None:
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return None
    import json

    try:
        payload = json.loads(match.group(1))
        return payload["props"]["pageProps"]["data"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
