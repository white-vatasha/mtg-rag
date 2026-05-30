from pathlib import Path

INGESTION_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = INGESTION_DIR.parent

MTG_DB = INGESTION_DIR / "mtg_db"
CARDS_JSON = PROJECT_ROOT / "context" / "AtomicCards.json"
DECK_DIR = INGESTION_DIR / "scraped_decks"
KNOWLEDGE_DIR = DECK_DIR / "knowledge"
MANIFEST_PATH = DECK_DIR / ".index_manifest.json"
DATA_DIR = PROJECT_ROOT / "data"
