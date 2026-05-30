"""
Bootstrap the RAG index on application startup (local or in-cluster).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

try:
    from api.config import get_settings
    from ingestion import mtg_json
    from ingestion.ollama_config import configure_ollama_settings
    from ingestion.paths import CARDS_JSON, DECK_DIR, KNOWLEDGE_DIR, MTG_DB
    from ingestion.scrapper import load_deck_documents, update_index_with_decks
except ImportError:
    from config import get_settings  # type: ignore
    import mtg_json  # type: ignore
    from ollama_config import configure_ollama_settings  # type: ignore
    from paths import CARDS_JSON, DECK_DIR, KNOWLEDGE_DIR, MTG_DB  # type: ignore
    from scrapper import load_deck_documents, update_index_with_decks  # type: ignore

logger = logging.getLogger(__name__)

COLLECTION_NAME = "mtg_cards"


@dataclass
class IndexBootstrapStatus:
    phase: str = "idle"
    message: str = ""
    rag_ready: bool = False
    card_count: int = 0
    decks_indexed: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "message": self.message,
            "rag_ready": self.rag_ready,
            "card_count": self.card_count,
            "decks_indexed": self.decks_indexed,
            "error": self.error,
        }


_status = IndexBootstrapStatus()


def get_bootstrap_status() -> IndexBootstrapStatus:
    return _status


def _set_status(phase: str, message: str, **kwargs: Any) -> None:
    global _status
    _status.phase = phase
    _status.message = message
    for key, value in kwargs.items():
        setattr(_status, key, value)
    line = f"[mtg-rag] {phase}: {message}"
    print(line, flush=True)
    logger.info("%s", line)
    try:
        from api.observability import emit_bootstrap_event

        emit_bootstrap_event(phase, message, **kwargs)
    except ImportError:
        pass


def wait_for_ollama(timeout_seconds: float = 300, interval: float = 5) -> None:
    settings = get_settings()
    base = settings.ollama_base_url.rstrip("/")
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            resp = requests.get(f"{base}/", timeout=5)
            if resp.status_code < 500:
                logger.info("Ollama is reachable at %s", base)
                return
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(interval)

    raise TimeoutError(
        f"Ollama not reachable at {base} after {timeout_seconds}s: {last_error}"
    )


def wait_for_ollama_models(timeout_seconds: float = 3600, interval: float = 15) -> None:
    """Block until required LLM and embedding models are pulled in Ollama."""
    settings = get_settings()
    base = settings.ollama_base_url.rstrip("/")
    required = {settings.ollama_llm_model, settings.ollama_embed_model}
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        try:
            resp = requests.get(f"{base}/api/tags", timeout=10)
            resp.raise_for_status()
            names = {m.get("name", "").split(":")[0] for m in resp.json().get("models", [])}
            names |= {m.get("name", "") for m in resp.json().get("models", [])}
            if all(
                any(r in n for n in names)
                for r in required
            ):
                logger.info("Ollama models available: %s", ", ".join(required))
                return
            _set_status(
                "waiting_models",
                f"Waiting for Ollama models {required} (pull job may still be running)…",
            )
        except requests.RequestException as exc:
            logger.debug("tags check failed: %s", exc)
        time.sleep(interval)

    raise TimeoutError(f"Ollama models {required} not available after {timeout_seconds}s")


def ensure_atomic_cards_file() -> bool:
    """Download AtomicCards.json when missing and AUTO_DOWNLOAD_CARDS is enabled."""
    if CARDS_JSON.exists() and CARDS_JSON.stat().st_size > 0:
        return True

    settings = get_settings()
    if not settings.auto_download_cards:
        _set_status(
            "error",
            f"Missing card database at {CARDS_JSON}. "
            "Set AUTO_DOWNLOAD_CARDS=true or mount AtomicCards.json.",
        )
        return False

    url = settings.atomic_cards_url
    _set_status("downloading_cards", f"Downloading card database from {url}…")
    CARDS_JSON.parent.mkdir(parents=True, exist_ok=True)

    try:
        with requests.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(CARDS_JSON, "wb") as out:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        out.write(chunk)
    except requests.RequestException as exc:
        _set_status("error", f"Failed to download AtomicCards.json: {exc}", error=str(exc))
        return False

    logger.info("Downloaded AtomicCards.json (%s bytes)", CARDS_JSON.stat().st_size)
    return True


def bootstrap_rag_index() -> Any:
    """
    Ensure Chroma is populated: cards from AtomicCards.json, then on-disk deck/knowledge files.
    Returns VectorStoreIndex or raises on failure.
    """
    global _status
    settings = get_settings()

    if not settings.auto_index_on_startup:
        _set_status("skipped", "AUTO_INDEX_ON_STARTUP is disabled")
        return _load_existing_index_only()

    DECK_DIR.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    MTG_DB.mkdir(parents=True, exist_ok=True)

    _set_status("waiting_ollama", "Waiting for Ollama…")
    configure_ollama_settings()
    wait_for_ollama(timeout_seconds=settings.ollama_wait_seconds)
    wait_for_ollama_models(timeout_seconds=settings.ollama_wait_seconds)

    if not ensure_atomic_cards_file():
        raise RuntimeError(_status.message or "AtomicCards.json not available")

    db, collection = mtg_json.create_db(path=str(MTG_DB), collection_name=COLLECTION_NAME)
    vector_store, storage_context = mtg_json.setup_db(collection=collection)
    existing = collection.count()

    if existing == 0:
        _set_status(
            "indexing_cards",
            "Indexing Commander-legal cards (first startup; may take 20–40 minutes)…",
            card_count=0,
        )
    else:
        _set_status(
            "loading_index",
            f"Loading existing index ({existing} vectors)…",
            card_count=existing,
        )

    index = mtg_json.index_cards(collection, vector_store, storage_context)
    if index is None:
        raise RuntimeError("Card indexing failed")

    card_count = collection.count()
    _status.card_count = card_count

    deck_docs = load_deck_documents()
    if deck_docs and settings.index_decks_on_startup:
        _set_status(
            "indexing_decks",
            f"Indexing {len(deck_docs)} deck/knowledge documents…",
            card_count=card_count,
        )
        inserted = update_index_with_decks(index, deck_docs)
        _status.decks_indexed = inserted
    else:
        _status.decks_indexed = 0

    _set_status(
        "ready",
        f"RAG ready ({card_count} vectors, {_status.decks_indexed} deck docs indexed this run).",
        rag_ready=True,
        card_count=card_count,
    )
    return index


def _load_existing_index_only() -> Any:
    configure_ollama_settings()
    db, collection = mtg_json.create_db(path=str(MTG_DB), collection_name=COLLECTION_NAME)
    vector_store, storage_context = mtg_json.setup_db(collection=collection)
    if collection.count() == 0:
        raise RuntimeError("No index present and AUTO_INDEX_ON_STARTUP is disabled")
    index = mtg_json.index_cards(collection, vector_store, storage_context)
    if index is None:
        raise RuntimeError("Failed to load index")
    _set_status("ready", "Loaded existing index", rag_ready=True, card_count=collection.count())
    return index
