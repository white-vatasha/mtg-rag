from api.observability import configure_observability, get_logger, trace_operation  # noqa: E402

configure_observability()
logger = get_logger(__name__)

import asyncio
from contextlib import asynccontextmanager
from functools import partial

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from api.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    get_user_by_email,
    hash_password,
)
from api.config import get_settings
from api.database import get_db, init_db
from api.models import Deck, User
from api.schemas import (
    DeckCreate,
    DeckOut,
    DeckUpdate,
    ExtractedDecklist,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SourceSnippet,
    TokenResponse,
    UserCreate,
    UserOut,
)
from ingestion.rag_service import ask, initialize_rag
from ingestion.startup_index import get_bootstrap_status

settings = get_settings()
_rag_ready = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application bootstrap (RAG index)")
    init_db()
    global _rag_ready
    try:
        with trace_operation("mtg_rag.bootstrap", resource="initialize_rag"):
            await asyncio.to_thread(initialize_rag)
        _rag_ready = get_bootstrap_status().rag_ready
    except Exception as exc:
        status = get_bootstrap_status()
        status.phase = "error"
        status.error = str(exc)
        status.message = status.message or str(exc)
        _rag_ready = False
        logger.exception("Bootstrap failed: %s", exc)
    else:
        boot = get_bootstrap_status()
        logger.info(
            "Bootstrap complete",
            extra={
                "mtg_rag.bootstrap.phase": boot.phase,
                "mtg_rag.card_count": boot.card_count,
                "mtg_rag.decks_indexed": boot.decks_indexed,
            },
        )
    yield
    logger.info("Application shutdown")


app = FastAPI(
    title="MTG Commander RAG",
    description="Commander deck intelligence powered by local RAG",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
def health():
    boot = get_bootstrap_status()
    return HealthResponse(
        status="ok",
        rag_ready=_rag_ready,
        indexing_phase=boot.phase,
        indexing_message=boot.message,
        card_vectors=boot.card_count,
        decks_indexed=boot.decks_indexed,
    )


@app.get("/api/ready")
def ready():
    boot = get_bootstrap_status()
    if not _rag_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=boot.message or boot.error or "RAG index not ready",
        )
    return {"status": "ready", "card_vectors": boot.card_count}


@app.post("/api/query", response_model=QueryResponse)
async def query_commander(body: QueryRequest):
    if not _rag_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG index is not ready. Ensure Ollama is running and the card database is indexed.",
        )
    try:
        result = await asyncio.to_thread(partial(ask, body.question))
    except Exception as exc:
        logger.exception("Query failed")
        msg = str(exc)
        if "requires more system memory" in msg:
            detail = (
                "Ollama ran out of memory loading the chat model. "
                "On Minikube use llama3.2:3b and OLLAMA_LLM_NUM_CTX=4096 (see README)."
            )
        elif "timed out" in msg.lower() or "timeout" in msg.lower():
            detail = (
                "The LLM request timed out (common on CPU-only Minikube). "
                "Retry with a shorter question or increase OLLAMA_REQUEST_TIMEOUT."
            )
        else:
            detail = f"Query failed: {exc}"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        ) from exc
    decklist = None
    if result.get("decklist"):
        decklist = ExtractedDecklist(**result["decklist"])

    return QueryResponse(
        answer=result["answer"],
        sources=[
            SourceSnippet(snippet=s["snippet"], metadata=s.get("metadata") or {})
            for s in result["sources"]
        ],
        has_decklist=bool(result.get("has_decklist")),
        decklist=decklist,
        color_identity=result.get("color_identity"),
    )


@app.post("/api/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, db: Session = Depends(get_db)):
    email = body.email.lower()
    if get_user_by_email(db, email):
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=email, hashed_password=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/auth/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form.username, form.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    token = create_access_token(user.email)
    return TokenResponse(access_token=token)


@app.get("/api/auth/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@app.get("/api/decks", response_model=list[DeckOut])
def list_decks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Deck)
        .filter(Deck.user_id == current_user.id)
        .order_by(Deck.updated_at.desc())
        .all()
    )


@app.post("/api/decks", response_model=DeckOut, status_code=status.HTTP_201_CREATED)
def create_deck(
    body: DeckCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deck = Deck(
        user_id=current_user.id,
        name=body.name,
        commander=body.commander,
        description=body.description,
        cards=body.cards,
    )
    db.add(deck)
    db.commit()
    db.refresh(deck)
    return deck


@app.get("/api/decks/{deck_id}", response_model=DeckOut)
def get_deck(
    deck_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deck = _get_user_deck(db, deck_id, current_user.id)
    return deck


@app.put("/api/decks/{deck_id}", response_model=DeckOut)
def update_deck(
    deck_id: int,
    body: DeckUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deck = _get_user_deck(db, deck_id, current_user.id)
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(deck, key, value)
    db.commit()
    db.refresh(deck)
    return deck


@app.delete("/api/decks/{deck_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deck(
    deck_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deck = _get_user_deck(db, deck_id, current_user.id)
    db.delete(deck)
    db.commit()


def _get_user_deck(db: Session, deck_id: int, user_id: int) -> Deck:
    deck = db.query(Deck).filter(Deck.id == deck_id, Deck.user_id == user_id).first()
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    return deck
