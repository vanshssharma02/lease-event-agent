"""Prompt Injection Defense and Quarantine Guard.

Defines an abstract InjectionGuard interface allowing future ML models (e.g., DistilBERT)
to be swapped in, and implements RuleBasedGuard v1 detecting role reassignment,
instruction override, exfiltration probes, jailbreak scaffolding, base64 blobs,
and Unicode lookalikes/anomalies.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple, Set, Optional, Dict, Any
import re
import unicodedata

from app.retrieval import RetrievedChunk


@dataclass(frozen=True)
class QuarantinedChunk:
    """Details of a document chunk flagged and isolated by the injection guard."""

    chunk_id: str
    lease_id: str
    page: int
    text: str
    score: float
    reasons: List[str]


class InjectionGuard(ABC):
    """Abstract base interface for prompt injection detectors."""

    @abstractmethod
    def score(self, text: str) -> float:
        """Score the input text for injection/jailbreak indicators between 0.0 and 1.0.

        A score above 0.75 triggers quarantine.
        """
        pass

    def inspect_text(self, text: str) -> Tuple[float, List[str]]:
        """Return the score and human-readable explanation of triggered indicators."""
        return self.score(text), []


class RuleBasedGuard(InjectionGuard):
    """Rule-based injection detector using regex heuristics, entropy, and Unicode checks."""

    # 1. Role reassignment indicators
    ROLE_REASSIGNMENT_PATTERNS = [
        re.compile(r"(?i)\b(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|system)\s+instructions\b"),
        re.compile(r"(?i)\byou\s+are\s+now\s+(?:a|an|dan|admin|root|system|developer|unrestricted)\b"),
        re.compile(r"(?i)\b(?:system\s+override|new\s+instructions|system\s+prompt\s+reset)\b"),
        re.compile(r"(?i)\b(?:pretend\s+you\s+are|act\s+as\s+an?\s+unrestricted)\b"),
    ]

    # 2. Instruction override indicators
    INSTRUCTION_OVERRIDE_PATTERNS = [
        re.compile(r"(?i)\b(?:override\s+all\s+rules|bypass\s+safety|disable\s+guardrails|ignore\s+constraints)\b"),
        re.compile(r"(?i)\b(?:do\s+not\s+follow|stop\s+following)\s+(?:the\s+)?rules\b"),
        re.compile(r"(?i)\bfrom\s+now\s+on\s+you\s+will\b"),
    ]

    # 3. Exfiltration probes
    EXFILTRATION_PATTERNS = [
        re.compile(r"(?i)\b(?:print|reveal|output|display|show|leak|repeat)\s+(?:the\s+)?(?:system\s+prompt|api\s+key|env|password|secret|config|credentials)\b"),
        re.compile(r"(?i)\b(?:curl|wget|fetch)\s+https?://\S+"),
        re.compile(r"(?i)\b(?:send|post|transmit)\s+(?:data|token|key)\s+to\s+https?://"),
    ]

    # 4. Jailbreak scaffolding
    JAILBREAK_PATTERNS = [
        re.compile(r"(?i)\b(?:dan\s+mode|jailbreak|developer\s+mode\s+enabled|unrestricted\s+mode)\b"),
        re.compile(r"(?i)\bhypothetical\s+scenario\s+where\s+you\s+(?:must|can\s+bypass)\b"),
        re.compile(r"(?i)\balways\s+comply\s+without\s+moral\s+or\s+ethical\s+filter\b"),
    ]

    # 5. Base64 payload blobs (minimum 28 base64 chars)
    BASE64_PATTERN = re.compile(r"\b[A-Za-z0-9+/]{28,}={0,2}\b")

    # 6. Zero-width and anomalous control characters
    ZERO_WIDTH_CHARS = {"\u200b", "\u200c", "\u200d", "\ufeff", "\u2060", "\u200e", "\u200f"}

    def __init__(self, quarantine_threshold: float = 0.75):
        self.quarantine_threshold = quarantine_threshold

    def inspect_text(self, text: str) -> Tuple[float, List[str]]:
        """Analyze text and return (score, detected_reasons)."""
        if not text:
            return 0.0, []

        reasons: List[str] = []
        score = 0.0

        # Check Role Reassignment
        for p in self.ROLE_REASSIGNMENT_PATTERNS:
            if p.search(text):
                reasons.append("Detected role reassignment pattern")
                score += 0.85
                break

        # Check Instruction Override
        for p in self.INSTRUCTION_OVERRIDE_PATTERNS:
            if p.search(text):
                reasons.append("Detected instruction override directive")
                score += 0.85
                break

        # Check Exfiltration Probes
        for p in self.EXFILTRATION_PATTERNS:
            if p.search(text):
                reasons.append("Detected system prompt or credential exfiltration probe")
                score += 0.85
                break

        # Check Jailbreak Scaffolding
        for p in self.JAILBREAK_PATTERNS:
            if p.search(text):
                reasons.append("Detected jailbreak scaffolding phrase")
                score += 0.85
                break

        # Check Base64 Blobs
        b64_matches = self.BASE64_PATTERN.findall(text)
        if b64_matches:
            # Check if match has high diversity (not just repeated characters)
            for m in b64_matches:
                if len(set(m)) > 10:
                    reasons.append("Detected high-entropy base64 encoded payload blob")
                    score += 0.80
                    break

        # Check Zero-width / hidden Unicode characters
        found_zero_width = [ch for ch in text if ch in self.ZERO_WIDTH_CHARS]
        if found_zero_width:
            reasons.append(f"Detected zero-width/anomalous Unicode character injection ({len(found_zero_width)} occurrences)")
            score += 0.80

        # Check Mixed-Script Homoglyph attacks (e.g. Cyrillic/Greek characters inside predominantly Latin text)
        has_latin = bool(re.search(r"[a-zA-Z]", text))
        has_cyrillic = bool(re.search(r"[\u0400-\u04ff]", text))
        has_greek = bool(re.search(r"[\u0370-\u03ff]", text))
        if has_latin and (has_cyrillic or has_greek):
            # Check for intra-word script mixing
            words = text.split()
            for w in words:
                has_w_latin = bool(re.search(r"[a-zA-Z]", w))
                has_w_other = bool(re.search(r"[\u0400-\u04ff\u0370-\u03ff]", w))
                if has_w_latin and has_w_other:
                    reasons.append("Detected mixed-script homoglyph obfuscation inside words")
                    score += 0.80
                    break

        final_score = min(1.0, score)
        return final_score, reasons

    def score(self, text: str) -> float:
        """Return the injection threat score between 0.0 and 1.0."""
        score, _ = self.inspect_text(text)
        return score

    def quarantine_chunks(
        self, chunks: List[RetrievedChunk]
    ) -> Tuple[List[RetrievedChunk], List[QuarantinedChunk], List[str]]:
        """Filter chunks, quarantining those scoring above threshold.

        Returns:
          - safe_chunks: Chunks safe to pass to prompt assembly
          - quarantined_chunks: QuarantinedChunk records with scores and reasons
          - injection_flags: List of quarantined chunk IDs
        """
        safe_chunks: List[RetrievedChunk] = []
        quarantined: List[QuarantinedChunk] = []
        injection_flags: List[str] = []

        for chunk in chunks:
            threat_score, reasons = self.inspect_text(chunk.text)
            if threat_score >= self.quarantine_threshold:
                quarantined.append(
                    QuarantinedChunk(
                        chunk_id=chunk.chunk_id,
                        lease_id=chunk.lease_id,
                        page=chunk.page,
                        text=chunk.text,
                        score=threat_score,
                        reasons=reasons,
                    )
                )
                injection_flags.append(chunk.chunk_id)
            else:
                safe_chunks.append(chunk)

        return safe_chunks, quarantined, injection_flags
