from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)


class SourceSnippet(BaseModel):
    snippet: str
    metadata: dict


class ExtractedDecklist(BaseModel):
    commander: str | None = None
    name: str | None = None
    cards: str
    card_count: int
    description: str | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceSnippet]
    has_decklist: bool = False
    decklist: ExtractedDecklist | None = None
    color_identity: str | None = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str

    class Config:
        from_attributes = True


class DeckCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    commander: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    cards: str = ""


class DeckUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    commander: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    cards: str | None = None


class DeckOut(BaseModel):
    id: int
    name: str
    commander: str | None
    description: str | None
    cards: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class HealthResponse(BaseModel):
    status: str
    rag_ready: bool
    indexing_phase: str = "idle"
    indexing_message: str = ""
    card_vectors: int = 0
    decks_indexed: int = 0
