"""Repeatable retrieval evaluation and source-removal diagnostics, fully local.

Run: python -m core.chat_evaluation cases.json
Each case: {query, expected_sources: [relative paths], excluded_sources: [...]}.
These diagnostics measure retrieval influence, not factual confidence or SHAP.
"""
import argparse
import json
from pathlib import Path
import time
from core.knowledge_retrieval import KnowledgeIndex


def evaluate(index, cases):
    rows = []
    for case in cases:
        started = time.perf_counter()
        results = index.search(case['query'])
        names = [name for name, _ in results]
        expected = set(case.get('expected_sources', []))
        excluded = set(case.get('excluded_sources', []))
        rows.append({'query': case['query'], 'sources': names,
                     'passed': expected.issubset(names) and not excluded.intersection(names),
                     'latency_ms': round((time.perf_counter()-started)*1000, 2)})
    return {'passed': sum(row['passed'] for row in rows), 'total': len(rows), 'cases': rows}


def source_removal_diagnostics(index, query):
    """Remove each selected source in a temporary index; never mutate saved files."""
    baseline = index.search(query)
    diagnostics = []
    for name in dict.fromkeys(name for name, _ in baseline):
        temporary = KnowledgeIndex(index.root)
        temporary.files = {key: value for key, value in index.files.items() if key != name}
        temporary.refresh = lambda: None
        temporary.embedding_model = index.embedding_model
        temporary.vectors = dict(index.vectors)
        alternatives = temporary.search(query)
        diagnostics.append({'removed_source': name, 'remaining_sources': [key for key, _ in alternatives]})
    return {'baseline_sources': [name for name, _ in baseline], 'removals': diagnostics,
            'meaning': 'Retrieval sensitivity only; does not verify claims or explain model internals.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases', type=Path)
    parser.add_argument('--knowledge-root', type=Path, default=Path('knowledge_base'))
    args = parser.parse_args()
    result = evaluate(KnowledgeIndex(args.knowledge_root), json.loads(args.cases.read_text()))
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] == result['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
