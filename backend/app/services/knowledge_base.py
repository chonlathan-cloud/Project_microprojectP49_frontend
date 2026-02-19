import json
import logging
import re
from pathlib import Path
from threading import Lock
from typing import Any

try:
    from langchain_community.vectorstores import Chroma
    from langchain_core.documents import Document
    from langchain_google_vertexai import VertexAIEmbeddings
    _KB_LIBS_AVAILABLE = True
except Exception:  # pragma: no cover - dependency availability check
    Chroma = Any  # type: ignore
    Document = Any  # type: ignore
    VertexAIEmbeddings = Any  # type: ignore
    _KB_LIBS_AVAILABLE = False

from app.core.config import settings

logger = logging.getLogger(__name__)

_init_lock = Lock()
_vector_store: Chroma | None = None
_last_init_error: str | None = None


def _resolve_playbook_path() -> Path:
    configured = Path(settings.KNOWLEDGE_BASE_PLAYBOOK_PATH)
    if configured.is_absolute():
        return configured

    app_dir = Path(__file__).resolve().parents[1]
    return app_dir / configured


def _to_doc_id(raw_value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", raw_value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "item"


def _load_playbook_documents() -> tuple[list[Document], list[str]]:
    playbook_path = _resolve_playbook_path()
    with playbook_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, list):
        raise ValueError("business_playbook.json must be a list of objects.")

    documents: list[Document] = []
    ids: list[str] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            continue

        category = str(item.get("category", "General")).strip() or "General"
        topic = str(item.get("topic", f"Topic-{index + 1}")).strip() or f"Topic-{index + 1}"
        content = str(item.get("content", "")).strip()
        if not content:
            continue

        metadata = {
            "category": category,
            "topic": topic,
            "source": playbook_path.name,
        }
        documents.append(Document(page_content=content, metadata=metadata))
        ids.append(f"{_to_doc_id(category)}::{_to_doc_id(topic)}::{index}")

    if not documents:
        raise ValueError("No valid playbook entries were found.")

    return documents, ids


def initialize_knowledge_base(force_rebuild: bool = False) -> dict:
    """
    Initialize Chroma vector store from business playbook JSON.
    Safe to call multiple times.
    """
    global _vector_store, _last_init_error

    with _init_lock:
        if _vector_store is not None and not force_rebuild:
            return {"ready": True, "documents_loaded": None, "error": None}

        try:
            if not _KB_LIBS_AVAILABLE:
                raise RuntimeError(
                    "Knowledge base dependencies are missing. "
                    "Install langchain, langchain-community, "
                    "langchain-google-vertexai, chromadb."
                )
            documents, ids = _load_playbook_documents()
            persist_dir = Path(settings.KNOWLEDGE_BASE_PERSIST_DIR)
            persist_dir.mkdir(parents=True, exist_ok=True)

            embeddings = VertexAIEmbeddings(
                model_name=settings.VERTEX_AI_EMBEDDING_MODEL,
                project=settings.GCP_PROJECT_ID,
                location=settings.VERTEX_AI_LOCATION,
            )

            store = Chroma(
                collection_name=settings.KNOWLEDGE_BASE_COLLECTION,
                embedding_function=embeddings,
                persist_directory=str(persist_dir),
            )
            store.add_documents(documents=documents, ids=ids)

            if hasattr(store, "persist"):
                store.persist()

            _vector_store = store
            _last_init_error = None
            logger.info(
                "Knowledge base initialized. docs=%d collection=%s persist_dir=%s",
                len(documents),
                settings.KNOWLEDGE_BASE_COLLECTION,
                str(persist_dir),
            )
            return {"ready": True, "documents_loaded": len(documents), "error": None}
        except Exception as exc:
            _vector_store = None
            _last_init_error = str(exc)
            logger.warning("Knowledge base initialization failed: %s", str(exc))
            return {"ready": False, "documents_loaded": 0, "error": str(exc)}


def retrieve_relevant_advice(
    query: str,
    k: int | None = None,
    category_id: str | None = None,
) -> list[dict]:
    """
    Retrieve top-k relevant playbook snippets.
    """
    if not query.strip():
        return []
    if not _KB_LIBS_AVAILABLE:
        return []

    if _vector_store is None:
        initialize_knowledge_base()
    if _vector_store is None:
        return []

    requested_k = max(1, k or settings.KNOWLEDGE_BASE_TOP_K)
    search_k = max(requested_k * 3, requested_k)
    raw_results = _vector_store.similarity_search_with_relevance_scores(query, k=search_k)

    preferred_categories = {category_id, "General"} if category_id else None
    selected: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for doc, score in raw_results:
        metadata = doc.metadata or {}
        topic = str(metadata.get("topic", "")).strip() or "Untitled"
        category = str(metadata.get("category", "General")).strip() or "General"
        source = str(metadata.get("source", "business_playbook.json")).strip()
        key = (topic, category)

        if preferred_categories and category not in preferred_categories:
            continue
        if key in seen:
            continue

        seen.add(key)
        selected.append(
            {
                "topic": topic,
                "category": category,
                "content": doc.page_content,
                "source": source,
                "score": float(score),
            }
        )
        if len(selected) >= requested_k:
            break

    # If strict category filtering yields nothing, fall back to global similarity.
    if not selected and preferred_categories:
        for doc, score in raw_results:
            metadata = doc.metadata or {}
            topic = str(metadata.get("topic", "")).strip() or "Untitled"
            category = str(metadata.get("category", "General")).strip() or "General"
            source = str(metadata.get("source", "business_playbook.json")).strip()
            key = (topic, category)
            if key in seen:
                continue
            seen.add(key)
            selected.append(
                {
                    "topic": topic,
                    "category": category,
                    "content": doc.page_content,
                    "source": source,
                    "score": float(score),
                }
            )
            if len(selected) >= requested_k:
                break

    return selected


def get_knowledge_base_status() -> dict:
    return {
        "ready": _vector_store is not None,
        "last_error": _last_init_error,
        "collection": settings.KNOWLEDGE_BASE_COLLECTION,
    }
