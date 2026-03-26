"""
FastAPI backend for LegalAI — LegalFly-style contract review system.
"""

DISCLAIMER = (
    "NOT LEGAL ADVICE: LegalAI is an AI-powered document analysis tool only. "
    "It does not provide legal advice, does not constitute the practice of law, "
    "and does not create an attorney-client relationship. All output may contain "
    "errors and must not be relied upon as a substitute for advice from a licensed attorney. "
    "Always consult a qualified legal professional before making any legal decisions."
)
import os
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from backend.orchestrator import run_contract_review
from backend.playbook import playbook

# ── In-memory session store (replace with Redis/DB in production) ──────────────
sessions: dict[str, dict] = {}

app = FastAPI(
    title="LegalAI",
    description="Agentic contract review system with PII anonymization, RAG playbook, and HITL redlining",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ── Models ─────────────────────────────────────────────────────────────────────

class RedlineDecision(BaseModel):
    session_id: str
    redline_index: int
    decision: str  # "accepted" | "rejected"


class PlaybookUpload(BaseModel):
    clause_type: str
    text: str
    notes: str = ""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = FRONTEND_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text())


@app.post("/api/review")
async def review_contract(file: UploadFile = File(...)) -> dict[str, Any]:
    """
    Upload a PDF/DOCX/TXT contract for full agentic review.
    Returns classification, risk analysis, and redline suggestions.
    """
    allowed = {".pdf", ".docx", ".txt"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use: {allowed}")

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(400, "File too large. Maximum 10 MB.")

    result = run_contract_review(file_bytes=file_bytes, filename=file.filename)

    if result.get("error"):
        raise HTTPException(500, result["error"])

    # Create session for HITL decisions
    session_id = str(uuid.uuid4())
    sessions[session_id] = result

    return {
        "session_id": session_id,
        "filename": file.filename,
        "elapsed_seconds": result.get("elapsed_seconds"),
        "classification": result.get("classification", {}),
        "risk_summary": _build_risk_summary(result.get("risk_analyses", [])),
        "redlines": result.get("redlines", []),
        "pii_detected": len(result.get("pii_mapping", {})),
        "disclaimer": DISCLAIMER,
    }


@app.post("/api/decide")
async def decide_redline(decision: RedlineDecision) -> dict:
    """
    Human-in-the-Loop: Accept or reject a specific redline suggestion.
    """
    session = sessions.get(decision.session_id)
    if not session:
        raise HTTPException(404, "Session not found or expired.")

    redlines = session.get("redlines", [])
    if decision.redline_index >= len(redlines):
        raise HTTPException(400, f"Redline index {decision.redline_index} out of range.")

    if decision.decision not in ("accepted", "rejected"):
        raise HTTPException(400, "Decision must be 'accepted' or 'rejected'.")

    redlines[decision.redline_index]["status"] = decision.decision

    accepted = sum(1 for r in redlines if r.get("status") == "accepted")
    rejected = sum(1 for r in redlines if r.get("status") == "rejected")
    pending = sum(1 for r in redlines if r.get("status") == "pending")

    return {
        "ok": True,
        "redline_index": decision.redline_index,
        "new_status": decision.decision,
        "summary": {"accepted": accepted, "rejected": rejected, "pending": pending},
    }


@app.get("/api/report/{session_id}")
async def get_report(session_id: str) -> dict:
    """Get the full review report for a session."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")
    return {
        "classification": session.get("classification", {}),
        "risk_analyses": session.get("risk_analyses", []),
        "redlines": session.get("redlines", []),
        "pii_mapping_count": len(session.get("pii_mapping", {})),
        "disclaimer": DISCLAIMER,
    }


@app.post("/api/playbook")
async def add_playbook_clause(item: PlaybookUpload) -> dict:
    """Add a standard clause to the firm's playbook."""
    doc_id = playbook.add_standard_clause(
        clause_type=item.clause_type,
        text=item.text,
        metadata={"notes": item.notes},
    )
    return {"ok": True, "id": doc_id, "total_clauses": playbook.collection_count()}


@app.post("/api/playbook/bulk")
async def bulk_load_playbook(file: UploadFile = File(...)) -> dict:
    """Upload a JSON file of standard clauses to the playbook."""
    if not file.filename.endswith(".json"):
        raise HTTPException(400, "Must be a .json file")

    import tempfile, json
    content = await file.read()
    try:
        clauses = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {e}")

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="wb") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    count = playbook.load_from_json(tmp_path)
    os.unlink(tmp_path)
    return {"ok": True, "clauses_added": count, "total_clauses": playbook.collection_count()}


@app.get("/api/playbook/status")
async def playbook_status() -> dict:
    return {
        "total_clauses": playbook.collection_count(),
        "clause_types": playbook.list_clause_types(),
    }


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_risk_summary(risk_analyses: list[dict]) -> dict:
    counts = {"None": 0, "Low": 0, "Medium": 0, "High": 0, "Critical": 0}
    for r in risk_analyses:
        level = r.get("risk_level", "None")
        counts[level] = counts.get(level, 0) + 1

    high_priority = [
        {
            "clause_type": r.get("clause_type", "Unknown"),
            "risk_level": r.get("risk_level"),
            "deviation_summary": r.get("deviation_summary", ""),
            "recommended_action": r.get("recommended_action", ""),
        }
        for r in risk_analyses
        if r.get("risk_level") in ("High", "Critical")
    ]

    return {
        "total_clauses_reviewed": len(risk_analyses),
        "risk_counts": counts,
        "high_priority_flags": high_priority,
        "overall_risk": _overall_risk(counts),
    }


def _overall_risk(counts: dict) -> str:
    if counts.get("Critical", 0) > 0:
        return "Critical"
    if counts.get("High", 0) > 0:
        return "High"
    if counts.get("Medium", 0) > 0:
        return "Medium"
    if counts.get("Low", 0) > 0:
        return "Low"
    return "None"
