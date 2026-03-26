"""
PII Anonymization Layer using Microsoft Presidio.
Masks sensitive data before it ever touches the LLM.
"""
import re
from typing import Optional

try:
    from presidio_analyzer import AnalyzerEngine, RecognizerResult
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig
    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False

import spacy

# Mapping from detected entity type → placeholder token
ENTITY_PLACEHOLDER_MAP = {
    "PERSON": "PARTY",
    "ORG": "ORGANIZATION",
    "GPE": "JURISDICTION",
    "LOC": "LOCATION",
    "DATE": "DATE_REF",
    "MONEY": "M_AMOUNT",
    "CARDINAL": "NUMERIC_VALUE",
    "EMAIL_ADDRESS": "EMAIL_REF",
    "PHONE_NUMBER": "PHONE_REF",
    "URL": "URL_REF",
    "IP_ADDRESS": "IP_REF",
    "US_SSN": "SSN_REF",
    "IBAN_CODE": "IBAN_REF",
}


class ContractAnonymizer:
    """
    Anonymizes PII in contract text before sending to LLM.
    Keeps a reverse mapping so results can be de-anonymized for display.
    """

    def __init__(self):
        self._analyzer: Optional[object] = None
        self._anonymizer: Optional[object] = None
        self._counters: dict[str, int] = {}

    def _init_engines(self):
        if not PRESIDIO_AVAILABLE:
            return
        if self._analyzer is None:
            self._analyzer = AnalyzerEngine()
            self._anonymizer = AnonymizerEngine()

    def anonymize(self, text: str) -> tuple[str, dict[str, str]]:
        """
        Returns (anonymized_text, mapping) where mapping is
        { placeholder → original_value }.
        """
        self._counters = {}
        mapping: dict[str, str] = {}

        if PRESIDIO_AVAILABLE:
            return self._presidio_anonymize(text, mapping)
        else:
            return self._regex_anonymize(text, mapping)

    def _presidio_anonymize(self, text: str, mapping: dict) -> tuple[str, dict]:
        self._init_engines()
        results = self._analyzer.analyze(text=text, language="en")

        # Sort by start position descending so we replace from end to start
        results = sorted(results, key=lambda r: r.start, reverse=True)

        anonymized = text
        for result in results:
            original = text[result.start:result.end]
            entity_type = result.entity_type
            base_label = ENTITY_PLACEHOLDER_MAP.get(entity_type, entity_type)

            # Generate unique counter per entity type + value
            key = f"{base_label}_{original}"
            if key not in mapping:
                self._counters[base_label] = self._counters.get(base_label, 0) + 1
                placeholder = f"[{base_label}_{self._counters[base_label]}]"
                mapping[placeholder] = original
            else:
                placeholder = next(k for k, v in mapping.items() if v == original and k.startswith(f"[{base_label}"))

            anonymized = anonymized[:result.start] + placeholder + anonymized[result.end:]

        return anonymized, mapping

    def _regex_anonymize(self, text: str, mapping: dict) -> tuple[str, dict]:
        """Fallback regex-based anonymizer if Presidio is not installed."""
        patterns = [
            (r'\b[A-Z][a-z]+ [A-Z][a-z]+\b', "PARTY"),
            (r'\$[\d,]+(?:\.\d{2})?(?:\s*(?:million|billion|thousand))?', "M_AMOUNT"),
            (r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', "DATE_REF"),
            (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', "EMAIL_REF"),
            (r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b', "PHONE_REF"),
        ]

        anonymized = text
        for pattern, label in patterns:
            def replacer(match, lbl=label):
                original = match.group(0)
                self._counters[lbl] = self._counters.get(lbl, 0) + 1
                placeholder = f"[{lbl}_{self._counters[lbl]}]"
                mapping[placeholder] = original
                return placeholder
            anonymized = re.sub(pattern, replacer, anonymized)

        return anonymized, mapping

    def deanonymize(self, text: str, mapping: dict[str, str]) -> str:
        """Restore original values from placeholders."""
        result = text
        # Sort by length descending to avoid partial replacements
        for placeholder, original in sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True):
            result = result.replace(placeholder, original)
        return result


anonymizer = ContractAnonymizer()
