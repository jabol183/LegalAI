"""
Agent 3 — Redliner
Rewrites flagged clauses using the firm's playbook language as reference.
Produces tracked-changes style suggestions for Human-in-the-Loop review.
"""
import json
from anthropic import Anthropic

client = Anthropic()

SYSTEM_PROMPT = """You are a senior contract attorney specializing in redlining contracts.
Your job is to rewrite problematic clauses using the firm's preferred language.
Always explain your changes. Return only valid JSON."""

REDLINE_TEMPLATE = """Rewrite the following contract clause to protect our client's interests.

ORIGINAL CLAUSE:
{original}

RISK ISSUES IDENTIFIED:
{issues}

FIRM'S STANDARD LANGUAGE (use as reference if available):
{standard}

CONTRACT CONTEXT:
- Type: {contract_type}
- Jurisdiction: {jurisdiction}
- Risk Level: {risk_level}

Return JSON:
{{
  "rewritten_clause": "the full rewritten clause text",
  "changes_summary": "brief explanation of what was changed and why",
  "change_details": [
    {{"original": "specific text changed", "replacement": "new text", "reason": "why"}}
  ],
  "negotiation_notes": "what to tell opposing counsel",
  "fallback_position": "minimum acceptable alternative if they reject our redline"
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
        # Truncated JSON — try to salvage the rewritten_clause value at minimum
        import re
        match = re.search(r'"rewritten_clause"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
        if match:
            try:
                rewritten = match.group(1).encode().decode("unicode_escape")
            except Exception:
                rewritten = match.group(1)
            summary_match = re.search(r'"changes_summary"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
            return {
                "rewritten_clause": rewritten,
                "changes_summary": summary_match.group(1) if summary_match else "Response was truncated — clause was rewritten but full summary unavailable.",
                "change_details": [],
                "negotiation_notes": "",
                "fallback_position": "",
                "_truncated": True,
            }
        return {"error": "JSON parse failed", "rewritten_clause": ""}


def redline_clause(
    original_clause: str,
    issues: list[str],
    standard_text: str,
    contract_type: str,
    jurisdiction: str,
    risk_level: str,
) -> dict:
    """Generate a redlined version of a flagged clause."""
    prompt = REDLINE_TEMPLATE.format(
        original=original_clause[:1500],
        issues="\n".join(f"- {i}" for i in issues) if issues else "- General risk identified",
        standard=standard_text[:800] if standard_text else "No standard clause on file",
        contract_type=contract_type,
        jurisdiction=jurisdiction,
        risk_level=risk_level,
    )

    # Use Sonnet only for High/Critical — Haiku handles Medium redlines
    risk_order = {"None": 0, "Low": 1, "Medium": 2, "High": 3, "Critical": 4}
    model = "claude-sonnet-4-6" if risk_order.get(risk_level, 0) >= 3 else "claude-haiku-4-5-20251001"

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    result = _parse_json(response.content[0].text)
    result["original_clause"] = original_clause
    result["risk_level"] = risk_level
    result["status"] = "pending"  # HITL: pending | accepted | rejected
    return result


def redline_flagged_clauses(
    risk_analyses: list[dict],
    contract_type: str,
    jurisdiction: str,
    min_risk_level: str = "Medium",
) -> list[dict]:
    """
    Run redlining on all clauses that meet the minimum risk threshold.
    Returns list of redline suggestions ready for HITL review.
    """
    risk_order = {"None": 0, "Low": 1, "Medium": 2, "High": 3, "Critical": 4}
    min_level = risk_order.get(min_risk_level, 2)

    redlines = []
    for analysis in risk_analyses:
        # Skip only if there's no risk_level — a parse error from risk analyst
        if not analysis.get("risk_level"):
            continue
        level = analysis.get("risk_level", "None")
        if risk_order.get(level, 0) < min_level:
            continue

        standard_text = ""
        if analysis.get("playbook_match"):
            standard_text = analysis["playbook_match"].get("standard_text", "")

        redline = redline_clause(
            original_clause=analysis.get("original_clause", ""),
            issues=analysis.get("specific_issues", []),
            standard_text=standard_text,
            contract_type=contract_type,
            jurisdiction=jurisdiction,
            risk_level=level,
        )
        redline["clause_index"] = analysis.get("clause_index", -1)
        redline["clause_type"] = analysis.get("clause_type", "Unknown")
        redlines.append(redline)

    return redlines
