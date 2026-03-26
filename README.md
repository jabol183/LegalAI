# ⚖ LegalAI

> An agentic contract review system inspired by LegalFly — built with Claude, LangGraph, ChromaDB, and Microsoft Presidio.

LegalAI solves the three biggest hurdles in legal AI: **Data Privacy**, **Contextual Accuracy**, and **User Friction**. It doesn't just "read" a contract — it executes a full legal workflow through a pipeline of specialized AI agents.

---

## How It Works

### 1. PII Anonymization (Privacy-First)

Before a document ever reaches the LLM, it passes through a local anonymization engine powered by **Microsoft Presidio**. Names, addresses, deal amounts, emails, and other sensitive identifiers are replaced with structured placeholders:

```
John Smith agreed to pay $2,500,000 to Acme Corp
→ [PARTY_1] agreed to pay [M_AMOUNT_1] to [ORGANIZATION_1]
```

The AI processes the **legal logic**, not the private data. The mapping is stored in-memory and used only to display results to the authorized user.

### 2. Multi-Agent Pipeline (LangGraph)

Instead of one giant prompt, LegalAI uses a **5-node LangGraph DAG** of specialized agents:

```
Parse → Anonymize → Classify → Risk Analysis → Redline
```

| Agent | Role |
|---|---|
| **Classifier** | Identifies contract type, jurisdiction, parties, term, and initial risk level |
| **Risk Analyst** | Compares each clause against the firm's Playbook via RAG; flags deviations |
| **Redliner** | Rewrites flagged clauses using the firm's preferred fallback language |

### 3. Playbook Engine (RAG)

Firms upload their "gold standard" clause library. For every clause in a new contract, the system:

1. Embeds the clause and queries **ChromaDB** for the most similar standard clause
2. Passes both to the Risk Analyst agent for comparison
3. Flags deviations, noting whether the clause favors Client, Counterparty, or is Neutral

10 standard clauses are pre-loaded (Indemnification, Limitation of Liability, Confidentiality, IP Assignment, Termination, Governing Law, Non-Solicitation, Payment Terms, Warranties, and more).

### 4. Human-in-the-Loop (HITL)

The AI **never applies changes automatically**. Every redline suggestion surfaces in the UI with:
- Side-by-side diff (Original vs. Proposed)
- Changes summary and negotiation notes
- Fallback position if the counterparty rejects the redline
- **Accept / Reject** buttons — decisions are recorded per session

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Claude (claude-sonnet-4-6) via Anthropic API |
| Agent Orchestration | LangGraph |
| PII Masking | Microsoft Presidio + spaCy (`en_core_web_lg`) |
| Vector Database | ChromaDB (local, no external service needed) |
| Backend | FastAPI + Uvicorn |
| Document Parsing | pypdf + python-docx |
| Frontend | Vanilla HTML/CSS/JS (dark mode, no framework) |

---

## Project Structure

```
LegalAI/
├── backend/
│   ├── main.py              # FastAPI app — all API routes
│   ├── orchestrator.py      # LangGraph 5-node workflow
│   ├── anonymizer.py        # PII masking (Presidio + regex fallback)
│   ├── parser.py            # PDF/DOCX/TXT → text + clause chunking
│   ├── playbook.py          # ChromaDB RAG engine
│   └── agents/
│       ├── classifier.py    # Agent 1: contract classification
│       ├── risk_analyst.py  # Agent 2: clause risk assessment
│       └── redliner.py      # Agent 3: clause rewriting
├── frontend/
│   ├── index.html           # Single-page UI
│   ├── style.css            # Dark-mode design system
│   └── app.js               # UI logic, API calls, HITL flow
├── playbooks/
│   └── standard_clauses.json  # Pre-loaded gold standard clauses
├── .env.example
├── requirements.txt
└── start.sh                 # One-command setup + launch
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com)

### 1. Clone and configure

```bash
git clone https://github.com/jabol183/LegalAI.git
cd LegalAI
cp .env.example .env
```

Open `.env` and add your key:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Run

```bash
./start.sh
```

This will automatically:
- Create a Python virtual environment
- Install all dependencies
- Download the spaCy NER model (`en_core_web_lg`)
- Seed ChromaDB with the 10 pre-loaded standard clauses
- Start the server at `http://localhost:8000`

### 3. Open the UI

Visit `http://localhost:8000` in your browser.

---

## API Reference

### `POST /api/review`
Upload a contract for full agentic review.

- **Body:** `multipart/form-data` with `file` (PDF, DOCX, or TXT, max 10 MB)
- **Returns:** `session_id`, classification, risk summary, and redline suggestions

```bash
curl -X POST http://localhost:8000/api/review \
  -F "file=@contract.pdf"
```

---

### `POST /api/decide`
Record a Human-in-the-Loop accept/reject decision on a redline.

```json
{
  "session_id": "abc123",
  "redline_index": 0,
  "decision": "accepted"
}
```

---

### `GET /api/report/{session_id}`
Retrieve the full structured report for a session (classification + risk analyses + redlines with decisions).

---

### `POST /api/playbook`
Add a single standard clause to the playbook.

```json
{
  "clause_type": "Indemnification",
  "text": "Each party shall defend and indemnify...",
  "notes": "Preferred balanced language"
}
```

---

### `POST /api/playbook/bulk`
Bulk-load standard clauses from a JSON file.

- **Body:** `multipart/form-data` with `file` (JSON)
- **Format:** `[{"type": "...", "text": "...", "metadata": {...}}]`

---

### `GET /api/playbook/status`
Returns the number of clauses in the playbook and all clause types present.

---

## Adding Your Firm's Playbook

You can load your own standard clauses in three ways:

**Option A — UI:** Use the Playbook Manager section at the bottom of the page to add clauses one at a time or upload a JSON file.

**Option B — JSON file upload via API:**
```bash
curl -X POST http://localhost:8000/api/playbook/bulk \
  -F "file=@my_firm_clauses.json"
```

**Option C — Edit the seed file** at `playbooks/standard_clauses.json` before first launch. The startup script loads it automatically into ChromaDB if the database is empty.

JSON format:
```json
[
  {
    "type": "Indemnification",
    "text": "Your firm's preferred indemnification language...",
    "metadata": { "risk_area": "Liability", "favors": "Client" }
  }
]
```

---

## Risk Level Definitions

| Level | Meaning | Default Action |
|---|---|---|
| **None** | Matches playbook, no issues | Accept |
| **Low** | Minor stylistic deviation | Accept or minor edit |
| **Medium** | Deviation from standard that warrants review | Negotiate |
| **High** | Significant exposure, unfavorable terms | Redline |
| **Critical** | Unacceptable risk, potential liability | Reject |

Only **Medium and above** trigger automatic redline generation.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Your Anthropic API key |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | Where ChromaDB stores its data |
| `UPLOAD_DIR` | `./uploads` | Temp directory for uploaded files |

---

## Limitations & Production Notes

- **Sessions are in-memory** — restarting the server clears all sessions. For production, replace the `sessions` dict in `main.py` with Redis or a database.
- **No authentication** — add OAuth or API key middleware before exposing this publicly.
- **10 MB file limit** — adjustable in `main.py`.
- **Presidio requires the spaCy model** — the startup script downloads it automatically (~750 MB first run).
- **Rate limits** — large contracts with many clauses make multiple Claude API calls. Consider batching for very long documents.

---

## License

MIT
