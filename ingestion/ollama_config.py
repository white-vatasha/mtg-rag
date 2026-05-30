"""Configure LlamaIndex to use Ollama (local or in-cluster)."""

from llama_index.core import Settings
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama

_configured = False


def configure_ollama_settings() -> None:
    global _configured
    if _configured:
        return

    try:
        from api.config import get_settings
    except ImportError:
        from config import get_settings  # type: ignore

    settings = get_settings()
    base_url = settings.ollama_base_url.rstrip("/")

    Settings.llm = Ollama(
        model=settings.ollama_llm_model,
        base_url=base_url,
        request_timeout=settings.ollama_request_timeout,
        # Keep context small so chat fits in Minikube RAM (~6–8 GiB for Ollama).
        additional_kwargs={"num_ctx": settings.ollama_llm_num_ctx},
    )
    Settings.embed_model = OllamaEmbedding(
        model_name=settings.ollama_embed_model,
        base_url=base_url,
    )
    _configured = True
