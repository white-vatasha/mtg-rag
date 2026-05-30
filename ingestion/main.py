try:
    from ingestion.paths import MTG_DB
    from ingestion import mtg_json, scrapper
except ImportError:
    from paths import MTG_DB
    import mtg_json
    import scrapper


def main():
    print("--- Phase 1: Knowledge Base Initialization ---")
    db, collection = mtg_json.create_db(path=str(MTG_DB), collection_name="mtg_cards")
    vector_store, storage_context = mtg_json.setup_db(collection=collection)
    index = mtg_json.index_cards(collection, vector_store, storage_context)

    print("\n--- Phase 2: Tournament & Community Meta Sync ---")
    # Adding a small buffer if you plan to scrape many decks
    scrapper.run_scrapper(index)

    print("\n--- Phase 3: Competitive Query Engine ---")
    query_engine = index.as_query_engine()

    # Query across card rules (JSON) and real deck performance (Scraped)
    # Now that the LLM has card rules AND real decklists, this query works much better
    query = " What are the top 10 most competitive EDH commanders?"
    response = query_engine.query(query)

    print(f"QUERY: {query}")
    print(f"\nRESPONSE:\n{response}")

if __name__ == "__main__":
    main()