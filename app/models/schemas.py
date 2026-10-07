from pydantic import BaseModel
from typing import Any

class QueryRequest(BaseModel):
    question: str
    filename: str | None = None
    user_document_text: str | None = None
    user_document_name: str | None = None

class Source(BaseModel):
    filename: str
    page: int | str

class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]

class UploadResponse(BaseModel):
    status: str
    filename: str
    chunks: int

class UserFileParseResponse(BaseModel):
    status: str
    filename: str
    text: str
    pages: int
    char_count: int
