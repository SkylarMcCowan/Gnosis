"""Runs every reviewer over the same content. Returns a plain
{"security": ..., "performance": ..., "documentation": ...} dict, not a
synthesized recommendation - release_manager.summarize_reviews does that
separately, since it also needs to know whether tests passed, which isn't
every caller's business to thread through here.
"""
from reviewers.documentation import review_documentation
from reviewers.performance import review_performance
from reviewers.security import review_security


def run_review_panel(content, coding_chat_fn):
    return {
        "security": review_security(content, coding_chat_fn),
        "performance": review_performance(content, coding_chat_fn),
        "documentation": review_documentation(content, coding_chat_fn),
    }
