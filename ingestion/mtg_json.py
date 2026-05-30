import json
import chromadb
from llama_index.core import Document, VectorStoreIndex, StorageContext
from llama_index.vector_stores.chroma import ChromaVectorStore

try:
    from ingestion.ollama_config import configure_ollama_settings
    from ingestion.paths import CARDS_JSON, MTG_DB
except ImportError:
    from ollama_config import configure_ollama_settings
    from paths import CARDS_JSON, MTG_DB


def create_db(path: str, collection_name: str):
    configure_ollama_settings()
    db = chromadb.PersistentClient(path=path)
    collection = db.get_or_create_collection(collection_name)
    return db, collection


def setup_db(collection):
    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    return vector_store, storage_context


def index_cards(collection, vector_store, storage_context):
    if collection.count() == 0:
        print("Indexing Commander-legal cards only...")
        with open(CARDS_JSON, "r") as f:
            mtg_data = json.load(f)

        documents = []
        for card_name, versions in mtg_data["data"].items():
            card = versions[0]

            # Check for Commander legality before indexing
            legalities = card.get("legalities", {})
            if legalities.get("commander") == "Legal":
                color_identity = card.get("colorIdentity") or []
                colors = card.get("colors") or []
                ci_str = ", ".join(color_identity) if color_identity else "Colorless"
                text_content = (
                    f"Card: {card_name}\n"
                    f"Color identity: {ci_str}\n"
                    f"Colors: {', '.join(colors) if colors else 'none'}\n"
                    f"Text: {card.get('text', '')}"
                )

                metadata = {
                    "name": card_name,
                    "mana_value": card.get("manaValue", 0),
                    "is_commander_legal": True,
                    "color_identity": ",".join(sorted(color_identity)),
                }
                documents.append(Document(text=text_content, metadata=metadata))

        if not documents:
            print("No legal cards found. Check your JSON path or 'commander' key name.")
            return None

        index = VectorStoreIndex.from_documents(
            documents, storage_context=storage_context, show_progress=True
        )
    else:
        print("Loading local index...")
        index = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_context, show_progress=True)
    return index


def main():
    db, collection = create_db(path=str(MTG_DB), collection_name="mtg_cards")
    vector_store, storage_context = setup_db(collection=collection)
    index = index_cards(collection, vector_store, storage_context)
    query_engine = index.as_query_engine()
    response = query_engine.query("What is the most efficient power to mana cost creature?")
    print(response)

if __name__ == "__main__":
    main()