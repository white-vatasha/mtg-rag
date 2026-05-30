from threading import Lock

from llama_index.core import PromptTemplate
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle

try:
    from ingestion import mtg_json
    from ingestion.paths import MTG_DB
except ImportError:
    import mtg_json
    from paths import MTG_DB

_lock = Lock()
_query_engine = None
_index = None

COMMANDER_QA_TEMPLATE = PromptTemplate(
    "You are an expert Magic: The Gathering Commander (EDH) deck advisor. "
    "Answer using only the context below, which includes card rules, EDHRec meta statistics "
    "(synergy %, theme counts, top staples), and real competitive decklists. "
    "Prefer EDHRec synergy/theme data for staple and commander questions; use decklists for "
    "specific card choices and archetype examples. Be specific about commanders and card names.\n"
    "CRITICAL — Color identity: If the question specifies colors (e.g. blue+red), only recommend "
    "commanders and cards in that exact identity. Blue+red is Izzet (U and R), NOT Azorius (white+blue). "
    "White+blue is Azorius only. Never swap guild names or color pairs.\n"
    "{color_constraints}"
    "---------------------\n"
    "{context_str}\n"
    "---------------------\n"
    "Question: {query_str}\n"
    "Answer: "
)


class ColorAwareRetriever(VectorIndexRetriever):
    """Re-rank retrieval results to prefer matching color identity."""

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        from api.color_identity import filter_nodes_by_color, parse_colors_from_augmented_query

        nodes = super()._retrieve(query_bundle)
        required = parse_colors_from_augmented_query(query_bundle.query_str)
        if required:
            nodes = filter_nodes_by_color(nodes, required, keep=self._similarity_top_k)
        return nodes


def _build_query_engine(index) -> RetrieverQueryEngine:
    # Fewer chunks = smaller prompts; important on CPU-only Minikube (avoids LLM timeouts).
    retriever = ColorAwareRetriever(index=index, similarity_top_k=8)
    synthesizer = get_response_synthesizer(text_qa_template=COMMANDER_QA_TEMPLATE)
    return RetrieverQueryEngine(retriever=retriever, response_synthesizer=synthesizer)


def initialize_rag() -> None:
    """Run full startup bootstrap (cards + on-disk decks). Called from API lifespan."""
    global _index, _query_engine
    from ingestion.startup_index import bootstrap_rag_index

    with _lock:
        _index = bootstrap_rag_index()
        _query_engine = _build_query_engine(_index)


def get_query_engine():
    global _query_engine, _index
    if _query_engine is None:
        with _lock:
            if _query_engine is None:
                from ingestion.startup_index import bootstrap_rag_index

                _index = bootstrap_rag_index()
                _query_engine = _build_query_engine(_index)
    return _query_engine


def ask(question: str) -> dict:
    from api.observability import get_logger, trace_rag_query

    log = get_logger("mtg_rag.query")
    from api.color_identity import (
        answer_violates_colors,
        augment_query,
        format_prompt_constraints,
        parse_color_request,
    )
    from api.decklist_extract import extract_decklist

    color_req = parse_color_request(question)
    query_text = augment_query(question, color_req)
    color_constraints = format_prompt_constraints(color_req)

    engine = get_query_engine()
    template = COMMANDER_QA_TEMPLATE.partial_format(color_constraints=color_constraints)
    engine.update_prompts({"response_synthesizer:text_qa_template": template})

    with trace_rag_query(question):
        log.info(
            "Running RAG query",
            extra={
                "mtg_rag.query.length": len(question),
                "mtg_rag.color_identity": color_req.sorted_str if color_req else None,
            },
        )
        response = engine.query(query_text)
    answer = str(response)

    if color_req:
        note = answer_violates_colors(answer, color_req.colors)
        if note:
            answer = answer + note

    sources = []
    if hasattr(response, "source_nodes"):
        for node in response.source_nodes:
            meta = dict(node.metadata or {})
            text = node.text or ""
            sources.append(
                {
                    "text": text,
                    "snippet": text[:400] + ("…" if len(text) > 400 else ""),
                    "metadata": meta,
                }
            )

    decklist = extract_decklist(answer, sources)
    return {
        "answer": answer,
        "sources": sources,
        "has_decklist": decklist is not None,
        "decklist": decklist,
        "color_identity": color_req.sorted_str if color_req else None,
    }
