"""
Scrape Commander decklists and EDHRec meta intelligence for the RAG index.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import mtg_parser
import requests
from llama_index.core import Document

try:
    from ingestion.deck_knowledge import (
        cards_to_record,
        collect_document_files,
        file_to_document,
        format_deck_document,
        format_edhrec_document,
        load_manifest,
        save_deck_file,
        save_edhrec_file,
        save_manifest,
        slugify,
        url_to_id,
    )
    from ingestion.deck_sources import (
        collect_deck_urls,
        collect_edhrec_slugs,
        parse_edhrec_page,
    )
    from ingestion.paths import DECK_DIR, KNOWLEDGE_DIR
except ImportError:
    from deck_knowledge import (
        cards_to_record,
        collect_document_files,
        file_to_document,
        format_deck_document,
        format_edhrec_document,
        load_manifest,
        save_deck_file,
        save_edhrec_file,
        save_manifest,
        slugify,
        url_to_id,
    )
    from deck_sources import (
        collect_deck_urls,
        collect_edhrec_slugs,
        parse_edhrec_page,
    )
    from paths import DECK_DIR, KNOWLEDGE_DIR

# Tune these for scrape runs (lower delay + limits for dev; raise for production crawls)
MAX_NEW_DECKS_PER_RUN = 40
MAX_EDHREC_COMMANDERS = 45
DECK_FETCH_DELAY = (4.0, 8.0)
EDHREC_DELAY = (1.0, 2.5)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


def _sleep(range_seconds: tuple[float, float]) -> None:
    wait = random.uniform(*range_seconds)
    print(f"  waiting {wait:.1f}s…")
    time.sleep(wait)


def _existing_deck_urls() -> set[str]:
    urls: set[str] = set()
    if not DECK_DIR.exists():
        return urls
    for path in DECK_DIR.glob("deck_*.txt"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith("URL:"):
                urls.add(line.split(":", 1)[1].strip())
                break
    return urls


def _existing_edhrec_slugs() -> set[str]:
    if not KNOWLEDGE_DIR.exists():
        return set()
    return {p.stem.replace("edhrec_", "") for p in KNOWLEDGE_DIR.glob("edhrec_*.txt")}


def scrape_edhrec_knowledge(
    session: requests.Session,
    slugs: list[str] | None = None,
    max_new: int = MAX_EDHREC_COMMANDERS,
) -> int:
    """Download EDHRec commander meta pages (synergies, themes, top cards)."""
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    if slugs is None:
        print("Discovering EDHRec commander slugs…")
        slugs = collect_edhrec_slugs(session, max_slugs=max_new + 20)

    already = _existing_edhrec_slugs()
    saved = 0

    for slug in slugs:
        if saved >= max_new:
            break
        if slug in already:
            continue

        url = f"https://edhrec.com/commanders/{slug}"
        print(f"EDHRec meta: {url}")
        try:
            resp = session.get(url, timeout=25)
            resp.raise_for_status()
            page_data = parse_edhrec_page(resp.text)
            if not page_data:
                print(f"  skip (no page data): {slug}")
                continue
            text = format_edhrec_document(slug, page_data)
            if not text:
                print(f"  skip (not a commander): {slug}")
                continue
            save_edhrec_file(slug, text)
            saved += 1
            print(f"  saved edhrec_{slug}.txt ({len(text)} chars)")
        except requests.RequestException as exc:
            print(f"  error: {exc}")
        _sleep(EDHREC_DELAY)

    print(f"EDHRec knowledge files saved this run: {saved}")
    return saved


def fetch_and_save_decks(
    urls: list[str] | None = None,
    max_new: int = MAX_NEW_DECKS_PER_RUN,
) -> int:
    """Parse deck URLs via mtg_parser and save RAG-rich text files."""
    DECK_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": random.choice(USER_AGENTS)})

    if urls is None:
        print("Discovering Commander deck URLs…")
        urls = collect_deck_urls(session)

    already_urls = _existing_deck_urls()
    saved = 0
    skipped = 0

    for url in urls:
        if saved >= max_new:
            break
        if url in already_urls:
            skipped += 1
            continue
        if not mtg_parser.can_handle(url):
            print(f"skip (unsupported host): {url}")
            continue

        try:
            print(f"Fetching deck: {url}")
            session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
            cards = list(mtg_parser.parse_deck(url, session) or [])
            if len(cards) < 10:
                print(f"  skip (too few cards: {len(cards)})")
                continue

            record = cards_to_record(cards, url)
            record["deck_id"] = url_to_id(url)
            text = format_deck_document(record)
            path = save_deck_file(record, text)
            already_urls.add(url)
            saved += 1
            cmd = record.get("commander") or "unknown"
            print(f"  saved {path.name} — {cmd}, {record['card_count']} cards")
        except Exception as exc:
            if "429" in str(exc):
                print("Rate limited — sleeping 60s")
                time.sleep(60)
            else:
                print(f"  error: {exc}")

        _sleep(DECK_FETCH_DELAY)

    print(f"Decks saved: {saved}, skipped (already had): {skipped}")
    return saved


def load_deck_documents() -> list[Document]:
    files = collect_document_files()
    if not files:
        return []
    return [file_to_document(path) for path in files]


def update_index_with_decks(index, documents: list[Document] | None = None) -> int:
    """Insert only documents not yet recorded in the index manifest."""
    if documents is None:
        documents = load_deck_documents()
    if not documents:
        print("No deck documents to index.")
        return 0

    manifest = load_manifest()
    inserted = 0
    for doc in documents:
        doc_id = doc.id_ or doc.metadata.get("file_name", "")
        if doc_id in manifest:
            continue
        index.insert(doc)
        manifest.add(doc_id)
        inserted += 1

    save_manifest(manifest)
    print(f"Indexed {inserted} new documents ({len(manifest)} total in manifest).")
    return inserted


def run_scrapper(index, *, refresh_edhrec: bool = True, refresh_decks: bool = True) -> None:
    """
    Full enrichment pass:
    1. EDHRec commander meta (synergies, themes, average staples)
    2. Live decklists from Goldfish / TappedOut
    3. Incremental index insert
    """
    session = requests.Session()
    session.headers.update({"User-Agent": random.choice(USER_AGENTS)})

    print("\n--- Scraper: EDHRec Commander intelligence ---")
    if refresh_edhrec:
        scrape_edhrec_knowledge(session)

    print("\n--- Scraper: Competitive decklists ---")
    if refresh_decks:
        fetch_and_save_decks()

    print("\n--- Scraper: Index enrichment ---")
    docs = load_deck_documents()
    if docs:
        update_index_with_decks(index, docs)
    else:
        print("No deck/knowledge files found under scraped_decks/.")


def run_scrape_only() -> None:
    """Scrape and save files without touching the vector index."""
    session = requests.Session()
    session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
    scrape_edhrec_knowledge(session)
    fetch_and_save_decks()


def purge_deck_vectors_from_chroma() -> int:
    """Remove all deck/EDHRec chunks from Chroma (keeps card index intact)."""
    import chromadb

    try:
        from ingestion.paths import MTG_DB
    except ImportError:
        from paths import MTG_DB

    client = chromadb.PersistentClient(path=str(MTG_DB))
    collection = client.get_collection("mtg_cards")
    before = collection.count()
    for where in (
        {"is_decklist": True},
        {"is_edhrec_meta": True},
        {"doc_type": "decklist"},
        {"doc_type": "edhrec_meta"},
    ):
        try:
            collection.delete(where=where)
        except Exception:
            pass
    removed = before - collection.count()
    print(f"Removed {removed} deck/meta vectors from Chroma ({collection.count()} remain).")
    return removed


def reindex_all_decks(index=None) -> int:
    """
    Full re-index of scraped_decks + knowledge files:
    purge old vectors, clear manifest, embed all enriched documents.
    """
    try:
        from ingestion.paths import MANIFEST_PATH
        from ingestion import mtg_json
        from ingestion.paths import MTG_DB
    except ImportError:
        from paths import MANIFEST_PATH, MTG_DB
        import mtg_json

    purge_deck_vectors_from_chroma()

    if MANIFEST_PATH.exists():
        MANIFEST_PATH.unlink()
        print("Cleared index manifest.")

    if index is None:
        db, collection = mtg_json.create_db(path=str(MTG_DB), collection_name="mtg_cards")
        vector_store, storage_context = mtg_json.setup_db(collection=collection)
        index = mtg_json.index_cards(collection, vector_store, storage_context)
        if index is None:
            raise RuntimeError("Could not load vector index")

    docs = load_deck_documents()
    print(f"Re-indexing {len(docs)} enriched documents…")
    return update_index_with_decks(index, docs)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "reindex":
        reindex_all_decks()
    else:
        run_scrape_only()
