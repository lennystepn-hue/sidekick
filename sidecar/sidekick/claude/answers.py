"""Interpret a spoken reply as a permission decision or an answer to AskUserQuestion."""

from __future__ import annotations

import re
from typing import Any

YES = {
    "ja", "jap", "jo", "yes", "yep", "yeah", "ok", "okay", "erlauben", "erlaubt", "erlaube", "mach", "machen",
    "weiter", "go", "genehmigt", "klar", "gerne", "sicher", "bitte", "los", "zustimmen", "einverstanden", "allow",
    "approve", "approved", "sure", "fine", "passt",
}
NO = {
    "nein", "no", "nope", "nicht", "ablehnen", "abbrechen", "abbruch", "stop", "stopp", "lass", "verweigern",
    "cancel", "deny", "denied", "niemals", "never", "warte",
}
ALWAYS_PHRASES = (
    "immer", "always", "dauerhaft", "permanent", "jedes mal", "jedesmal", "nicht mehr fragen", "nicht nochmal fragen",
    "don't ask again", "dont ask again", "for the session", "für die session", "für diese session",
)
ORDINALS = {
    "eins": 0, "erste": 0, "ersten": 0, "erstes": 0, "first": 0, "one": 0, "1": 0,
    "zwei": 1, "zweite": 1, "zweiten": 1, "zweites": 1, "second": 1, "two": 1, "2": 1,
    "drei": 2, "dritte": 2, "dritten": 2, "drittes": 2, "third": 2, "three": 2, "3": 2,
    "vier": 3, "vierte": 3, "vierten": 3, "fourth": 3, "four": 3, "4": 3,
}
MAX_DECISION_WORDS = 8


def normalize(text: str) -> str:
    return re.sub(r"[^\w\s'-]", " ", (text or "").lower()).strip()


def tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s-]+", normalize(text)) if t]


def parse_decision(text: str) -> str | None:
    """Return "allow", "deny", "allow_always" or None (treat as free text).

    A decision is recognised when the utterance starts with a yes/no word, or is very
    short and contains one. Longer sentences are content, not decisions.
    """
    norm = normalize(text)
    toks = tokens(text)
    if not toks or len(toks) > MAX_DECISION_WORDS:
        return None
    if any(p in norm for p in ALWAYS_PHRASES):
        return "deny" if toks[0] in NO and "nicht mehr fragen" not in norm else "allow_always"
    if toks[0] in NO:
        return "deny"
    if toks[0] in YES:
        return "deny" if any(t in NO for t in toks[1:3]) else "allow"
    if len(toks) <= 3:
        if any(t in NO for t in toks):
            return "deny"
        if any(t in YES for t in toks):
            return "allow"
    return None


def match_option(text: str, options: list[str]) -> str | None:
    if not options:
        return None
    norm = normalize(text)
    toks = tokens(text)
    lowered = [normalize(o) for o in options]
    for i, opt in enumerate(lowered):
        if opt and opt == norm:
            return options[i]
    for tok in toks:
        idx = ORDINALS.get(tok)
        if idx is not None and idx < len(options) and len(toks) <= 3:
            return options[idx]
    for i, opt in enumerate(lowered):
        if opt and (norm.startswith(opt) or opt.startswith(norm)) and len(norm) >= 3:
            return options[i]
    best, best_score = None, 0.0
    tokset = set(toks)
    for i, opt in enumerate(lowered):
        opt_toks = set(tokens(opt))
        if not opt_toks:
            continue
        overlap = len(tokset & opt_toks) / len(opt_toks)
        if overlap > best_score:
            best, best_score = options[i], overlap
    return best if best_score >= 0.6 else None


def build_question_answers(questions: list[dict[str, Any]], text: str) -> dict[str, Any]:
    """Map a spoken answer onto AskUserQuestion's `answers` structure."""
    answers: dict[str, Any] = {}
    for q in questions or []:
        question = str(q.get("question", ""))
        labels = [str(o.get("label", "")) for o in q.get("options", []) if isinstance(o, dict)]
        if q.get("multiSelect"):
            parts = [p for p in re.split(r"\s*(?:,| und | and |;)\s*", text) if p.strip()]
            picked = [m for m in (match_option(p, labels) for p in parts) if m]
            answers[question] = picked or [text.strip()]
        else:
            answers[question] = match_option(text, labels) or text.strip()
    return answers
