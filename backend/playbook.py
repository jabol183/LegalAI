"""
Playbook Engine — RAG over firm's standard clauses using ChromaDB.
Stores "gold standard" clause language; compares new contract clauses against them.
"""
import json
import os
import uuid
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

CHROMA_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
COLLECTION_NAME = "legal_playbook"


class PlaybookEngine:
    def __init__(self):
        self._client: Optional[chromadb.PersistentClient] = None
        self._collection = None

    def _init(self):
        if self._client is not None:
            return
        self._client = chromadb.PersistentClient(path=CHROMA_DIR)
        # Use the built-in sentence transformer (no API key needed for embeddings)
        ef = embedding_functions.DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

    def add_standard_clause(self, clause_type: str, text: str, metadata: dict = None):
        """Add a 'gold standard' clause to the playbook."""
        self._init()
        doc_id = str(uuid.uuid4())
        meta = {"clause_type": clause_type, **(metadata or {})}
        self._collection.add(
            documents=[text],
            metadatas=[meta],
            ids=[doc_id],
        )
        return doc_id

    def load_from_json(self, json_path: str):
        """Bulk-load standard clauses from a JSON file."""
        self._init()
        with open(json_path) as f:
            clauses = json.load(f)

        for item in clauses:
            self.add_standard_clause(
                clause_type=item["type"],
                text=item["text"],
                metadata=item.get("metadata", {}),
            )
        return len(clauses)

    def find_similar_clauses(self, query_text: str, n_results: int = 3) -> list[dict]:
        """Return the most similar standard clauses for a given contract chunk."""
        self._init()
        if self._collection.count() == 0:
            return []

        results = self._collection.query(
            query_texts=[query_text],
            n_results=min(n_results, self._collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        output = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            similarity = 1 - dist  # cosine distance → similarity
            output.append({
                "clause_type": meta.get("clause_type", "unknown"),
                "standard_text": doc,
                "similarity": round(similarity, 3),
                "metadata": meta,
            })
        return output

    def collection_count(self) -> int:
        self._init()
        return self._collection.count()

    def list_clause_types(self) -> list[str]:
        self._init()
        if self._collection.count() == 0:
            return []
        results = self._collection.get(include=["metadatas"])
        types = {m.get("clause_type", "unknown") for m in results["metadatas"]}
        return sorted(types)


playbook = PlaybookEngine()
