"""
Playbook Engine — RAG over firm's standard clauses using ChromaDB.
Stores "gold standard" clause language; compares new contract clauses against them.
"""
import json
import os
import uuid
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
        ef = embedding_functions.DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

    def add_standard_clause(self, clause_type: str, text: str, metadata: dict = None):
        """Add a gold standard clause to the playbook."""
        self._init()
        doc_id = str(uuid.uuid4())
        meta = {"clause_type": clause_type, **(metadata or {})}
        # Flatten lists to comma-separated strings (ChromaDB only stores scalar metadata)
        meta = _flatten_metadata(meta)
        self._collection.add(
            documents=[text],
            metadatas=[meta],
            ids=[doc_id],
        )
        return doc_id

    def load_from_json(self, json_path: str):
        """
        Bulk-load standard clauses from a JSON file.
        Supports the extended schema with id, summary, variables, and tags.
        """
        self._init()
        with open(json_path) as f:
            clauses = json.load(f)

        for item in clauses:
            clause_type = item.get("type", "Unknown")
            text = item.get("text", "")
            summary = item.get("summary", "")
            variables = item.get("variables", [])

            # Merge user-supplied metadata with top-level schema fields
            meta = {
                **(item.get("metadata", {})),
                "clause_id": item.get("id", str(uuid.uuid4())),
                "summary": summary,
                "variables": variables,  # will be flattened below
            }

            # Embed summary + text together for richer retrieval signal
            document = f"{summary}\n\n{text}" if summary else text

            doc_id = meta["clause_id"]
            flat_meta = _flatten_metadata({"clause_type": clause_type, **meta})

            self._collection.add(
                documents=[document],
                metadatas=[flat_meta],
                ids=[doc_id],
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
            similarity = 1 - dist
            # Restore variables list from comma-separated string
            variables_raw = meta.get("variables", "")
            variables = [v.strip() for v in variables_raw.split(",")] if variables_raw else []

            output.append({
                "clause_type": meta.get("clause_type", "unknown"),
                "clause_id": meta.get("clause_id", ""),
                "summary": meta.get("summary", ""),
                "standard_text": doc,
                "variables": variables,
                "similarity": round(similarity, 3),
                "metadata": meta,
            })
        return output

    def reseed(self, json_path: str):
        """Wipe and reload the collection from a JSON file."""
        self._init()
        self._client.delete_collection(COLLECTION_NAME)
        ef = embedding_functions.DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        return self.load_from_json(json_path)

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


def _flatten_metadata(meta: dict) -> dict:
    """
    ChromaDB only accepts str/int/float/bool metadata values.
    Convert lists to comma-separated strings and drop None values.
    """
    flat = {}
    for k, v in meta.items():
        if v is None:
            continue
        elif isinstance(v, list):
            flat[k] = ", ".join(str(i) for i in v)
        elif isinstance(v, (str, int, float, bool)):
            flat[k] = v
        else:
            flat[k] = str(v)
    return flat


playbook = PlaybookEngine()
