# Papertrail AI — GenAI Document Intelligence Platform

> A production-oriented document intelligence platform for uploading documents, performing grounded conversational Q&A, retrieving relevant document context using vector search, and generating citation-backed answers with an LLM.


flowchart TB

    User["User"]

    subgraph Frontend["Frontend"]
        UI["React + TypeScript UI"]
        Query["TanStack Query"]
        AuthClient["Supabase Auth Client"]
    end

    subgraph Backend["FastAPI Backend"]
        API["API / Route Layer"]
        Auth["Authentication & Authorization"]

        subgraph Services["Application Services"]
            DocumentService["Document Service"]
            IngestionService["Ingestion Service"]
            Extraction["Document Extraction"]
            Chunker["Recursive Chunker"]
            RAG["RAG Service"]
            Retrieval["Retrieval Service"]
            Conversation["Conversation Service"]
            UserService["User Service"]
        end

        subgraph Repositories["Repository Layer"]
            DocumentRepo["Document Repository"]
            UserRepo["User Repository"]
            ConversationRepo["Conversation Repository"]
        end

        Provider["LLM / Embedding Provider"]
    end

    subgraph External["External Services"]
        Supabase["Supabase Auth / Google OAuth"]
        Gemini["Google Gemini API"]
    end

    subgraph Storage["Persistence"]
        PostgreSQL["PostgreSQL 16"]
        PGVector["pgvector"]
        Files["Document Storage"]
    end

    User --> UI
    UI --> Query
    UI --> AuthClient

    AuthClient --> Supabase
    Query --> API

    API --> Auth
    Auth --> Supabase

    API --> DocumentService
    API --> Conversation
    API --> RAG

    DocumentService --> DocumentRepo
    DocumentRepo --> PostgreSQL

    DocumentService --> Files

    IngestionService --> Extraction
    Extraction --> Chunker
    IngestionService --> Provider
    IngestionService --> PostgreSQL
    PostgreSQL --> PGVector

    RAG --> Retrieval
    Retrieval --> Provider
    Retrieval --> PGVector

    RAG --> Provider
    Provider --> Gemini

    Conversation --> ConversationRepo
    ConversationRepo --> PostgreSQL

    UserService --> UserRepo
    UserRepo --> PostgreSQL


    
---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [System Architecture](#system-architecture)
- [High-Level Architecture Diagram](#high-level-architecture-diagram)
- [Deployment Architecture](#deployment-architecture)
- [Component Architecture](#component-architecture)
- [Database Design](#database-design)
- [Database ER Diagram](#database-er-diagram)
- [Document Ingestion Pipeline](#document-ingestion-pipeline)
- [RAG Pipeline](#rag-pipeline)
- [Sequence Diagrams](#sequence-diagrams)
  - [Document Upload & Ingestion](#document-upload--ingestion)
  - [Question Answering](#question-answering)
  - [Authentication](#authentication)
  - [Conversation Deletion](#conversation-deletion)
- [API Documentation](#api-documentation)
- [Non-Functional Requirements](#non-functional-requirements)
  - [Scalability](#scalability)
  - [Security](#security)
  - [Observability & Monitoring](#observability--monitoring)
  - [Resilience & Fault Tolerance](#resilience--fault-tolerance)
  - [Maintainability & Auditability](#maintainability--auditability)
  - [Performance Optimization](#performance-optimization)
- [Error Handling](#error-handling)
- [Authentication & Authorization](#authentication--authorization)
- [Data Storage](#data-storage)
- [Configuration](#configuration)
- [Local Development](#local-development)
- [Testing](#testing)
- [Docker Deployment](#docker-deployment)
- [API Documentation](#api-documentation-1)
- [Architecture Trade-offs](#architecture-trade-offs)
- [Project Structure](#project-structure)
- [Evaluation & Submission](#evaluation--submission)
- [Future Improvements](#future-improvements)

---

# Overview

Papertrail AI is a document intelligence platform that allows authenticated users to:

1. Upload PDF, DOCX, and TXT documents.
2. Store and process documents asynchronously.
3. Extract text from uploaded documents.
4. Split documents into retrieval-friendly chunks.
5. Generate vector embeddings for chunks.
6. Store embeddings using PostgreSQL with `pgvector`.
7. Create conversations associated with one or more documents.
8. Ask natural-language questions about the selected documents.
9. Retrieve relevant document chunks using semantic vector search.
10. Improve retrieval using multi-query expansion and step-back prompting.
11. Fuse multiple retrieval rankings using Reciprocal Rank Fusion (RRF).
12. Generate grounded answers using Gemini.
13. Return citations pointing back to the source document and page/chunk.
14. Persist conversations and messages for conversational context.
15. Manage uploaded documents and conversations.

The system is designed as a **modular monolith** rather than a collection of microservices. This keeps the architecture simple enough for development and deployment while maintaining clear separation between API, service, repository, provider, and persistence layers.

---



# Key Features

## Document Management

- PDF, DOCX, and TXT support.
- File size validation.
- MIME type validation.
- File extension validation.
- SHA-256 document checksum.
- Per-user document ownership.
- Document processing states:
  - `PROCESSING`
  - `READY`
  - `FAILED`
- Document deletion with underlying file cleanup.
- Persistent document metadata.

## Document Intelligence

- PDF text extraction using PyMuPDF.
- DOCX extraction using `python-docx`.
- TXT extraction using native Python file handling.
- Recursive document chunking.
- Configurable chunk size and overlap.
- Batched embedding generation.
- PostgreSQL `pgvector` storage.
- HNSW vector index for similarity search.

## RAG

The RAG pipeline combines:

- Query expansion.
- Three alternative retrieval queries.
- One broader step-back query.
- Batched query embedding.
- PostgreSQL/pgvector similarity search.
- Reciprocal Rank Fusion.
- Top-k context selection.
- Conversation history.
- Grounded LLM generation.
- Citation generation.

## Conversational Q&A

- Persistent conversations.
- Persistent messages.
- Conversation-document associations.
- Multi-document conversations.
- Conversational history passed to the generation layer.
- Citation-backed answers.

## Authentication

- Supabase Auth.
- Google OAuth.
- JWT-based authentication.
- Backend JWT verification using Supabase JWKS.
- User ownership checks for application resources.

## Production-Oriented Design

- Dockerized application.
- PostgreSQL + pgvector.
- Alembic migrations.
- Structured logging.
- Provider abstraction.
- Repository pattern.
- Service layer.
- Error handling.
- Automated tests.
- API validation.
- Health checks.

---

# Technology Stack

| Layer | Technology |
|---|---|
| Frontend | React + TypeScript |
| Frontend Build | Vite |
| Frontend Data Fetching | TanStack Query |
| Styling | Tailwind CSS |
| Backend | FastAPI |
| Language | Python 3.11+ |
| ORM | SQLAlchemy 2 |
| Database | PostgreSQL 16 |
| Vector Search | pgvector |
| Vector Index | HNSW |
| Migrations | Alembic |
| Database Driver | psycopg |
| Authentication | Supabase Auth |
| OAuth | Google OAuth |
| LLM | Gemini |
| Embeddings | Gemini Embedding API |
| PDF Extraction | PyMuPDF |
| DOCX Extraction | python-docx |
| Containerization | Docker + Docker Compose |
| Testing | pytest |
| API Documentation | OpenAPI / Swagger |
| Storage | Local filesystem abstraction |

---

# System Architecture

The application follows a **modular monolith architecture**.

The major layers are:

```text
Frontend
   |
   v
FastAPI API Layer
   |
   v
Application Services
   |
   +------------------+
   |                  |
   v                  v
Repositories      AI Services
   |                  |
   v                  +--------> Gemini
PostgreSQL
   |
   +--> pgvector