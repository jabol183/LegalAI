"""
Agentic Orchestrator using LangGraph.
Coordinates the full contract review workflow:
  1. Parse → 2. Anonymize → 3. Classify → 4. Risk Analysis → 5. Redline → 6. Report
"""
from __future__ import annotations

import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from backend.anonymizer import anonymizer
from backend.parser import chunk_into_clauses, extract_text
from backend.agents.classifier import classify
from backend.agents.risk_analyst import analyze_all_clauses
from backend.agents.redliner import redline_flagged_clauses


# ── State schema ──────────────────────────────────────────────────────────────

class ContractState(TypedDict, total=False):
    # Input
    file_bytes: bytes
    filename: str

    # Parsed
    raw_text: str
    clauses: list[str]

    # Anonymization
    anonymized_text: str
    anonymized_clauses: list[str]
    pii_mapping: dict[str, str]

    # Agent outputs
    classification: dict
    risk_analyses: list[dict]
    redlines: list[dict]

    # Meta
    error: str | None
    elapsed_seconds: float


# ── Node functions ─────────────────────────────────────────────────────────────

def parse_node(state: ContractState) -> ContractState:
    try:
        raw_text = extract_text(state["file_bytes"], state["filename"])
        clauses = chunk_into_clauses(raw_text)
        return {**state, "raw_text": raw_text, "clauses": clauses, "error": None}
    except Exception as e:
        return {**state, "error": f"Parse error: {e}"}


def anonymize_node(state: ContractState) -> ContractState:
    if state.get("error"):
        return state
    try:
        anon_text, mapping = anonymizer.anonymize(state["raw_text"])
        anon_clauses = []
        for clause in state["clauses"]:
            a, _ = anonymizer.anonymize(clause)
            anon_clauses.append(a)
        return {
            **state,
            "anonymized_text": anon_text,
            "anonymized_clauses": anon_clauses,
            "pii_mapping": mapping,
        }
    except Exception as e:
        return {**state, "error": f"Anonymization error: {e}"}


def classify_node(state: ContractState) -> ContractState:
    if state.get("error"):
        return state
    try:
        classification = classify(state["anonymized_text"])
        return {**state, "classification": classification}
    except Exception as e:
        return {**state, "error": f"Classification error: {e}"}


def risk_analysis_node(state: ContractState) -> ContractState:
    if state.get("error"):
        return state
    try:
        clf = state["classification"]
        risk_analyses = analyze_all_clauses(
            clauses=state["anonymized_clauses"],
            contract_type=clf.get("contract_type", "Unknown"),
            jurisdiction=clf.get("jurisdiction", "Unknown"),
        )
        return {**state, "risk_analyses": risk_analyses}
    except Exception as e:
        return {**state, "error": f"Risk analysis error: {e}"}


def redline_node(state: ContractState) -> ContractState:
    if state.get("error"):
        return state
    try:
        clf = state["classification"]
        redlines = redline_flagged_clauses(
            risk_analyses=state["risk_analyses"],
            contract_type=clf.get("contract_type", "Unknown"),
            jurisdiction=clf.get("jurisdiction", "Unknown"),
            min_risk_level="Medium",
        )
        return {**state, "redlines": redlines}
    except Exception as e:
        return {**state, "error": f"Redline error: {e}"}


def should_continue(state: ContractState) -> str:
    return "error" if state.get("error") else "continue"


# ── Build graph ────────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    graph = StateGraph(ContractState)

    graph.add_node("parse", parse_node)
    graph.add_node("anonymize", anonymize_node)
    graph.add_node("classify", classify_node)
    graph.add_node("risk_analysis", risk_analysis_node)
    graph.add_node("redline", redline_node)

    graph.set_entry_point("parse")
    graph.add_edge("parse", "anonymize")
    graph.add_edge("anonymize", "classify")
    graph.add_edge("classify", "risk_analysis")
    graph.add_edge("risk_analysis", "redline")
    graph.add_edge("redline", END)

    return graph.compile()


workflow = build_graph()


# ── Public API ────────────────────────────────────────────────────────────────

def run_contract_review(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """
    Run the full contract review workflow.
    Returns the complete state with all agent outputs.
    """
    start = time.time()
    initial_state: ContractState = {
        "file_bytes": file_bytes,
        "filename": filename,
    }
    final_state = workflow.invoke(initial_state)
    final_state["elapsed_seconds"] = round(time.time() - start, 2)

    # Remove raw bytes from output
    final_state.pop("file_bytes", None)

    return final_state
