"""
Agent 1 — Classifier
Determines: contract type, governing jurisdiction, key parties, and overall risk profile.
"""
import json
from anthropic import Anthropic

client = Anthropic()

SYSTEM_PROMPT = """You are a legal contract classification specialist.
Analyze the provided contract text and return a structured JSON response.
Be concise and accurate. Only output valid JSON, no prose."""

USER_TEMPLATE = """Analyze this contract and return JSON with these exact fields:
{{
  "contract_type": "e.g. NDA, SaaS Agreement, Employment Agreement, Consulting Agreement, Lease, M&A, etc.",
  "jurisdiction": "governing law / jurisdiction if stated, else 'Not specified'",
  "parties": ["list of identified party roles, e.g. Company, Contractor, Client"],
  "effective_date": "date if found, else null",
  "term": "duration/term if found, else null",
  "key_topics": ["top 5 legal topics covered"],
  "initial_risk_level": "Low | Medium | High",
  "initial_risk_reason": "one sentence explaining the initial risk assessment"
}}

CONTRACT TEXT:
{text}"""


def classify(anonymized_text: str) -> dict:
    """Run the classifier agent on anonymized contract text."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_TEMPLATE.format(text=anonymized_text[:6000]),
            }
        ],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "contract_type": "Unknown",
            "jurisdiction": "Unknown",
            "parties": [],
            "effective_date": None,
            "term": None,
            "key_topics": [],
            "initial_risk_level": "Unknown",
            "initial_risk_reason": raw,
        }
