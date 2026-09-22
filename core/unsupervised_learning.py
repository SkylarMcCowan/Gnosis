"""Bounded, drainable research with private staging and atomic publication."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import threading
import time
import uuid

from core.autonomous_research import local_chat, public_query, record_gap, run_research, search_endpoint, search_public
from core.knowledge_maintenance import atomic_json

_topic_lock = threading.Lock()
_progress = threading.local()

# More candidates than the 100-question recent-history window, so a model
# stuck repeating old questions cannot permanently starve research waves.
_FALLBACK_SUBJECTS = (
    'coral bleaching', 'ocean acidification', 'deep ocean circulation',
    'hydrothermal vent ecosystems', 'kelp forest recovery', 'tidal mixing',
    'seed dormancy', 'plant gravitropism', 'mycorrhizal nutrient exchange',
    'stomatal regulation', 'xylem water transport', 'plant cold tolerance',
    'volcanic ash dispersal', 'plate subduction', 'glacial erosion',
    'river delta formation', 'mineral crystallization', 'soil carbon storage',
    'bird migration', 'bat echolocation', 'ant navigation',
    'bee communication', 'cephalopod camouflage', 'whale vocal learning',
    'stellar nucleosynthesis', 'planetary ring formation', 'solar magnetic cycles',
    'exoplanet atmosphere escape', 'pulsar timing', 'galactic rotation',
    'metal fatigue', 'ceramic fracture', 'polymer degradation',
    'semiconductor charge transport', 'superconducting phase transitions', 'glass formation',
)
_FALLBACK_TEMPLATES = (
    'What physical mechanisms explain {subject}?',
    'How do researchers measure {subject}?',
    'What environmental conditions affect {subject}?',
)


def report_progress(message):
    callback = getattr(_progress, 'callback', None)
    if callback:
        callback(message)



def select_topic(chat, recent):
    """Give deterministic local models varied prompts and actionable rejection feedback."""
    import random
    from core.autonomous_research import PRIVATE
    from core.knowledge_retrieval import terms
    domains = ['geology', 'oceanography', 'linguistics', 'ancient technology',
               'ecology', 'astronomy', 'materials science', 'music history',
               'mathematics', 'botany', 'archaeology', 'animal behavior']
    random.SystemRandom().shuffle(domains)
    seen = {' '.join(terms(question)) for question in recent}
    attempts = []
    repeated = False
    for domain in domains[:3]:
        report_progress(f'Selecting topic: {domain} (attempt {len(attempts) + 1}/3)')
        prompt = ('Choose one narrow public research question, preferably about ' + domain + '. '
                  'Use 6–18 words, at most 180 characters. Ask one question, not multiple parts. '
                  'Avoid personal details, URLs, credentials and private information. '
                  'Select a different subject from these previous questions: ' + repr(recent[-100:]) +
                  '\nReturn JSON {"query":"one specific public question"}.')
        if attempts:
            prompt += '\nPrevious attempts were rejected: ' + repr(attempts) + '. Fix these problems.'
        try:
            plan = chat(prompt)
            query = plan.get('query') if isinstance(plan, dict) else None
            if isinstance(query, str):
                query = ' '.join(query.split())
            if not isinstance(query, str) or not query:
                reason = 'Missing nonempty query string in JSON response'
            elif PRIVATE.search(query):
                reason = 'Query contains potentially private information or a URL'
            elif not public_query(query):
                reason = 'Query must contain 3–24 meaningful words and at most 220 characters'
            elif ' '.join(terms(query)) in seen:
                reason = 'Query repeats an already selected topic'
                repeated = True
            else:
                return query
        except Exception as error:
            reason = f'Topic model request failed ({type(error).__name__})'
        report_progress('Topic rejected: ' + reason)
        attempts.append(reason)
    if repeated:
        candidates = [template.format(subject=subject)
                      for subject in _FALLBACK_SUBJECTS for template in _FALLBACK_TEMPLATES]
        random.SystemRandom().shuffle(candidates)
        for query in candidates:
            if public_query(query) and ' '.join(terms(query)) not in seen:
                report_progress('Using fallback topic after repeated model selections: ' + query)
                return query
    raise ValueError('Topic selection failed after 3 attempts: ' + '; '.join(attempts))


def run_task(root, chat=None, search=None, defer_cleanup=False):
    root, chat = Path(root), chat or local_chat
    task_id = uuid.uuid4().hex
    stage = root / 'knowledge_state/learning_tasks' / task_id
    # Reserve topics before research so concurrent workers pursue different questions.
    from core.autonomous_research import queue_store
    with _topic_lock, queue_store(root / 'knowledge_state/curiosity') as state:
        recent = [g['question'] for g in state['gaps'].values()][-100:]
        query = select_topic(chat, recent)
        report_progress('Topic selected: ' + query)
        state['gaps'] = dict(list(state['gaps'].items())[-199:])
        state['gaps'][task_id] = {'question': query, 'status': 'learning', 'id': task_id,
                                 'occurrences': 1, 'created_at': task_id, 'attempts': 3, 'reasons': []}
    atomic_json(stage / 'knowledge_state/research_settings.json', {
        'enabled': True, 'allow_external_search': True,
        'approved_search_endpoint': search_endpoint(), 'topics_per_night': 1})
    record_gap(stage, query, 'curiosity')
    report_progress('Researching: ' + query)
    result = run_research(stage, chat=chat, search=search or wikipedia_first_search, batch_size=1)
    report_progress(f"Research finished: {query} — {result.get('saved_sources', 0)} sources, {result.get('saved_answers', 0)} answers")
    kb = stage / 'knowledge_base'
    kb.mkdir(exist_ok=True)
    report = {'task': task_id, 'question': query, 'research': result, 'staging': str(kb)}
    atomic_json(stage / 'report.json', report)
    if not defer_cleanup:
        report.update(finish_wave(root, task_id, [report]))
    return report


def scrape_page(url):
    """Bounded page download and main-text extraction; never saves navigation HTML."""
    import requests
    import trafilatura
    with requests.get(url, timeout=(5, 15), stream=True,
                      headers={'User-Agent': 'GnosisResearch/1.0'}) as response:
        response.raise_for_status()
        if 'html' not in response.headers.get('Content-Type', '').lower():
            return ''
        chunks, size = [], 0
        deadline = time.monotonic() + 30
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 2_000_000 or time.monotonic() > deadline:
                return ''
            chunks.append(chunk)
        text = trafilatura.extract(b''.join(chunks), include_comments=False, include_tables=False) or ''
        return text[:12000]


def wikipedia_first_search(query, search=search_public, fetch=scrape_page):
    from urllib.parse import urlsplit
    candidates = []
    for request in ('site:en.wikipedia.org ' + query, query):
        report_progress('Searching: ' + request)
        try:
            candidates.extend(search(request))
        except Exception as error:
            report_progress(f'Search failed: {type(error).__name__}')
            continue
    def wikipedia(row):
        host = (urlsplit(row.get('url', '')).hostname or '').lower()
        return host == 'wikipedia.org' or host.endswith('.wikipedia.org')
    candidates.sort(key=lambda row: not wikipedia(row))
    results, seen = [], set()
    for row in candidates[:10]:
        url = row.get('url', '')
        if url in seen or urlsplit(url).scheme not in ('http', 'https'):
            continue
        seen.add(url)
        report_progress('Scraping: ' + url)
        try:
            content = fetch(url)
        except Exception as error:
            report_progress(f'Scrape failed: {url} ({type(error).__name__})')
            continue
        if not content or len(content.strip()) < 100:
            continue
        report_progress(f'Extracted {len(content)} characters: {url}')
        results.append({**row, 'content': content, 'evidence_kind': 'page_extract'})
        if len(results) == 4:
            break
    return results


def finish_wave(root, wave_id, reports):
    """Only called after all tasks settle; normalize one isolated wave, then publish."""
    import shutil
    from webagent import historian
    root = Path(root)
    stage = root / 'knowledge_state/learning_waves' / wave_id
    kb = stage / 'knowledge_base'
    kb.mkdir(parents=True, exist_ok=True)
    for report in reports:
        if 'staging' not in report:
            continue
        source = Path(report['staging'])
        for path in source.rglob('*'):
            if path.is_file():
                relative = path.relative_to(source)
                destination = kb / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Evidence filenames are content hashes; findings use topic hashes.
                shutil.copy2(path, destination)
    has_findings = any(path.is_file() for path in kb.rglob('*'))
    if not has_findings:
        result = {'wave': wave_id, 'historian': None, 'knowledge': None, 'tasks': reports}
        atomic_json(stage / 'report.json', result)
        return result
    cleanup = historian(knowledge_root=kb)
    destination = root / 'knowledge_base/unsupervised_learning' / wave_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(kb, destination)
    result = {'wave': wave_id, 'historian': cleanup, 'knowledge': str(destination), 'tasks': reports}
    atomic_json(stage / 'report.json', result)
    # Once published, discard redundant private staging to bound disk amplification.
    for report in reports:
        if 'staging' in report:
            task_dir = Path(report['staging']).parent
            if task_dir.parent == root / 'knowledge_state/learning_tasks':
                shutil.rmtree(task_dir)
    return result


class UnsupervisedLearning:
    """One wave at a time; toggle-off drains research and historian together."""
    def __init__(self, root, workers=4, task=run_task):
        self.root, self.workers, self.task = root, max(3, min(workers, 5)), task
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='gnosis-learning-wave')
        self.enabled = self.closed = False
        self.pending = set()
        self.recent = []
        self.retry_at = 0
        self.phase = 'idle'
        self.completed = 0
        self.wave_number = 0
        from collections import deque
        self.messages = deque(maxlen=1000)
        self.message_lock = threading.Lock()

    def emit(self, message):
        with self.message_lock:
            self.messages.append(time.strftime('%H:%M:%S') + '  ' + message)

    def drain_messages(self):
        with self.message_lock:
            messages = list(self.messages)
            self.messages.clear()
        return messages

    def set_enabled(self, enabled):
        self.enabled = bool(enabled) and not self.closed
        self.tick()

    def _execute_task(self, number):
        from core.background import background_work
        with background_work():
            _progress.callback = lambda message: self.emit(f'[Task {number}] {message}')
            try:
                return self.task(self.root, defer_cleanup=True)
            finally:
                del _progress.callback

    def _execute(self):
        from concurrent.futures import as_completed
        from core.background import background_work
        reports = []
        with ThreadPoolExecutor(max_workers=self.workers) as tasks:
            futures = [tasks.submit(self._execute_task, number + 1) for number in range(self.workers)]
            for future in as_completed(futures):
                try:
                    reports.append(future.result())
                except Exception as error:
                    self.emit('Task failed: ' + str(error))
                    reports.append({'error': str(error)})
                self.completed = len(reports)
        self.phase = 'normalizing'
        self.emit('Research tasks finished; preparing historian cleanup.')
        with background_work():
            return finish_wave(self.root, uuid.uuid4().hex, reports)

    def tick(self):
        for future in list(self.pending):
            if not future.done():
                continue
            self.pending.remove(future)
            try:
                result = future.result()
                if any(r.get('error') or r.get('research', {}).get('errors') or
                       not r.get('research', {}).get('saved_sources') for r in result['tasks']):
                    self.retry_at = time.monotonic() + 15
                self.recent.append(result)
                self.emit(self.output_text(waves=[result]))
            except Exception as error:
                self.recent.append({'error': str(error)})
                self.emit('Wave failed: ' + str(error))
                self.retry_at = time.monotonic() + 15
            self.recent = self.recent[-10:]
            self.phase = 'idle'
        if self.enabled and not self.pending and time.monotonic() >= self.retry_at:
            self.phase, self.completed = 'researching', 0
            self.wave_number += 1
            self.emit(f'Starting research wave {self.wave_number}')
            self.pending.add(self.pool.submit(self._execute))

    def status_text(self):
        if self.pending:
            suffix = ' · stopping after this wave' if not self.enabled else ''
            return f'Wave {self.wave_number}: {self.phase} · {self.completed}/{self.workers} tasks complete{suffix}'
        if self.enabled:
            import math
            remaining = max(0, math.ceil(self.retry_at - time.monotonic()))
            return (f'Wave {self.wave_number + 1} starts in {remaining}s · cooldown after incomplete research'
                    if remaining else f'Starting wave {self.wave_number + 1}…')
        return 'Learning is off'

    def output_text(self, waves=None):
        lines = []
        for wave in self.recent if waves is None else waves:
            if wave.get('error'):
                lines.append('Wave failed: ' + wave['error'])
                continue
            lines.append('Completed research wave')
            for task in wave['tasks']:
                if task.get('error'):
                    lines.append('  Task failed: ' + task['error'])
                    continue
                research = task['research']
                lines.append(f"  {task.get('question', 'Research task')} — {research.get('saved_sources', 0)} sources, {research.get('saved_answers', 0)} answers saved")
                for topic in research.get('topics', []):
                    diagnostic = topic.get('answer', {})
                    status = diagnostic.get('status')
                    if status == 'repaired':
                        lines.append('    Answer saved after one repair attempt.')
                    elif status in ('not_saved', 'not_attempted'):
                        lines.append('    Answer not saved: ' + diagnostic.get('reason', 'No usable answer.'))
                        if research.get('saved_sources'):
                            lines.append('    Scraped sources were retained in the knowledge base.')
                for error in research.get('errors', []):
                    lines.append('    ' + str(error.get('error', error)))
            if wave.get('knowledge'):
                lines.append('Historian finished; findings saved to the knowledge base.\n')
            else:
                lines.append('No findings collected; historian and publication skipped.\n')
        return '\n'.join(lines)

    def shutdown(self):
        self.enabled = False
        self.closed = True
        self.pool.shutdown(wait=False)
