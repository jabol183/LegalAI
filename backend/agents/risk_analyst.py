"""
Agent 2 — Risk Analyst
Compares each contract clause against the playbook and flags deviations.
"""
import json
from anthropic import Anthropic
from backend.playbook import playbook

client = Anthropic()

SYSTEM_PROMPT = """You are a senior legal risk analyst at a law firm.
Your job is to compare contract clauses against the firm's standard playbook language.
Return only valid JSON, no prose."""

CLAUSE_ANALYSIS_TEMPLATE = """You are reviewing a contract clause against the firm's standard language.

CONTRACT CLAUSE:
{clause}

MOST SIMILAR STANDARD CLAUSE FROM PLAYBOOK (similarity: {similarity}):
Type: {clause_type}
Text: {standard_text}

Analyze the deviation and return JSON:
{{
  "clause_type": "{clause_type}",
  "risk_level": "None | Low | Medium | High | Critical",
  "deviation_summary": "one sentence describing how this clause differs from standard",
  "specific_issues": ["list each specific issue found"],
  "favors": "Client | Counterparty | Neutral",
  "recommended_action": "Accept | Negotiate | Reject | Flag for Attorney"
}}"""

NO_PLAYBOOK_TEMPLATE = """Review this contract clause for general legal risk:

CONTRACT CLAUSE:
{clause}

CONTRACT TYPE: {contract_type}
JURISDICTION: {jurisdiction}

Return JSON:
{{
  "clause_type": "inferred clause type",
  "risk_level": "None | Low | Medium | High | Critical",
  "deviation_summary": "summary of any concerns",
  "specific_issues": ["list specific issues if any"],
  "favors": "Client | Counterparty | Neutral",
  "recommended_action": "Accept | Negotiate | Reject | Flag for Attorney"
}}"""


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": raw}


def analyze_clause(
    clause: str,
    contract_type: str,
    jurisdiction: str,
    similarity_threshold: float = 0.55,
) -> dict:
    """
    Analyze a single clause against the playbook.
    Returns a risk assessment dict.
    """
    similar = playbook.find_similar_clauses(clause, n_results=1)

    if similar and similar[0]["similarity"] >= similarity_threshold:
        best = similar[0]
        prompt = CLAUSE_ANALYSIS_TEMPLATE.format(
            clause=clause[:1500],
            similarity=best["similarity"],
            clause_type=best["clause_type"],
            standard_text=best["standard_text"][:800],
        )
    else:
        prompt = NO_PLAYBOOK_TEMPLATE.format(
            clause=clause[:1500],
            contract_type=contract_type,
            jurisdiction=jurisdiction,
        )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    result = _parse_json(response.content[0].text)
    result["original_clause"] = clause
    result["playbook_match"] = similar[0] if similar else None
    return result


def analyze_all_clauses(
    clauses: list[str],
    contract_type: str,
    jurisdiction: str,
) -> list[dict]:
    """Run risk analysis on all clauses, return only flagged ones."""
    results = []
    for i, clause in enumerate(clauses):
        if len(clause.strip()) < 50:
            continue
        analysis = analyze_clause(clause, contract_type, jurisdiction)
        analysis["clause_index"] = i
        results.append(analysis)
    return results
