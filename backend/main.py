"""
FastAPI backend for LegalAI — Agentic contract review system.
"""

DISCLAIMER = (
    "NOT LEGAL ADVICE: LegalAI is an AI-powered document analysis tool only. "
    "It does not provide legal advice, does not constitute the practice of law, "
    "and does not create an attorney-client relationship. All output may contain "
    "errors and must not be relied upon as a substitute for advice from a licensed attorney. "
    "Always consult a qualified legal professional before making any legal decisions."
)
import json
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

# ── File-backed session store (survives server restarts / hot-reloads) ─────────
SESSIONS_FILE = Path(os.getenv("SESSIONS_FILE", "./sessions.json"))


def _load_sessions() -> dict:
    if SESSIONS_FILE.exists():
        try:
            return json.loads(SESSIONS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_sessions(data: dict):
    SESSIONS_FILE.write_text(json.dumps(data))


sessions: dict[str, dict] = _load_sessions()

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
    _save_sessions(sessions)

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
    _save_sessions(sessions)

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


@app.post("/api/finalize/{session_id}")
async def finalize_contract(session_id: str):
    """
    Apply all accepted redlines to the original contract text,
    de-anonymize it, highlight unfilled placeholders in red,
    and return a Markdown file download.
    """
    import re
    from fastapi.responses import Response
    from backend.anonymizer import anonymizer

    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")

    redlines = session.get("redlines", [])
    accepted = [r for r in redlines if r.get("status") == "accepted"]

    if not accepted:
        raise HTTPException(400, "No accepted redlines to apply. Accept at least one suggestion first.")

    # Start from the raw (anonymized) contract text
    contract = session.get("raw_text") or session.get("anonymized_text", "")
    if not contract:
        raise HTTPException(500, "Original contract text not found in session.")

    # Apply each accepted redline: replace original clause with rewritten clause
    applied, skipped = [], []
    for r in accepted:
        original = (r.get("original_clause") or "").strip()
        rewritten = (r.get("rewritten_clause") or "").strip()
        if not original or not rewritten:
            skipped.append(r.get("clause_type", "unknown"))
            continue
        if original in contract:
            contract = contract.replace(original, rewritten, 1)
            applied.append(r.get("clause_type", "unknown"))
        else:
            skipped.append(r.get("clause_type", "unknown"))

    # De-anonymize: restore original PII values
    pii_mapping = session.get("pii_mapping", {})
    if pii_mapping:
        contract = anonymizer.deanonymize(contract, pii_mapping)

    # ── Highlight unfilled placeholders in red ─────────────────────────────
    # Matches:
    #   [ALL CAPS or mixed with dashes/en-dashes]  e.g. [EFFECTIVE DATE], [CLIENT FORMATION STATE — TO BE CONFIRMED]
    #   Leftover anonymizer tokens                  e.g. [PARTY_1], [DATE_TIME_2], [LOCATION_3]
    #   Playbook template variables                 e.g. {{variable_name}}
    PLACEHOLDER_PATTERNS = [
        r'\{\{[a-z_]+\}\}',                            # {{variable_name}}
        r'\[[A-Z][A-Z0-9 _\-–—/,\.]+\]',              # [ALL CAPS PLACEHOLDER]
        r'\[[A-Za-z ]+[—–\-][A-Za-z ,]+\]',            # [Text — TO BE CONFIRMED]
    ]
    combined = re.compile('|'.join(PLACEHOLDER_PATTERNS))

    def red(match: re.Match) -> str:
        return f'<span style="color:red">**{match.group(0)}**</span>'

    contract = combined.sub(red, contract)

    # ── Format contract body as Markdown ──────────────────────────────────
    # Convert numbered clause headings (e.g. "1. Parties") to ## headings
    contract = re.sub(
        r'^(\d+\.(?:\d+\.)*)\s+([A-Z][^\n]{2,60})$',
        lambda m: f'\n## {m.group(1)} {m.group(2)}',
        contract,
        flags=re.MULTILINE,
    )
    # Ensure paragraph spacing
    contract = re.sub(r'\n{3,}', '\n\n', contract)

    # ── Build Markdown document ────────────────────────────────────────────
    clf = session.get("classification", {})
    placeholder_count = len(combined.findall(
        session.get("raw_text", "") + " ".join(r.get("rewritten_clause", "") for r in accepted)
    ))

    md = f"""# {clf.get('contract_type', 'Contract')} — LegalAI Redlined Version

> ⚠️ **{DISCLAIMER}**

---

## Review Summary

| Field | Value |
|---|---|
| Contract Type | {clf.get('contract_type', 'Unknown')} |
| Jurisdiction | {clf.get('jurisdiction', 'Unknown')} |
| Redlines Applied | {len(applied)} ({', '.join(applied) or 'none'}) |
| Redlines Skipped | {len(skipped)} ({', '.join(skipped) or 'none'}) |

> 🔴 **Items highlighted in red require your attention before execution.**
> Search for `<span` to find all unfilled fields, or use your Markdown renderer's search.

---

{contract}

---

*Generated by LegalAI · {DISCLAIMER}*
"""

    filename = f"legalai-final-{session_id[:8]}.md"
    return Response(
        content=md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


@app.post("/api/playbook/reseed")
async def reseed_playbook() -> dict:
    """Wipe and reload the playbook from the bundled standard_clauses.json."""
    seed_path = Path(__file__).parent.parent / "playbooks" / "standard_clauses.json"
    if not seed_path.exists():
        raise HTTPException(404, "standard_clauses.json not found")
    count = playbook.reseed(str(seed_path))
    return {"ok": True, "clauses_loaded": count, "total_clauses": playbook.collection_count()}


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
