"""Incremental, local passage retrieval. Scores describe relevance, never truth."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time

STOP = set('a an the is are was were of in on to for and or it this that what how does do tell me about please explain describe show know understand many s'.split())
ALIASES = {'america': 'usa', 'american': 'usa', 'us': 'usa',
           'residents': 'population', 'inhabitants': 'population',
           'fixtures': 'schedule', 'matches': 'schedule', 'manu': 'manchester',
           'earnings': 'income', 'wages': 'salary'}


def terms(text):
    normalized = re.sub(r'\bunited states(?: of america)?\b', 'usa', text.lower())
    normalized = re.sub(r'\bu\.s\.(?:a\.)?', 'usa', normalized)
    normalized = re.sub(r'\bhow many people\b', 'population', normalized)
    words = re.findall(r'[a-z0-9]+', normalized)
    return [ALIASES.get(w, w) for w in words if w not in STOP]


def supports_population_count(text, wanted):
    """A conservative fact-type gate, not a general factual verifier."""
    count = r"\b(?:\d+(?:[,.]\d+)*\s*(?:million|billion|people|residents|inhabitants)\b|\d{5,}\b|\d{1,3}(?:,\d{3})+\b)"
    population = r"\b(?:population|residents|inhabitants)\b"
    if 'usa' in wanted:
        country = r"\b(?:usa|america|u\.s\.(?:a\.)?|us|united states(?: of america)?)(?![a-z])"
        anchor = rf"(?:{country}[^.!?\n]{{0,45}}{population}|{population}[^.!?\n]{{0,45}}{country})"
    else:
        anchor = population
    for match in re.finditer(anchor, text, re.I):
        tail = re.split(r"[.!?]\s|\n", text[match.end():match.end()+160], maxsplit=1)[0]
        window = text[match.start():match.end()] + tail
        if re.search(count, window, re.I):
            return True
    return False


class Passage(str):
    """String-compatible result carrying provenance through legacy tools."""
    def __new__(cls, text, metadata):
        obj = super().__new__(cls, text)
        obj.metadata = metadata
        return obj


class KnowledgeIndex:
    def __init__(self, root):
        self.root = Path(root)
        self.files = {}
        self.lock = threading.RLock()
        self.vectors = {}
        self.embedding_model = embedding_model(self.root.parent)
        self.embedding_error = None
        from core.knowledge_maintenance import read_json
        self.cache_path = self.root.parent / 'knowledge_state' / 'passages.json'
        cached = read_json(self.cache_path, {})
        try:
            if cached.get('version') == 2 and cached.get('root') == str(self.root.resolve()):
                self.files = {name: (tuple(signature), [(text, meta, Counter(counts)) for text, meta, counts in rows])
                              for name, (signature, rows) in cached['files'].items()}
        except (AttributeError, KeyError, TypeError, ValueError):
            self.files = {}
        catalog_path = self.root.parent / 'knowledge_state' / 'catalog.json'
        catalog = read_json(catalog_path, {})
        self.catalog = catalog.get('documents', {}) if isinstance(catalog, dict) else {}
        try:
            self.catalog_signature = catalog_path.stat().st_mtime_ns
        except OSError:
            self.catalog_signature = None
        if not isinstance(cached, dict) or cached.get('catalog_signature') != self.catalog_signature:
            self.files.clear()
        if isinstance(cached, dict) and cached.get('embedding_model') == self.embedding_model:
            self.vectors = cached.get('vectors', {})

    def save(self):
        from core.knowledge_maintenance import atomic_json
        atomic_json(self.cache_path, {'version': 2, 'root': str(self.root.resolve()), 'files': self.files,
                                     'catalog_signature': self.catalog_signature,
                                     'embedding_model': self.embedding_model, 'vectors': self.vectors})

    def _read(self, path, stat):
        from core.knowledge_maintenance import read_source
        raw, source_metadata = read_source(path)
        metadata = {'origin': 'saved-note', 'verification_status': 'unverified',
                    'captured_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    'date_basis': 'file-modified'}
        text = raw
        if path.suffix.lower() == '.json':
            data = source_metadata
            if not isinstance(data, dict) or not isinstance(data.get('content'), str):
                return []  # Conversation containers are not independent factual sources.
            text = data['content']
            metadata.update({k: data[k] for k in ('url', 'title', 'captured_at', 'published_at', 'verification_status') if data.get(k)})
            metadata['origin'] = 'saved-web' if str(data.get('url', '')).startswith(('http://', 'https://')) else 'saved-conversation'
            if data.get('origin') == 'derived-learning':
                metadata.update(origin='derived-learning', verification_status='unverified',
                                source_path=data.get('source_path'), source_hash=data.get('source_hash'))
            metadata['date_basis'] = 'capture' if data.get('captured_at') else 'file-modified'
        if any(w in path.as_posix().lower() for w in ('conversation', 'memory')):
            metadata['origin'] = 'saved-conversation'
        metadata.update({k: self.catalog.get(path.relative_to(self.root).as_posix(), {}).get(k)
                         for k in ('topics', 'keywords', 'summary')})
        chunks = []
        # Overlap preserves facts that cross passage boundaries; search the entire document.
        for offset in range(0, len(text), 1400):
            passage = text[offset:offset + 1800].strip()
            if passage:
                counts = Counter(terms(passage))
                counts.update(terms(' '.join(metadata.get('topics') or [])))
                chunks.append((passage, {**metadata, 'offset': offset}, counts))
        return chunks

    def refresh(self):
        from core.knowledge_maintenance import read_json, source_paths
        catalog_path = self.root.parent / 'knowledge_state' / 'catalog.json'
        try:
            catalog_signature = catalog_path.stat().st_mtime_ns
        except OSError:
            catalog_signature = None
        if catalog_signature != self.catalog_signature:
            catalog = read_json(catalog_path, {})
            self.catalog = catalog.get('documents', {}) if isinstance(catalog, dict) else {}
            self.catalog_signature = catalog_signature
            # Metadata changes must be visible in existing long-lived GUI sessions.
            self.files.clear()
        seen = set()
        for path in source_paths(self.root):
            name = path.relative_to(self.root).as_posix()
            seen.add(name)
            try:
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                if name.startswith('learned_notes/'):
                    data = read_json(path, {})
                    source = (self.root / str(data.get('source_path', ''))).resolve()
                    if (not source.is_relative_to(self.root.resolve()) or not source.is_file()
                            or hashlib.sha256(source.read_bytes()).hexdigest() != data.get('source_hash')):
                        self.files.pop(name, None)
                        continue
                if name not in self.files or self.files[name][0] != signature:
                    self.files[name] = (signature, self._read(path, stat))
            except (OSError, UnicodeError, ValueError):
                self.files.pop(name, None)
        for name in set(self.files) - seen:
            del self.files[name]

    def _semantic_scores(self, query, passages):
        """Use an explicitly configured, already-installed Ollama model.

        Never pull models or call a cloud provider. Failed embeddings fall back
        to keyword search. Cache vectors by content hash, pruning removed text.
        """
        if not self.embedding_model or not passages:
            return {}
        keys = [hashlib.sha256(text.encode()).hexdigest() for _, text, _, _ in passages]
        active = set(keys)
        self.vectors = {key: value for key, value in self.vectors.items() if key in active}
        missing = {key: row[1] for key, row in zip(keys, passages) if key not in self.vectors}
        try:
            import ollama
            client = ollama.Client(host="http://127.0.0.1:11434", timeout=3)
            from core.background import model_slot
            from core.models import _check_cancelled
            def embed(value):
                with model_slot(check=_check_cancelled):
                    return client.embed(model=self.embedding_model, input=value).embeddings
            # A missing model is an error, never a download trigger.
            deadline = time.monotonic() + 6
            for offset in range(0, len(missing), 32):
                if time.monotonic() > deadline:
                    raise TimeoutError("Embedding indexing budget reached")
                batch = list(missing.items())[offset:offset + 32]
                vectors = embed([text for _, text in batch])
                if len(vectors) != len(batch):
                    raise ValueError("Incomplete embedding batch")
                self.vectors.update((key, vector) for (key, _), vector in zip(batch, vectors))
            if time.monotonic() > deadline:
                raise TimeoutError("Embedding indexing budget reached")
            q = embed(query)[0]
            norm = math.sqrt(sum(v*v for v in q))
            scores = {}
            for key in active:
                v = self.vectors[key]
                if len(v) != len(q):
                    raise ValueError("Embedding dimensions changed")
                denominator = norm * math.sqrt(sum(x*x for x in v))
                scores[key] = sum(a*b for a, b in zip(q, v))/denominator if denominator else 0
            self.embedding_error = None
            return scores
        except Exception as error:
            self.embedding_error = type(error).__name__
            return {}

    def search(self, query, limit=8):
        with self.lock:
            self.refresh()
            wanted = set(terms(query))
            if not wanted:
                return []
            passages = [(name, *entry) for name, (_, entries) in self.files.items() for entry in entries]
            frequency = Counter(t for _, _, _, counts in passages for t in counts)
            semantic = self._semantic_scores(query, passages)
            ranked = []
            for name, text, meta, counts in passages:
                matched = wanted & counts.keys()
                coverage = len(matched) / len(wanted)
                # Require the actual requested statistic, not just a country mention.
                if 'population' in wanted:
                    if meta['origin'] in ('saved-conversation', 'derived-learning') or not supports_population_count(text, wanted):
                        continue
                similarity = semantic.get(hashlib.sha256(text.encode()).hexdigest(), 0)
                if "usa" in wanted and "usa" not in counts:
                    continue
                if coverage < .6 and similarity < .65:
                    continue
                score = sum((1 + math.log(counts[t])) * math.log(1 + len(passages)/(1 + frequency[t])) for t in matched)
                score /= math.sqrt(max(len(counts), 1))
                score += max(similarity, 0)
                ranked.append((score, name, text, {**meta, 'semantic_similarity': round(similarity, 4) if semantic else None, 'embedding_status': self.embedding_error or ('enabled' if semantic else 'not configured'), 'matched_terms': sorted(matched), 'coverage': round(coverage, 3), 'retrieval_score': round(score, 4), 'retrieval_method': 'keywords + local Ollama embeddings' if semantic else 'keyword + local concept aliases'}))
            origins = {"saved-web": 0, "saved-note": 1, "saved-conversation": 2}
            ranked.sort(key=lambda row: (-row[0], origins.get(row[3]["origin"], 1), row[1]))
            results, hashes = [], set()
            for _, name, text, meta in ranked:
                sentences = list(re.finditer(r"[^.!?\n]+(?:[.!?]|\n|$)", text))
                if sentences:
                    best = max(range(len(sentences)), key=lambda i: len(wanted & set(terms(sentences[i].group()))))
                    if len(wanted & set(terms(sentences[best].group()))):
                        start = sentences[max(0, best - 1)].start()
                        end = sentences[min(best + 1, len(sentences)-1)].end()
                        text = text[start:end].strip()
                        meta = {**meta, 'offset': meta['offset'] + start}
                fingerprint = hashlib.sha256(' '.join(text.split()).encode()).hexdigest()
                if fingerprint in hashes:
                    continue
                hashes.add(fingerprint)
                results.append((name, Passage(text, meta)))
                if len(results) >= limit:
                    break
            return results


def embedding_model(project_root):
    override = os.environ.get("GNOSIS_EMBEDDING_MODEL")
    if override is not None:
        return override.strip()
    try:
        data = json.loads((Path(project_root)/"knowledge_settings.json").read_text())
        return str(data.get("embedding_model") or "").strip()
    except (OSError, ValueError, AttributeError):
        return ""


def save_embedding_model(project_root, model):
    path = Path(project_root)/"knowledge_settings.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"embedding_model": model.strip()}, indent=2))
    temporary.replace(path)


_indexes = {}
_index_lock = threading.Lock()


def search(root, query):
    key = str(Path(root).resolve())
    with _index_lock:
        index = _indexes.setdefault(key, KnowledgeIndex(key))
    configured = embedding_model(Path(key).parent)
    with index.lock:
        if configured != index.embedding_model:
            index.embedding_model = configured
            index.vectors.clear()
        return index.search(query)
