"""Deterministic, inspectable checks for keeping chat turns on topic."""
import re


_GENERIC_TERMS = {
    "about", "again", "answer", "best", "book", "books", "current", "find", "give",
    "help", "information", "latest", "list", "more", "need", "read", "search", "should",
    "before", "tell", "that", "the", "this", "today", "what", "when", "where", "which", "who",
}


def topic_terms(text):
    """Return meaningful lowercase terms while excluding conversational scaffolding."""
    normalized = re.sub(r"\bmoth[ -]+man\b", "mothman", (text or "").casefold())
    words = set(re.findall(r"[a-z0-9]+", normalized))
    return {
        word for word in words
        if (len(word) > 3 or (word.isdigit() and len(word) >= 2))
        and word not in _GENERIC_TERMS
    }


def _close_spelling(left, right):
    """Allow one typo in longer words, never fuzzy-match short words or numbers."""
    if left == right:
        return True
    if min(len(left), len(right)) < 5 or not (left.isalpha() and right.isalpha()):
        return False
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        differences = [i for i, (a, b) in enumerate(zip(left, right)) if a != b]
        return len(differences) == 1 or (
            len(differences) == 2 and differences[1] == differences[0] + 1
            and left[differences[0]] == right[differences[1]]
            and left[differences[1]] == right[differences[0]]
        )
    shorter, longer = sorted((left, right), key=len)
    return any(longer[:i] + longer[i + 1:] == shorter for i in range(len(longer)))


def _matched_terms(request_terms, candidate_terms):
    """Count distinct matches; a single candidate word cannot satisfy two terms."""
    assigned = {}

    def match(term, visited):
        for candidate in sorted(candidate_terms, key=lambda word: (word != term, word)):
            if candidate in visited or not _close_spelling(term, candidate):
                continue
            visited.add(candidate)
            if candidate not in assigned or match(assigned[candidate], visited):
                assigned[candidate] = term
                return True
        return False

    for term in sorted(request_terms):
        match(term, set())
    return set(assigned.values())


def relevance_signals(request, candidate):
    """Return transparent overlap signals for a request and generated candidate."""
    request_terms = topic_terms(request)
    candidate_terms = topic_terms(candidate)
    overlap = request_terms & candidate_terms
    spelling_matches = _matched_terms(request_terms, candidate_terms) - overlap
    missing = request_terms - candidate_terms
    introduced = candidate_terms - request_terms
    return {
        "request_terms": sorted(request_terms),
        "candidate_terms": sorted(candidate_terms),
        "overlap": sorted(overlap),
        "spelling_matches": sorted(spelling_matches),
        "missing": sorted(missing),
        "introduced": sorted(introduced),
        "overlap_count": len(overlap),
        "request_term_count": len(request_terms),
        "candidate_term_count": len(candidate_terms),
        "aligned": not request_terms or bool(overlap or spelling_matches),
    }


def candidate_matches_request(request, candidate):
    """Return whether a generated query retains a meaningful request signal."""
    return relevance_signals(request, candidate)["aligned"]


def filter_web_results(query, results):
    """Reject obvious topic mismatches before scoring; overlap is not verification.

    Require two distinct terms for multiword subjects, so a hit for just
    'Golden' cannot establish relevance to 'Golden Dawn'. Inspect excerpts,
    not URLs, whose domains and tracking parameters can create false matches.
    """
    def normalized_terms(text):
        text = re.sub(r"\b(?:united states(?: of america)?|america|usa|u\.s\.a\.|u\.s\.)\b",
                      "american", text.casefold())
        return topic_terms(text)

    terms = normalized_terms(query) - {
        "lets", "talk", "some", "sciences", "with", "from", "have", "does",
        "please", "explain", "official", "source", "sources", "section",
        "foundations", "vocabulary", "historical", "development", "mechanisms",
        "worked", "examples", "applications", "debates", "limitations", "synthesis",
        "further", "questions",
    }
    required = min(2, len(terms))
    return [result for result in results if len(_matched_terms(terms, normalized_terms(
        f"{result.get('title', '')} {result.get('content', '')}"
    ))) >= required]
