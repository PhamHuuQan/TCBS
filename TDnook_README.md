# TDnook — Minimalist Paper Document Reader & Assistant

## 1. Overview

**TDnook** is a minimalist paper document reader and intelligent question-answering system built with **Retrieval-Augmented Generation (RAG)**.

The system allows users to upload documents (PDF, DOCX, XLSX, images, and text), process and index their content in a **vector database**, retrieve the most relevant context based on queries, and generate grounded answers using an **LLM** with page-level citations.


```text
PDF Document
     │
     ▼
Document Parser
     │
     ▼
Text Chunking
     │
     ▼
Embedding Model
     │
     ▼
Vector Database
     │
     │
     │     User Question
     │           │
     │           ▼
     │      Query Embedding
     │           │
     ▼           ▼
     └──── Similarity Search
                 │
                 ▼
            Top-K Chunks
                 │
                 ▼
                LLM
                 │
                 ▼
        Answer + Sources
```

## 2. Features

- Upload PDF documents
- Extract text from PDF files
- Split documents into smaller chunks
- Generate vector embeddings
- Store embeddings in a vector database
- Perform semantic similarity search
- Retrieve Top-K relevant chunks
- Generate answers using an LLM
- Provide document/page sources for answers
- REST API using FastAPI
- Simple web interface using Streamlit

## 3. Tech Stack

### Backend

- Python
- FastAPI
- Pydantic

### RAG / AI

- Google Gemini API
- Embedding Model
- LangChain *(optional)*

### Vector Database

- ChromaDB
- Qdrant *(planned)*

### Document Processing

- PyMuPDF

### Frontend

- Streamlit

### Development

- Git
- Docker *(planned)*
- pytest

## 4. Architecture

```text
                         ┌─────────────────────┐
                         │     User / Client   │
                         └──────────┬──────────┘
                                    │
                          Upload PDF / Question
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │      FastAPI        │
                         └──────────┬──────────┘
                                    │
                  ┌─────────────────┴─────────────────┐
                  │                                   │
                  ▼                                   ▼
          Document Ingestion                    Query Pipeline
                  │                                   │
                  ▼                                   ▼
             PDF Parser                       Query Embedding
                  │                                   │
                  ▼                                   │
              Chunking                                │
                  │                                   │
                  ▼                                   │
             Embeddings                               │
                  │                                   │
                  ▼                                   ▼
          ┌──────────────────────────────────────────────┐
          │                ChromaDB                       │
          │             Vector Database                  │
          └──────────────────────┬───────────────────────┘
                                 │
                           Similarity Search
                                 │
                                 ▼
                           Top-K Chunks
                                 │
                                 ▼
                           Context Builder
                                 │
                                 ▼
                           Gemini / LLM
                                 │
                                 ▼
                         Answer + Sources
```

## 5. RAG Pipeline

### 5.1 Document Ingestion

When a PDF is uploaded, the system extracts its text.

```text
PDF
 │
 ▼
PyMuPDF
 │
 ▼
Raw Text
```

### 5.2 Text Chunking

Large documents are split into smaller chunks.

```text
Document
    │
    ▼
Large Text
    │
    ▼
Chunking
    │
    ├── Chunk 1
    ├── Chunk 2
    ├── Chunk 3
    └── Chunk N
```

### 5.3 Embedding

Each text chunk is converted into a numerical vector.

```text
Text
  │
  ▼
Embedding Model
  │
  ▼
[0.021, -0.182, 0.731, ..., 0.092]
```

### 5.4 Vector Database

The generated embeddings are stored in ChromaDB together with text and metadata.

```json
{
  "text": "Employees are entitled to 12 days of annual leave.",
  "metadata": {
    "filename": "employee_handbook.pdf",
    "page": 2,
    "chunk_id": 15
  }
}
```

## 6. Query Pipeline

Suppose the user asks:

> How many annual leave days do employees have?

The question is converted into an embedding and searched against the vector database.

```text
User Question
      │
      ▼
Embedding Model
      │
      ▼
Query Vector
      │
      ▼
Vector Similarity Search
      │
      ▼
Top-K Relevant Chunks
```

Example:

```text
Top 3 Results

1. employee_handbook.pdf — Page 2
   Similarity: 0.91

2. employee_handbook.pdf — Page 3
   Similarity: 0.87

3. employee_handbook.pdf — Page 8
   Similarity: 0.76
```

## 7. Context Augmentation

Retrieved chunks are inserted into the LLM prompt.

```text
System:
Answer the question using only the provided context.

Context:
Employees are entitled to 12 days of annual leave.

Question:
How many annual leave days do employees have?
```

## 8. Generation

Example output:

```text
Employees are entitled to 12 days of annual leave.

Sources:
- employee_handbook.pdf — Page 2
```

The core RAG flow is:

```text
Retrieve → Augment → Generate
```

## 9. Vector Database vs RAG

### Vector Database

A vector database stores and searches embeddings.

```text
Text
 ↓
Embedding
 ↓
Vector Database
 ↓
Similarity Search
```

### RAG

RAG is the complete application architecture.

```text
Question
 ↓
Embedding
 ↓
Retrieval
 ↓
Relevant Context
 ↓
LLM
 ↓
Answer
```

**Vector Database is a component of a RAG system, while RAG is the overall retrieval + generation architecture.**

## 10. Project Structure

```text
docu-rag/
│
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   └── routes.py
│   │
│   ├── rag/
│   │   ├── loader.py
│   │   ├── chunker.py
│   │   ├── embeddings.py
│   │   ├── vector_store.py
│   │   ├── retriever.py
│   │   └── pipeline.py
│   │
│   ├── llm/
│   │   └── generator.py
│   │
│   └── models/
│       └── schemas.py
│
├── data/
│   └── documents/
│
├── tests/
│
├── .env
├── .gitignore
├── requirements.txt
├── Dockerfile
└── README.md
```

## 11. Installation

```bash
git clone https://github.com/your-username/docu-rag.git
cd docu-rag

python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

Linux / macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## 12. Environment Variables

Create `.env`:

```env
GEMINI_API_KEY=your_api_key
VECTOR_DB_PATH=./data/vector_db
TOP_K=5
```

Do not commit `.env` to Git.

```gitignore
.env
.venv/
__pycache__/
data/vector_db/
```

## 13. Running the Application

Start FastAPI:

```bash
uvicorn app.main:app --reload
```

Run Streamlit:

```bash
streamlit run app/streamlit_app.py
```

## 14. Example API

### Upload Document

```http
POST /documents/upload
```

Response:

```json
{
  "status": "success",
  "filename": "employee_handbook.pdf",
  "chunks": 42
}
```

### Ask Question

```http
POST /query
```

Request:

```json
{
  "question": "How many annual leave days do employees have?"
}
```

Response:

```json
{
  "answer": "Employees are entitled to 12 days of annual leave.",
  "sources": [
    {
      "filename": "employee_handbook.pdf",
      "page": 2
    }
  ]
}
```

## 15. Future Improvements

### Phase 1 — Basic RAG

```text
PDF
 ↓
Chunking
 ↓
Embedding
 ↓
ChromaDB
 ↓
Similarity Search
 ↓
Gemini
```

### Phase 2 — Advanced Retrieval

```text
                    ┌── Vector Search ──┐
User Query ─────────┤                   ├──→ Reranker
                    └── BM25 Search ────┘
                                             │
                                             ▼
                                            LLM
```

Planned features:

- Hybrid Search
- BM25
- Reranking
- Metadata filtering
- Query rewriting
- Conversation memory
- Source citation
- Response caching

## 16. Evaluation

A production RAG system should evaluate both retrieval and generation.

### Retrieval

- Precision@K
- Recall@K
- MRR

### Generation

- Faithfulness
- Answer Relevance
- Context Relevance

Future versions may integrate RAG evaluation frameworks such as RAGAS.

## 17. Production Considerations

```text
                    ┌──────────────┐
                    │   Frontend   │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   FastAPI    │
                    └──────┬───────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
       Document Worker             Query Service
              │                         │
              ▼                         ▼
        Embedding Model             Retriever
              │                         │
              └────────────┬────────────┘
                           ▼
                     Vector DB
                           │
                           ▼
                          LLM
```

Potential improvements:

- Async document processing
- Background workers
- Docker
- Authentication
- Rate limiting
- Logging
- Monitoring
- Caching
- Vector database persistence
- Horizontal scaling

## 18. Learning Objectives

After completing this project, you should understand:

1. How embeddings work
2. Why vector databases are useful
3. How semantic search works
4. How document chunking affects retrieval
5. How RAG works internally
6. How an LLM uses retrieved context
7. How to reduce hallucination using external context
8. How to expose an AI pipeline through a REST API
9. How to evaluate retrieval quality
10. How to evolve a prototype into a production-oriented RAG system

## 19. Roadmap

- [x] Project design
- [ ] PDF parser
- [ ] Text chunking
- [ ] Embedding generation
- [ ] ChromaDB integration
- [ ] Similarity search
- [ ] Gemini integration
- [ ] Basic RAG pipeline
- [ ] FastAPI API
- [ ] Streamlit UI
- [ ] Source citation
- [ ] Metadata filtering
- [ ] Hybrid search
- [ ] Reranking
- [ ] RAG evaluation
- [ ] Docker
- [ ] Production deployment

## 20. Project Overview
 
**TDnook** is a minimalist paper document reader and Retrieval-Augmented Generation (RAG) assistant for document-based question answering. The system processes multi-format documents (PDF, Word, Excel, images, text), generates vector embeddings, stores them in ChromaDB, performs semantic retrieval, and leverages local or cloud LLMs to generate grounded responses with exact source citations and strict business rules.
 
**Key technologies:** Python, FastAPI, ChromaDB, EasyOCR, Sentence-Transformers, Local LLMs (MLX, llama.cpp), Gemini API, Minimalist Paper Web Canvas.

