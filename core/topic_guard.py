"""Deterministic, inspectable checks for keeping chat turns on topic."""
import re


_GENERIC_TERMS = {
    "about", "again", "answer", "best", "book", "books", "current", "find", "give",
    "help", "information", "latest", "list", "more", "need", "read", "search", "should",
    "before", "tell", "that", "the", "this", "today", "what", "when", "where", "which", "who",
}


def topic_terms(text):
    """Return meaningful lowercase terms while excluding conversational scaffolding."""
    words = set(re.findall(r"[a-z0-9]+", (text or "").casefold()))
    return {
        word for word in words
        if (len(word) > 3 or (word.isdigit() and len(word) >= 2))
        and word not in _GENERIC_TERMS
    }


def relevance_signals(request, candidate):
    """Return transparent overlap signals for a request and generated candidate."""
    request_terms = topic_terms(request)
    candidate_terms = topic_terms(candidate)
    overlap = request_terms & candidate_terms
    missing = request_terms - candidate_terms
    introduced = candidate_terms - request_terms
    return {
        "request_terms": sorted(request_terms),
        "candidate_terms": sorted(candidate_terms),
        "overlap": sorted(overlap),
        "missing": sorted(missing),
        "introduced": sorted(introduced),
        "overlap_count": len(overlap),
        "request_term_count": len(request_terms),
        "candidate_term_count": len(candidate_terms),
        "aligned": not request_terms or bool(overlap),
    }


def candidate_matches_request(request, candidate):
    """Return whether a generated query retains a meaningful request signal."""
    return relevance_signals(request, candidate)["aligned"]
