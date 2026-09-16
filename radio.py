"""Radio pane: a full-featured audio hub, not just an internet-radio finder.

Three tabs sharing one player and one audio-reactive spectrum visualizer:
- Live Radio: search Radio-Browser's free directory or paste a stream URL,
  same backend the Weather Station pane's compact Radio tab uses (station
  bookmarks live in one shared store, so adding a station here or there
  shows up in both places). Moved out of weather_station.py so it has room
  to be a real radio, not a cramped tab.
- Music & Audiobooks: point it at your own files/folders (paths are
  recorded, not copied) and play them back with seek + volume. Audiobooks
  remember playback position across sessions; music doesn't need to.
- Soundscapes: a handful of ambient loops synthesized locally at first use
  and cached to disk - no internet fetch, no bundled audio, no licensing
  question - plus room to add your own looping audio file (white noise,
  rain, etc. you already have).

The visualizer taps real decoded PCM via QAudioBufferOutput (Qt 6.8+'s
replacement for the old QAudioProbe), so it reacts to whatever is actually
playing - live stream, local file, or generated loop - rather than faking
motion. FFT is a small pure-Python radix-2 implementation; no numpy
dependency for a widget this size.
"""
import array
import cmath
import json
import math
import os
import random
import struct
import uuid
import wave

import requests
from PyQt6.QtCore import QRectF, QThread, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtMultimedia import (
    QAudioBufferOutput,
    QAudioFormat,
    QAudioOutput,
    QMediaDevices,
    QMediaPlayer,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from core import config as core_config
from core.models import MODELS, chat as model_chat
from tv import TVWidget

_RADIO_BROWSER_HEADERS = {"User-Agent": "GnosisRadio/1.0 (personal desktop app)"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".m4b", ".wav", ".flac", ".ogg", ".aac", ".wma"}


# ----------------------------------------------------------------------
# Live radio backend - unchanged behavior/storage from when this lived in
# weather_station.py, so existing saved stations keep working untouched.
# ----------------------------------------------------------------------
def search_radio_stations(query, limit=15):
    """Search Radio-Browser's community station directory by name. Returns
    a list of {name, stream_url, country, state, tags, bitrate} (only
    stations with a usable stream URL), or None on failure. Empty query
    returns None rather than an unfiltered dump of the whole directory."""
    query = (query or "").strip()
    if not query:
        return None
    try:
        response = requests.get(
            "https://all.api.radio-browser.info/json/stations/search",
            params={"name": query, "limit": limit, "hidebroken": "true", "order": "clickcount", "reverse": "true"},
            headers=_RADIO_BROWSER_HEADERS, timeout=10,
        )
        response.raise_for_status()
        results = []
        for station in response.json():
            stream_url = station.get("url_resolved") or station.get("url") or ""
            if not stream_url:
                continue
            results.append({
                "name": station.get("name") or "Unknown station",
                "stream_url": stream_url,
                "country": station.get("country") or "",
                "state": station.get("state") or "",
                "tags": station.get("tags") or "",
                "bitrate": station.get("bitrate"),
            })
        return results
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


def _radio_stations_path():
    return os.path.join(core_config.path("weather_station"), "radio_stations.json")


def list_radio_stations():
    path = _radio_stations_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return records if isinstance(records, list) else []


def _save_radio_stations(records):
    path = _radio_stations_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


def add_radio_station(name, stream_url):
    name = (name or "").strip()
    stream_url = (stream_url or "").strip()
    if not name or not stream_url:
        raise ValueError("A radio station needs both a name and a stream URL.")
    records = list_radio_stations()
    if any(r["stream_url"] == stream_url for r in records):
        raise ValueError(f'"{name}" is already in your saved stations.')
    record = {"id": uuid.uuid4().hex[:8], "name": name, "stream_url": stream_url}
    records.append(record)
    _save_radio_stations(records)
    return record


def remove_radio_station(station_id):
    records = list_radio_stations()
    remaining = [r for r in records if r.get("id") != station_id]
    if len(remaining) == len(records):
        return False
    _save_radio_stations(remaining)
    return True


# ----------------------------------------------------------------------
# Music & audiobook library - just path references (files aren't copied),
# with a per-item playback position so audiobooks resume where they left
# off. Own store under radio/ rather than weather_station/, since none of
# this is weather-related.
# ----------------------------------------------------------------------
def _library_path():
    return os.path.join(core_config.path("radio"), "library.json")


def list_library_items():
    path = _library_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(records, list):
        return []
    for record in records:
        record.setdefault("book_id", None)
        record.setdefault("track_order", 0)
        record.setdefault("finished", False)
    return records


def _save_library_items(records):
    path = _library_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


def _iter_audio_files(paths):
    for raw_path in paths:
        if os.path.isdir(raw_path):
            for root, _dirs, files in os.walk(raw_path):
                for name in sorted(files):
                    if os.path.splitext(name)[1].lower() in AUDIO_EXTENSIONS:
                        yield os.path.join(root, name)
        elif os.path.isfile(raw_path) and os.path.splitext(raw_path)[1].lower() in AUDIO_EXTENSIONS:
            yield raw_path


def add_library_paths(paths, kind="music"):
    """Adds every audio file found under `paths` (files as-is, folders
    walked recursively) that isn't already in the library. Returns the
    list of newly-added records; duplicates (by absolute path) are
    silently skipped rather than erroring, since re-adding a folder you've
    already added is a normal thing to do."""
    records = list_library_items()
    existing_paths = {r["path"] for r in records}
    added = []
    for file_path in _iter_audio_files(paths):
        abs_path = os.path.abspath(file_path)
        if abs_path in existing_paths:
            continue
        record = {
            "id": uuid.uuid4().hex[:8],
            "path": abs_path,
            "title": os.path.splitext(os.path.basename(abs_path))[0],
            "kind": kind,
            "position_ms": 0,
            "book_id": None,
            "track_order": 0,
        }
        records.append(record)
        existing_paths.add(abs_path)
        added.append(record)
    if added:
        _save_library_items(records)
    return added


def remove_library_item(item_id):
    records = list_library_items()
    remaining = [r for r in records if r.get("id") != item_id]
    if len(remaining) == len(records):
        return False
    _save_library_items(remaining)
    return True


def update_library_position(item_id, position_ms):
    records = list_library_items()
    for record in records:
        if record.get("id") == item_id:
            record["position_ms"] = max(0, int(position_ms))
            record["finished"] = False
            _save_library_items(records)
            return True
    return False


def set_library_finished(item_id, finished):
    """Marks a library item as listened/unlistened, either automatically
    (a chapter played to its end) or manually from the UI to correct a
    desync between stored progress and what was actually heard. Resets
    position_ms to 0 either way, since a finished item should restart from
    the beginning rather than resuming a second before the end, and an
    unlistened one should start over too."""
    records = list_library_items()
    for record in records:
        if record.get("id") == item_id:
            record["finished"] = bool(finished)
            record["position_ms"] = 0
            _save_library_items(records)
            return True
    return False


def set_book_listened(book_id, listened):
    """Manually marks every chapter of a book as listened/unlistened, and
    updates its last-played chapter so the Resume button and progress
    summary agree with the new state."""
    files = list_book_files(book_id)
    for record in files:
        set_library_finished(record["id"], listened)
    set_book_last_played(book_id, files[-1]["id"] if (listened and files) else None)
    return bool(files)


def assign_files_to_book(file_ids, book_id):
    """Assigns each file in `file_ids` (in the order given) to `book_id`,
    numbering track_order sequentially after whatever's already assigned to
    that book - so re-running this to add more chapters later doesn't
    disturb the ones already there."""
    records = list_library_items()
    by_id = {r["id"]: r for r in records}
    existing_orders = [r.get("track_order") or 0 for r in records if r.get("book_id") == book_id]
    next_order = (max(existing_orders) + 1) if existing_orders else 0
    changed = False
    for file_id in file_ids:
        record = by_id.get(file_id)
        if record is None:
            continue
        record["book_id"] = book_id
        record["track_order"] = next_order
        next_order += 1
        changed = True
    if changed:
        _save_library_items(records)
    return changed


def unassign_file(file_id):
    records = list_library_items()
    for record in records:
        if record.get("id") == file_id:
            record["book_id"] = None
            record["track_order"] = 0
            _save_library_items(records)
            return True
    return False


def list_book_files(book_id):
    return sorted(
        (r for r in list_library_items() if r.get("book_id") == book_id),
        key=lambda r: r.get("track_order") or 0,
    )


def book_progress_summary(book_id):
    """Returns {"total", "current_index", "current_title", "position_ms",
    "status"} where status is "empty" (no chapters), "not_started",
    "in_progress", or "missing" (the book's last-played chapter was removed
    from the library - surfaced explicitly rather than silently resuming a
    different chapter)."""
    files = list_book_files(book_id)
    if not files:
        return {"total": 0, "current_index": None, "current_title": None, "position_ms": 0, "status": "empty"}
    if all(f.get("finished") for f in files):
        return {
            "total": len(files), "current_index": len(files), "current_title": files[-1]["title"],
            "position_ms": 0, "status": "finished",
        }
    book = next((b for b in list_books() if b["id"] == book_id), None)
    last_file_id = book.get("last_played_file_id") if book else None
    if not last_file_id:
        return {"total": len(files), "current_index": None, "current_title": None, "position_ms": 0, "status": "not_started"}
    for index, record in enumerate(files):
        if record["id"] == last_file_id:
            return {
                "total": len(files), "current_index": index + 1, "current_title": record["title"],
                "position_ms": record.get("position_ms") or 0, "status": "in_progress",
            }
    return {"total": len(files), "current_index": None, "current_title": None, "position_ms": 0, "status": "missing"}


# ----------------------------------------------------------------------
# Authors / Series / Books - the catalog the user builds on top of the raw
# library files above, so audiobooks can be browsed as books instead of a
# flat dump of chapter files. Own store (radio/catalog.json) rather than
# folding into library.json, since these are user-authored groupings, not
# discovered files.
# ----------------------------------------------------------------------
def _catalog_path():
    return os.path.join(core_config.path("radio"), "catalog.json")


def _load_catalog():
    path = _catalog_path()
    default = {"authors": [], "series": [], "books": []}
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return default
    if not isinstance(data, dict):
        return default
    return {key: data.get(key) if isinstance(data.get(key), list) else [] for key in default}


def _save_catalog(data):
    path = _catalog_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def list_authors():
    return _load_catalog()["authors"]


def add_author(name):
    name = (name or "").strip()
    if not name:
        raise ValueError("An author needs a name.")
    catalog = _load_catalog()
    if any(a["name"].lower() == name.lower() for a in catalog["authors"]):
        raise ValueError(f'"{name}" is already in your authors.')
    record = {"id": uuid.uuid4().hex[:8], "name": name}
    catalog["authors"].append(record)
    _save_catalog(catalog)
    return record


def remove_author(author_id):
    catalog = _load_catalog()
    if any(b.get("author_id") == author_id for b in catalog["books"]):
        raise ValueError("This author still has books - reassign or remove those first.")
    remaining = [a for a in catalog["authors"] if a["id"] != author_id]
    if len(remaining) == len(catalog["authors"]):
        return False
    catalog["authors"] = remaining
    _save_catalog(catalog)
    return True


def list_series():
    return _load_catalog()["series"]


def add_series(name, author_id, synopsis=""):
    name = (name or "").strip()
    if not name:
        raise ValueError("A series needs a name.")
    if not author_id:
        raise ValueError("A series needs an author.")
    catalog = _load_catalog()
    record = {
        "id": uuid.uuid4().hex[:8], "name": name, "author_id": author_id,
        "synopsis": (synopsis or "").strip(), "last_played_book_id": None,
    }
    catalog["series"].append(record)
    _save_catalog(catalog)
    return record


def update_series(series_id, **fields):
    catalog = _load_catalog()
    for record in catalog["series"]:
        if record["id"] != series_id:
            continue
        if "name" in fields:
            name = (fields["name"] or "").strip()
            if not name:
                raise ValueError("A series needs a name.")
            record["name"] = name
        if "author_id" in fields:
            if not fields["author_id"]:
                raise ValueError("A series needs an author.")
            record["author_id"] = fields["author_id"]
        if "synopsis" in fields:
            record["synopsis"] = (fields["synopsis"] or "").strip()
        _save_catalog(catalog)
        return record
    raise ValueError("Series not found.")


def remove_series(series_id):
    catalog = _load_catalog()
    remaining = [s for s in catalog["series"] if s["id"] != series_id]
    if len(remaining) == len(catalog["series"]):
        return False
    catalog["series"] = remaining
    for book in catalog["books"]:
        if book.get("series_id") == series_id:
            book["series_id"] = None
            book["series_index"] = None
    _save_catalog(catalog)
    return True


def set_series_last_played(series_id, book_id):
    catalog = _load_catalog()
    for record in catalog["series"]:
        if record["id"] == series_id:
            record["last_played_book_id"] = book_id
            _save_catalog(catalog)
            return True
    return False


def list_books():
    return _load_catalog()["books"]


def add_book(title, author_id, series_id=None, series_index=None, synopsis=""):
    title = (title or "").strip()
    if not title:
        raise ValueError("A book needs a title.")
    if not author_id:
        raise ValueError("A book needs an author.")
    catalog = _load_catalog()
    record = {
        "id": uuid.uuid4().hex[:8], "title": title, "author_id": author_id,
        "series_id": series_id, "series_index": series_index,
        "synopsis": (synopsis or "").strip(), "last_played_file_id": None,
    }
    catalog["books"].append(record)
    _save_catalog(catalog)
    return record


def update_book(book_id, **fields):
    catalog = _load_catalog()
    for record in catalog["books"]:
        if record["id"] != book_id:
            continue
        if "title" in fields:
            title = (fields["title"] or "").strip()
            if not title:
                raise ValueError("A book needs a title.")
            record["title"] = title
        if "author_id" in fields:
            record["author_id"] = fields["author_id"]
        if "series_id" in fields:
            record["series_id"] = fields["series_id"]
        if "series_index" in fields:
            record["series_index"] = fields["series_index"]
        if "synopsis" in fields:
            record["synopsis"] = (fields["synopsis"] or "").strip()
        _save_catalog(catalog)
        return record
    raise ValueError("Book not found.")


def remove_book(book_id):
    catalog = _load_catalog()
    remaining = [b for b in catalog["books"] if b["id"] != book_id]
    if len(remaining) == len(catalog["books"]):
        return False
    catalog["books"] = remaining
    _save_catalog(catalog)
    records = list_library_items()
    changed = False
    for record in records:
        if record.get("book_id") == book_id:
            record["book_id"] = None
            record["track_order"] = 0
            changed = True
    if changed:
        _save_library_items(records)
    return True


def set_book_last_played(book_id, file_id):
    catalog = _load_catalog()
    for record in catalog["books"]:
        if record["id"] == book_id:
            record["last_played_file_id"] = file_id
            _save_catalog(catalog)
            return True
    return False


# ----------------------------------------------------------------------
# Book/series chat - "ask about this book/series" against local Ollama.
# One plain model_chat() call per turn (no MCP/tool loop, unlike Penpot
# Studio's agent - this feature never needs to mutate anything), with
# conversation history persisted so a discussion survives closing the
# dialog. Own store (radio/book_chats.json); no chat-transcript
# persistence convention exists elsewhere in the repo yet.
# ----------------------------------------------------------------------
_CHAT_MODEL = MODELS.get("main", "qwen3.5:4b")


def _chats_path():
    return os.path.join(core_config.path("radio"), "book_chats.json")


def _load_chats():
    path = _chats_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_chats(data):
    path = _chats_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_chat(scope, scope_id):
    return _load_chats().get(f"{scope}:{scope_id}", [])


def save_chat(scope, scope_id, conversation):
    data = _load_chats()
    data[f"{scope}:{scope_id}"] = conversation
    _save_chats(data)


def _build_topic_system_prompt(scope, title, author_name, series_name, synopsis):
    subject = f'the book "{title}"' if scope == "book" else f'the series "{title}"'
    lines = [
        "You are a knowledgeable, conversational assistant discussing "
        + subject + (f" by {author_name}" if author_name else "") + ".",
        "The user owns this and is asking to explore themes, characters, context, or fill "
        "gaps in their own knowledge - not asking for a plot summary of the obvious.",
        "If you're not confident about a specific detail, say so plainly instead of "
        "inventing one - a wrong guess is worse than admitting uncertainty here.",
    ]
    if series_name:
        lines.append(f'This is part of the series "{series_name}".')
    if synopsis:
        lines.append(f"Known synopsis/notes so far: {synopsis}")
    return "\n".join(lines)


def ask_about_topic(conversation, system_prompt, model=None):
    """conversation: list of {"role","content"} dicts ending with the
    newest user message already appended. Returns (reply_text,
    updated_conversation) - mirrors penpot_studio.run_agent_turn's shape,
    minus the tool-call loop this feature doesn't need."""
    working = [{"role": "system", "content": system_prompt}] + conversation
    response = model_chat(model=model or _CHAT_MODEL, messages=working)
    reply = response.get("message", {}).get("content", "") or "(no reply)"
    conversation.append({"role": "assistant", "content": reply})
    return reply, conversation


# ----------------------------------------------------------------------
# Soundscapes - built-in loops synthesized in pure Python (no numpy, no
# bundled audio files, no licensing question) and cached to disk on first
# play, plus a small store for the user's own looping audio files.
# ----------------------------------------------------------------------
_SOUNDSCAPE_SAMPLE_RATE = 22050
_SOUNDSCAPE_DURATION_S = 20
_SOUNDSCAPE_CROSSFADE_S = 1.5


def _white_noise_samples(n, amplitude, rng=None):
    rng = rng or random
    return [rng.uniform(-amplitude, amplitude) for _ in range(n)]


def _low_pass(samples, alpha):
    """One-pole low-pass filter; smaller alpha = smoother/darker noise."""
    out = [0.0] * len(samples)
    prev = 0.0
    for i, sample in enumerate(samples):
        prev += alpha * (sample - prev)
        out[i] = prev
    return out


def _normalize(samples, peak):
    largest = max((abs(s) for s in samples), default=0.0)
    if largest <= 1e-9:
        return samples
    scale = peak / largest
    return [s * scale for s in samples]


def _crossfade_loop(samples, sample_rate, fade_seconds):
    """Blends the tail into the head so the cached wav loops seamlessly
    instead of clicking at the seam."""
    fade_n = min(int(sample_rate * fade_seconds), len(samples) // 4)
    if fade_n <= 0:
        return samples
    head = samples[:fade_n]
    tail_start = len(samples) - fade_n
    for i in range(fade_n):
        t = i / fade_n
        samples[tail_start + i] = samples[tail_start + i] * (1 - t) + head[i] * t
    return samples


def _synth_white_noise(n, sr):
    return _white_noise_samples(n, amplitude=0.35)


def _synth_brown_noise(n, sr):
    rng = random.Random()
    out = []
    level = 0.0
    for _ in range(n):
        level += rng.uniform(-0.02, 0.02)
        level = max(-1.0, min(1.0, level * 0.999))
        out.append(level)
    return _normalize(out, 0.6)


def _synth_ocean_waves(n, sr):
    filtered = _low_pass(_white_noise_samples(n, amplitude=1.0), 0.02)
    out = []
    for i, sample in enumerate(filtered):
        swell = 0.5 + 0.5 * math.sin(2 * math.pi * (i / sr) / 6.0)
        out.append(sample * (0.3 + 0.7 * swell))
    return _normalize(out, 0.7)


def _synth_rain(n, sr):
    rng = random.Random()
    out = _low_pass(_white_noise_samples(n, amplitude=1.0), 0.35)
    drop_count = int(n / sr * 40)
    for _ in range(drop_count):
        start = rng.randrange(0, max(1, n - 200))
        drop_len = rng.randrange(20, 180)
        for j in range(drop_len):
            if start + j < n:
                out[start + j] += rng.uniform(-0.4, 0.4) * math.exp(-j / 30.0)
    return _normalize(out, 0.7)


def _synth_deep_space(n, sr):
    out = [0.0] * n
    for freq, amp in ((40, 0.5), (63, 0.3), (95, 0.2)):
        for i in range(n):
            out[i] += amp * math.sin(2 * math.pi * freq * i / sr)
    hiss = _low_pass(_white_noise_samples(n, amplitude=0.3), 0.01)
    for i in range(n):
        out[i] += hiss[i]
    return _normalize(out, 0.6)


BUILTIN_SOUNDSCAPES = (
    {"id": "white_noise", "name": "White Noise", "synth": _synth_white_noise,
     "description": "Flat, even hiss - good for masking sudden sounds."},
    {"id": "brown_noise", "name": "Brown Noise", "synth": _synth_brown_noise,
     "description": "Deeper, softer rumble than white noise."},
    {"id": "ocean_waves", "name": "Ocean Waves", "synth": _synth_ocean_waves,
     "description": "Filtered noise swelling like waves on a shore."},
    {"id": "rain", "name": "Rain", "synth": _synth_rain,
     "description": "Steady rain with scattered droplets."},
    {"id": "deep_space", "name": "Deep Space", "synth": _synth_deep_space,
     "description": "A low drone with a distant hiss - adrift in a station."},
)


def _soundscape_cache_dir():
    return os.path.join(core_config.path("radio"), "soundscape_cache")


def builtin_soundscape_cache_path(soundscape_id):
    return os.path.join(_soundscape_cache_dir(), f"{soundscape_id}.wav")


def _write_wav(path, samples, sample_rate):
    clipped = array.array("h", (int(max(-1.0, min(1.0, s)) * 32767) for s in samples))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(clipped.tobytes())


def generate_soundscape_wav(soundscape_id):
    """Returns the cached wav path for a built-in soundscape, synthesizing
    and caching it on first use so replays are instant. Raises KeyError
    for an unknown id."""
    preset = next((p for p in BUILTIN_SOUNDSCAPES if p["id"] == soundscape_id), None)
    if preset is None:
        raise KeyError(f"Unknown soundscape: {soundscape_id}")
    path = builtin_soundscape_cache_path(soundscape_id)
    if os.path.isfile(path):
        return path
    sample_count = _SOUNDSCAPE_SAMPLE_RATE * _SOUNDSCAPE_DURATION_S
    samples = preset["synth"](sample_count, _SOUNDSCAPE_SAMPLE_RATE)
    samples = _crossfade_loop(samples, _SOUNDSCAPE_SAMPLE_RATE, _SOUNDSCAPE_CROSSFADE_S)
    _write_wav(path, samples, _SOUNDSCAPE_SAMPLE_RATE)
    return path


def _custom_soundscapes_path():
    return os.path.join(core_config.path("radio"), "custom_soundscapes.json")


def list_custom_soundscapes():
    path = _custom_soundscapes_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return records if isinstance(records, list) else []


def _save_custom_soundscapes(records):
    path = _custom_soundscapes_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


def add_custom_soundscape(name, path):
    name = (name or "").strip()
    path = (path or "").strip()
    if not name or not path:
        raise ValueError("A soundscape needs both a name and an audio file.")
    records = list_custom_soundscapes()
    if any(r["path"] == path for r in records):
        raise ValueError(f'"{name}" is already in your soundscapes.')
    record = {"id": uuid.uuid4().hex[:8], "name": name, "path": path}
    records.append(record)
    _save_custom_soundscapes(records)
    return record


def remove_custom_soundscape(soundscape_id):
    records = list_custom_soundscapes()
    remaining = [r for r in records if r.get("id") != soundscape_id]
    if len(remaining) == len(records):
        return False
    _save_custom_soundscapes(remaining)
    return True


# ----------------------------------------------------------------------
# Spectrum analysis - pure-Python radix-2 FFT over whatever PCM the
# player's QAudioBufferOutput hands us, so the visualizer reacts to real
# audio (stream, file, or generated loop alike) instead of faking motion.
# ----------------------------------------------------------------------
def _fft(samples):
    n = len(samples)
    if n <= 1:
        return samples
    even = _fft(samples[0::2])
    odd = _fft(samples[1::2])
    half = n // 2
    combined = [0j] * n
    for k in range(half):
        twiddle = cmath.exp(-2j * math.pi * k / n) * odd[k]
        combined[k] = even[k] + twiddle
        combined[k + half] = even[k] - twiddle
    return combined


def _decode_pcm_mono(raw, sample_format, channels):
    """Decodes one QAudioBuffer's raw bytes into mono floats in [-1, 1]."""
    if sample_format == QAudioFormat.SampleFormat.Int16:
        count = len(raw) // 2
        if not count:
            return []
        values = struct.unpack(f"<{count}h", raw[:count * 2])
        scale = 32768.0
    elif sample_format == QAudioFormat.SampleFormat.Int32:
        count = len(raw) // 4
        if not count:
            return []
        values = struct.unpack(f"<{count}i", raw[:count * 4])
        scale = 2147483648.0
    elif sample_format == QAudioFormat.SampleFormat.UInt8:
        count = len(raw)
        if not count:
            return []
        values = [b - 128 for b in raw]
        scale = 128.0
    elif sample_format == QAudioFormat.SampleFormat.Float:
        count = len(raw) // 4
        if not count:
            return []
        values = struct.unpack(f"<{count}f", raw[:count * 4])
        scale = 1.0
    else:
        return []
    channels = max(1, channels)
    frame_count = len(values) // channels
    mono = []
    for i in range(frame_count):
        frame = values[i * channels:(i + 1) * channels]
        mono.append(sum(frame) / (len(frame) * scale))
    return mono


def _bucket_log(magnitudes, bar_count):
    """Averages linearly-spaced FFT bins into log-spaced buckets, so bass
    doesn't dominate every bar the way it would with linear bucketing."""
    n = len(magnitudes)
    if n == 0:
        return [0.0] * bar_count
    log_max = math.log2(n)
    bars = []
    for i in range(bar_count):
        lo = max(0, int(2 ** (log_max * i / bar_count)) - 1)
        hi = min(n, max(lo + 1, int(2 ** (log_max * (i + 1) / bar_count))))
        segment = magnitudes[lo:hi] or [0.0]
        bars.append(sum(segment) / len(segment))
    return bars


class SpectrumVisualizerWidget(QWidget):
    """Bar-spectrum visualizer driven by real decoded audio via
    feed_audio_buffer(); falls to a gentle decay-to-flat when idle rather
    than freezing on the last frame."""
    BAR_COUNT = 32
    FFT_SIZE = 1024
    GAIN = 55.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(90)
        self._samples = []
        self._bar_heights = [0.0] * self.BAR_COUNT
        self._active = False
        self._hud_caption = ""
        self._hud_title = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_now_playing(self, caption, title):
        """Sets the HUD overlay text drawn in the top-left corner - caption
        is a small kind label ("LIVE RADIO"/"NOW PLAYING"/"SOUNDSCAPE"),
        title is the station/track name. Empty title hides the HUD."""
        self._hud_caption = caption or ""
        self._hud_title = title or ""
        self.update()

    def feed_audio_buffer(self, buffer):
        try:
            fmt = buffer.format()
            pointer = buffer.data()
            pointer.setsize(buffer.byteCount())
            raw = bytes(pointer)
        except Exception:
            return
        mono = _decode_pcm_mono(raw, fmt.sampleFormat(), fmt.channelCount())
        if not mono:
            return
        self._samples.extend(mono)
        if len(self._samples) > self.FFT_SIZE:
            self._samples = self._samples[-self.FFT_SIZE:]
        self._active = True

    def set_idle(self):
        self._active = False
        self._samples = []

    def _tick(self):
        if self._active and len(self._samples) >= 64:
            window = self._samples[-self.FFT_SIZE:]
            if len(window) < self.FFT_SIZE:
                window = [0.0] * (self.FFT_SIZE - len(window)) + window
            magnitudes = [abs(v) for v in _fft(window)[:self.FFT_SIZE // 2]]
            for i, avg_magnitude in enumerate(_bucket_log(magnitudes, self.BAR_COUNT)):
                target = min(1.0, math.sqrt(avg_magnitude / self.GAIN))
                self._bar_heights[i] = target if target > self._bar_heights[i] else self._bar_heights[i] * 0.82
        else:
            self._bar_heights = [h * 0.85 for h in self._bar_heights]
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        painter.fillRect(self.rect(), QColor(18, 18, 26))
        gap = 3
        bar_width = (width - gap * (self.BAR_COUNT + 1)) / self.BAR_COUNT
        for i, level in enumerate(self._bar_heights):
            bar_height = max(2.0, level * (height - 8))
            x = gap + i * (bar_width + gap)
            y = height - bar_height - 4
            color = QColor.fromHsv(int(200 - level * 160), 210, 255)
            painter.fillRect(int(x), int(y), max(1, int(bar_width)), int(bar_height), color)
        if self._hud_title:
            self._paint_hud(painter, width)

    def _paint_hud(self, painter, width):
        padding = 8
        caption_font = QFont()
        caption_font.setPointSize(8)
        caption_font.setBold(True)
        caption_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 115)
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)

        painter.setFont(title_font)
        title_metrics = painter.fontMetrics()
        painter.setFont(caption_font)
        caption_metrics = painter.fontMetrics()

        max_text_width = width - 2 * padding - 24
        box_width = min(width - 2 * padding, max(
            title_metrics.horizontalAdvance(self._hud_title),
            caption_metrics.horizontalAdvance(self._hud_caption),
        ) + 24)
        box_rect = QRectF(padding, padding, box_width, 44)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(10, 10, 16, 160))
        painter.drawRoundedRect(box_rect, 8, 8)

        painter.setPen(QColor(150, 220, 255))
        painter.setFont(caption_font)
        painter.drawText(
            QRectF(padding + 12, padding + 4, box_width - 24, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._hud_caption,
        )

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(title_font)
        elided_title = title_metrics.elidedText(self._hud_title, Qt.TextElideMode.ElideRight, int(max_text_width))
        painter.drawText(
            QRectF(padding + 12, padding + 18, box_width - 24, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title,
        )


def _format_ms(ms):
    total_seconds = max(0, int(ms)) // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


# ----------------------------------------------------------------------
# Widget infra - own copies of the small helpers weather_station.py also
# defines locally (repo convention: duplicate rather than share a util).
# ----------------------------------------------------------------------
class _FetchWorker(QThread):
    result_ready = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        self.result_ready.emit(self.fn())


def _scroll_list():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    inner = QWidget()
    inner_layout = QVBoxLayout(inner)
    inner_layout.setContentsMargins(4, 4, 4, 4)
    inner_layout.setSpacing(8)
    inner_layout.addStretch()
    scroll.setWidget(inner)
    return scroll, inner_layout


def _clear_layout(layout):
    while layout.count() > 1:  # keep the trailing stretch
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.deleteLater()


class AuthorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Author")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Name"))
        self.name_input = QLineEdit()
        layout.addWidget(self.name_input)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red;")
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.created_author = None

    def _on_save(self):
        try:
            self.created_author = add_author(self.name_input.text())
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()


class SeriesDialog(QDialog):
    def __init__(self, parent=None, editing_series=None):
        super().__init__(parent)
        self.editing_series = editing_series
        self.setWindowTitle("Edit Series" if editing_series else "New Series")
        self.resize(360, 320)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Name"))
        self.name_input = QLineEdit(editing_series["name"] if editing_series else "")
        layout.addWidget(self.name_input)

        layout.addWidget(QLabel("Author"))
        author_row = QHBoxLayout()
        self.author_combo = QComboBox()
        self._reload_authors(select_id=editing_series.get("author_id") if editing_series else None)
        author_row.addWidget(self.author_combo, 1)
        new_author_button = QPushButton("+ New Author")
        new_author_button.clicked.connect(self._new_author_clicked)
        author_row.addWidget(new_author_button)
        layout.addLayout(author_row)

        layout.addWidget(QLabel("Synopsis (optional)"))
        self.synopsis_input = QTextEdit()
        self.synopsis_input.setFixedHeight(100)
        self.synopsis_input.setPlainText(editing_series.get("synopsis", "") if editing_series else "")
        layout.addWidget(self.synopsis_input)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red;")
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.created_series = None

    def _reload_authors(self, select_id=None):
        self.author_combo.clear()
        for author in list_authors():
            self.author_combo.addItem(author["name"], author["id"])
        if select_id:
            idx = self.author_combo.findData(select_id)
            if idx >= 0:
                self.author_combo.setCurrentIndex(idx)

    def _new_author_clicked(self):
        dialog = AuthorDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created_author:
            self._reload_authors(select_id=dialog.created_author["id"])

    def _on_save(self):
        if self.author_combo.count() == 0:
            self.error_label.setText("Add an author first.")
            return
        try:
            if self.editing_series:
                self.created_series = update_series(
                    self.editing_series["id"], name=self.name_input.text(),
                    author_id=self.author_combo.currentData(),
                    synopsis=self.synopsis_input.toPlainText(),
                )
            else:
                self.created_series = add_series(
                    self.name_input.text(), self.author_combo.currentData(),
                    synopsis=self.synopsis_input.toPlainText(),
                )
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()


class BookDialog(QDialog):
    def __init__(self, initial_title="", parent=None, editing_book=None):
        super().__init__(parent)
        self.editing_book = editing_book
        self.setWindowTitle("Edit Book" if editing_book else "New Book")
        self.resize(420, 480)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Title"))
        self.title_input = QLineEdit(editing_book["title"] if editing_book else initial_title)
        layout.addWidget(self.title_input)

        layout.addWidget(QLabel("Author"))
        author_row = QHBoxLayout()
        self.author_combo = QComboBox()
        self._reload_authors(select_id=editing_book.get("author_id") if editing_book else None)
        author_row.addWidget(self.author_combo, 1)
        new_author_button = QPushButton("+ New Author")
        new_author_button.clicked.connect(self._new_author_clicked)
        author_row.addWidget(new_author_button)
        layout.addLayout(author_row)

        layout.addWidget(QLabel("Series (optional)"))
        series_row = QHBoxLayout()
        self.series_combo = QComboBox()
        self._reload_series(select_id=editing_book.get("series_id") if editing_book else None)
        self.series_combo.currentIndexChanged.connect(self._on_series_changed)
        series_row.addWidget(self.series_combo, 1)
        new_series_button = QPushButton("+ New Series")
        new_series_button.clicked.connect(self._new_series_clicked)
        series_row.addWidget(new_series_button)
        layout.addLayout(series_row)

        index_row = QHBoxLayout()
        index_row.addWidget(QLabel("Position in series"))
        self.series_index_input = QSpinBox()
        self.series_index_input.setRange(1, 999)
        self.series_index_input.setValue((editing_book.get("series_index") or 1) if editing_book else 1)
        index_row.addWidget(self.series_index_input)
        index_row.addStretch()
        layout.addLayout(index_row)
        self._on_series_changed()

        layout.addWidget(QLabel("Synopsis (optional)"))
        self.synopsis_input = QTextEdit()
        self.synopsis_input.setFixedHeight(110)
        self.synopsis_input.setPlainText(editing_book.get("synopsis", "") if editing_book else "")
        layout.addWidget(self.synopsis_input)
        draft_button = QPushButton("🪄 Draft synopsis with AI (unverified - review before saving)")
        draft_button.clicked.connect(self._draft_synopsis_clicked)
        layout.addWidget(draft_button)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red;")
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.result_book = None
        self._draft_worker = None

    def _reload_authors(self, select_id=None):
        self.author_combo.clear()
        for author in list_authors():
            self.author_combo.addItem(author["name"], author["id"])
        if select_id:
            idx = self.author_combo.findData(select_id)
            if idx >= 0:
                self.author_combo.setCurrentIndex(idx)

    def _reload_series(self, select_id=None):
        self.series_combo.clear()
        self.series_combo.addItem("— No series —", None)
        for series in list_series():
            self.series_combo.addItem(series["name"], series["id"])
        if select_id:
            idx = self.series_combo.findData(select_id)
            if idx >= 0:
                self.series_combo.setCurrentIndex(idx)

    def _on_series_changed(self):
        self.series_index_input.setEnabled(self.series_combo.currentData() is not None)

    def _new_author_clicked(self):
        dialog = AuthorDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created_author:
            self._reload_authors(select_id=dialog.created_author["id"])

    def _new_series_clicked(self):
        dialog = SeriesDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created_series:
            self._reload_series(select_id=dialog.created_series["id"])

    def _draft_synopsis_clicked(self):
        title = self.title_input.text().strip()
        if not title:
            self.error_label.setText("Enter a title first.")
            return
        author_name = self.author_combo.currentText()
        self.error_label.setText("Drafting...")

        def work():
            prompt = (
                f'Write a short (3-5 sentence), spoiler-light synopsis of the book "{title}"'
                + (f" by {author_name}" if author_name else "")
                + ". If you don't actually recognize this specific book, say so plainly instead "
                "of inventing a plot."
            )
            response = model_chat(model=_CHAT_MODEL, messages=[{"role": "user", "content": prompt}])
            return response.get("message", {}).get("content", "")

        def handle(text):
            self.error_label.setText("")
            self.synopsis_input.setPlainText(text or "")

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._draft_worker = worker
        worker.start()

    def _on_save(self):
        if self.author_combo.count() == 0:
            self.error_label.setText("Add an author first.")
            return
        series_id = self.series_combo.currentData()
        series_index = self.series_index_input.value() if series_id else None
        try:
            if self.editing_book:
                self.result_book = update_book(
                    self.editing_book["id"], title=self.title_input.text(),
                    author_id=self.author_combo.currentData(), series_id=series_id,
                    series_index=series_index, synopsis=self.synopsis_input.toPlainText(),
                )
            else:
                self.result_book = add_book(
                    self.title_input.text(), self.author_combo.currentData(),
                    series_id=series_id, series_index=series_index,
                    synopsis=self.synopsis_input.toPlainText(),
                )
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()


class AssignToBookDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Assign to Book")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Book"))
        self.book_combo = QComboBox()
        self._reload_books()
        layout.addWidget(self.book_combo)
        new_book_button = QPushButton("+ New Book")
        new_book_button.clicked.connect(self._new_book_clicked)
        layout.addWidget(new_book_button)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red;")
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.selected_book_id = None

    def _reload_books(self, select_id=None):
        self.book_combo.clear()
        authors = {a["id"]: a["name"] for a in list_authors()}
        for book in list_books():
            author_name = authors.get(book.get("author_id"), "Unknown author")
            self.book_combo.addItem(f'{book["title"]} — {author_name}', book["id"])
        if select_id:
            idx = self.book_combo.findData(select_id)
            if idx >= 0:
                self.book_combo.setCurrentIndex(idx)

    def _new_book_clicked(self):
        dialog = BookDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_book:
            self._reload_books(select_id=dialog.result_book["id"])

    def _on_ok(self):
        if self.book_combo.count() == 0:
            self.error_label.setText("Create a book first.")
            return
        self.selected_book_id = self.book_combo.currentData()
        self.accept()


class _ChooseFolderGroupDialog(QDialog):
    """When Unsorted files span more than one source folder, lets the user
    pick which folder's-worth to turn into a book (one at a time), rather
    than guessing which files belong together."""

    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose a folder to group")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Your unsorted files come from more than one folder - pick one to turn into a book:"))
        self.combo = QComboBox()
        for folder, records in groups.items():
            label = os.path.basename(folder.rstrip(os.sep)) or folder
            self.combo.addItem(f"{label} ({len(records)} file(s))", folder)
        layout.addWidget(self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.selected_folder = None

    def _on_ok(self):
        self.selected_folder = self.combo.currentData()
        self.accept()


class _ChatTurnWorker(QThread):
    done = pyqtSignal(str, list)
    failed = pyqtSignal(str)

    def __init__(self, conversation, system_prompt):
        super().__init__()
        self.conversation = conversation
        self.system_prompt = system_prompt

    def run(self):
        try:
            reply, updated = ask_about_topic(self.conversation, self.system_prompt)
            self.done.emit(reply, updated)
        except Exception as exc:
            self.failed.emit(str(exc))


class TopicChatDialog(QDialog):
    """'Ask about this book/series' - a chat scoped to one book or series,
    reusing Penpot Studio's minimal chat shape (transcript + input row +
    QThread worker, penpot_studio.py) rather than the main chat's heavier
    tool-routing pipeline, since this never needs to call any tools."""

    def __init__(self, scope, scope_id, title, author_name="", series_name="", synopsis="", parent=None):
        super().__init__(parent)
        self.scope = scope
        self.scope_id = scope_id
        self.setWindowTitle(f'💬 Ask about "{title}"')
        self.resize(520, 480)
        self._system_prompt = _build_topic_system_prompt(scope, title, author_name, series_name, synopsis)
        self._conversation = load_chat(scope, scope_id)
        self._worker = None

        layout = QVBoxLayout(self)
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        for turn in self._conversation:
            speaker = "You" if turn.get("role") == "user" else "Assistant"
            self.transcript.append(f"<b>{speaker}:</b> {turn.get('content', '')}")
        layout.addWidget(self.transcript, 1)

        input_row = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText(f"Ask anything about {title}...")
        self.message_input.returnPressed.connect(self._on_send_clicked)
        input_row.addWidget(self.message_input, 1)
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self._on_send_clicked)
        input_row.addWidget(self.send_button)
        layout.addLayout(input_row)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

    def _on_send_clicked(self):
        text = self.message_input.text().strip()
        if not text:
            return
        self.transcript.append(f"<b>You:</b> {text}")
        self.message_input.clear()
        self._conversation.append({"role": "user", "content": text})
        self.send_button.setEnabled(False)
        self.status_label.setText("Thinking...")
        worker = _ChatTurnWorker(list(self._conversation), self._system_prompt)
        worker.done.connect(self._on_turn_done)
        worker.failed.connect(self._on_turn_failed)
        self._worker = worker
        worker.start()

    def _on_turn_done(self, reply, updated_conversation):
        self._conversation = updated_conversation
        self.transcript.append(f"<b>Assistant:</b> {reply}")
        save_chat(self.scope, self.scope_id, self._conversation)
        self.status_label.setText("")
        self.send_button.setEnabled(True)

    def _on_turn_failed(self, message):
        self.transcript.append(f"<b>Error:</b> {message}")
        self.status_label.setText("")
        self.send_button.setEnabled(True)


class RadioWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._now_playing = None  # {"kind": "radio"|"library"|"soundscape", "id":.., "label":..}
        self._pending_resume_ms = None
        self._seek_dragging = False
        self._library_kind_filter = "music"
        self._expanded_books = set()
        self._expanded_series = set()
        self._library_search = ""
        self._radio_buttons = {}
        self._library_buttons = {}
        self._soundscape_buttons = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(15, 15, 15, 15)
        outer.setSpacing(10)

        title = QLabel("📻 Radio")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_live_radio_tab(), "📻 Live Radio")
        self.tabs.addTab(self._build_library_tab(), "🎵 Music && Audiobooks")
        self.tabs.addTab(self._build_soundscapes_tab(), "🌊 Soundscapes")
        self._tv_tab_index = self.tabs.addTab(TVWidget(), "📺 TV")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.transport_bar = self._build_transport_bar()
        outer.addWidget(self.transport_bar)

        self._media_player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(0.7)
        self._media_player.setAudioOutput(self._audio_output)
        self._media_devices = QMediaDevices(self)
        self._media_devices.audioOutputsChanged.connect(self._on_audio_outputs_changed)
        self._buffer_output = QAudioBufferOutput()
        self._media_player.setAudioBufferOutput(self._buffer_output)
        self._buffer_output.audioBufferReceived.connect(self._on_audio_buffer)
        self._media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._media_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._media_player.positionChanged.connect(self._on_position_changed)
        self._media_player.durationChanged.connect(self._on_duration_changed)
        self._media_player.errorOccurred.connect(self._on_player_error)

        self._position_save_timer = QTimer(self)
        self._position_save_timer.setInterval(5000)
        self._position_save_timer.timeout.connect(self._save_current_library_position)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._save_current_library_position)

        self._refresh_radio_stations()
        self._refresh_library()
        self._refresh_soundscapes()

    # ------------------------------------------------------------------
    # Transport bar - shared across all three tabs, one player at a time
    # ------------------------------------------------------------------
    def _build_transport_bar(self):
        bar = QFrame()
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(bar)

        self.visualizer = SpectrumVisualizerWidget()
        layout.addWidget(self.visualizer)

        info_row = QHBoxLayout()
        info_row.addStretch()
        self.player_status_label = QLabel("")
        info_row.addWidget(self.player_status_label)
        layout.addLayout(info_row)

        seek_row = QHBoxLayout()
        self.elapsed_label = QLabel("0:00")
        seek_row.addWidget(self.elapsed_label)
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setEnabled(False)
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        seek_row.addWidget(self.seek_slider, 1)
        self.duration_label = QLabel("0:00")
        seek_row.addWidget(self.duration_label)
        layout.addLayout(seek_row)

        controls_row = QHBoxLayout()
        self.play_pause_button = QPushButton("▶ Play")
        self.play_pause_button.clicked.connect(self._toggle_play_pause)
        controls_row.addWidget(self.play_pause_button)
        self.stop_button = QPushButton("■ Stop")
        self.stop_button.clicked.connect(self._stop_playback)
        controls_row.addWidget(self.stop_button)
        controls_row.addSpacing(16)
        controls_row.addWidget(QLabel("🔊"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.valueChanged.connect(lambda v: self._audio_output.setVolume(v / 100))
        controls_row.addWidget(self.volume_slider)
        controls_row.addStretch()
        layout.addLayout(controls_row)
        return bar

    def _on_tab_changed(self, index):
        self.transport_bar.setVisible(index != self._tv_tab_index)

    def _toggle_play_pause(self):
        state = self._media_player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._media_player.play()

    def _stop_playback(self):
        self._save_current_library_position()
        self._position_save_timer.stop()
        self._media_player.stop()
        self._now_playing = None
        self._pending_resume_ms = None
        self.visualizer.set_idle()
        self._sync_now_playing_ui()

    def _on_seek_pressed(self):
        self._seek_dragging = True

    def _on_seek_released(self):
        self._seek_dragging = False
        self._media_player.setPosition(self.seek_slider.value())

    def _on_position_changed(self, position_ms):
        if not self._seek_dragging:
            self.seek_slider.setValue(position_ms)
        self.elapsed_label.setText(_format_ms(position_ms))

    def _on_duration_changed(self, duration_ms):
        seekable = duration_ms > 0
        self.seek_slider.setRange(0, max(0, duration_ms))
        self.seek_slider.setEnabled(seekable)
        self.duration_label.setText(_format_ms(duration_ms) if seekable else "live")

    def _on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia and self._pending_resume_ms:
            self._media_player.setPosition(self._pending_resume_ms)
            self._pending_resume_ms = None
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._on_library_playback_finished()

    def _on_library_playback_finished(self):
        """Auto-advances to the next chapter of a book, so a series/book
        actually keeps playing across chapter files instead of stopping
        every ~20 minutes. Marks the chapter that just ended as finished
        (position reset to 0) instead of leaving its saved position sitting
        at end-of-track - otherwise replaying it later would seek to the
        last second and immediately re-trigger this same handler."""
        if not self._now_playing or self._now_playing["kind"] != "library":
            return
        finished_id = self._now_playing["id"]
        record = next((r for r in list_library_items() if r["id"] == finished_id), None)
        set_library_finished(finished_id, True)
        book_id = record.get("book_id") if record else None
        next_file = None
        if book_id:
            files = list_book_files(book_id)
            index = next((i for i, f in enumerate(files) if f["id"] == finished_id), None)
            if index is not None and index + 1 < len(files):
                next_file = files[index + 1]
        # Clear now-playing before dispatching further, so the position-save
        # that _play_library_item/_stop_playback do up front can't re-save
        # this item's end-of-track position and undo the finished mark above.
        self._now_playing = None
        if next_file:
            self._play_library_item(next_file)
        else:
            self._position_save_timer.stop()
            self._pending_resume_ms = None
            self.visualizer.set_idle()
            self._sync_now_playing_ui()
            if book_id and self._library_kind_filter == "audiobook":
                self._refresh_library()

    def _on_playback_state_changed(self, state):
        self.play_pause_button.setText(
            "⏸ Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "▶ Play"
        )
        if state == QMediaPlayer.PlaybackState.StoppedState:
            self.visualizer.set_idle()
        self._sync_row_button_labels()

    def _on_player_error(self, error, error_string):
        if error == QMediaPlayer.Error.NoError:
            return
        self.player_status_label.setText(f"⚠ {error_string}")

    def _on_audio_outputs_changed(self):
        self._audio_output.setDevice(QMediaDevices.defaultAudioOutput())

    def _on_audio_buffer(self, buffer):
        self.visualizer.feed_audio_buffer(buffer)

    def _sync_now_playing_ui(self):
        if self._now_playing:
            captions = {"radio": "📻 LIVE RADIO", "library": "🎵 NOW PLAYING", "soundscape": "🌊 SOUNDSCAPE"}
            self.visualizer.set_now_playing(captions[self._now_playing["kind"]], self._now_playing["label"])
        else:
            self.visualizer.set_now_playing("", "")
        self.player_status_label.setText("")
        self._sync_row_button_labels()

    def _sync_row_button_labels(self):
        playing = self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        active = (self._now_playing["kind"], self._now_playing["id"]) if (self._now_playing and playing) else None
        for kind, group, active_label in (
            ("radio", self._radio_buttons, "⏹ Stop"),
            ("library", self._library_buttons, "⏸ Pause"),
            ("soundscape", self._soundscape_buttons, "⏹ Stop"),
        ):
            for item_id, button in group.items():
                button.setText(active_label if (kind, item_id) == active else "▶ Play")

    def _toggle_row(self, kind, item_id, on_play):
        is_active = self._now_playing and self._now_playing["kind"] == kind and self._now_playing["id"] == item_id
        is_playing = self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if is_active and is_playing:
            if kind == "library":
                self._media_player.pause()
            else:
                self._stop_playback()
        else:
            on_play()

    def _save_current_library_position(self):
        if self._now_playing and self._now_playing["kind"] == "library":
            update_library_position(self._now_playing["id"], self._media_player.position())

    # ------------------------------------------------------------------
    # Playback dispatch - one QMediaPlayer, three kinds of source
    # ------------------------------------------------------------------
    def _play_stream(self, stream_url, label, station_id=None):
        self._save_current_library_position()
        self._position_save_timer.stop()
        self._media_player.stop()  # fully tear down any in-flight source/reconnect before switching
        self._media_player.setLoops(QMediaPlayer.Loops.Once)
        self._pending_resume_ms = None
        self._now_playing = {"kind": "radio", "id": station_id, "label": label}
        self._media_player.setSource(QUrl(stream_url))
        self._media_player.play()
        self._sync_now_playing_ui()

    def _play_library_item(self, record):
        self._save_current_library_position()
        self._media_player.stop()
        self._media_player.setLoops(QMediaPlayer.Loops.Once)
        self._pending_resume_ms = 0 if record.get("finished") else (record.get("position_ms") or 0)
        self._now_playing = {"kind": "library", "id": record["id"], "label": record["title"]}
        self._media_player.setSource(QUrl.fromLocalFile(record["path"]))
        self._media_player.play()
        self._sync_now_playing_ui()
        if record["kind"] == "audiobook":
            self._position_save_timer.start()
        else:
            self._position_save_timer.stop()
        book_id = record.get("book_id")
        if book_id:
            set_book_last_played(book_id, record["id"])
            book = next((b for b in list_books() if b["id"] == book_id), None)
            if book and book.get("series_id"):
                set_series_last_played(book["series_id"], book_id)
            if self._library_kind_filter == "audiobook":
                self._refresh_library()

    def _play_soundscape(self, path, label, soundscape_id):
        self._save_current_library_position()
        self._position_save_timer.stop()
        self._media_player.stop()
        self._media_player.setLoops(QMediaPlayer.Loops.Infinite)
        self._pending_resume_ms = None
        self._now_playing = {"kind": "soundscape", "id": soundscape_id, "label": label}
        self._media_player.setSource(QUrl.fromLocalFile(path))
        self._media_player.play()
        self._sync_now_playing_ui()

    # ------------------------------------------------------------------
    # Live Radio tab
    # ------------------------------------------------------------------
    def _build_live_radio_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        search_row = QHBoxLayout()
        self.radio_search_input = QLineEdit()
        self.radio_search_input.setPlaceholderText('Search stations, e.g. "lofi" or "BBC Radio 4"')
        self.radio_search_input.returnPressed.connect(self._search_radio_stations_clicked)
        search_row.addWidget(self.radio_search_input, 1)
        search_button = QPushButton("🔍 Search")
        search_button.clicked.connect(self._search_radio_stations_clicked)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        search_section = QWidget()
        search_layout = QVBoxLayout(search_section)
        search_layout.setContentsMargins(0, 0, 0, 0)
        self.radio_search_status_label = QLabel(
            "Search Radio-Browser's free station directory, or add a stream URL manually below."
        )
        self.radio_search_status_label.setWordWrap(True)
        search_layout.addWidget(self.radio_search_status_label)
        self.radio_search_scroll, self.radio_search_results_layout = _scroll_list()
        search_layout.addWidget(self.radio_search_scroll)
        splitter.addWidget(search_section)

        saved_section = QWidget()
        saved_layout = QVBoxLayout(saved_section)
        saved_layout.setContentsMargins(0, 0, 0, 0)
        saved_layout.addWidget(QLabel("Saved stations"))
        add_row = QHBoxLayout()
        self.radio_name_input = QLineEdit()
        self.radio_name_input.setPlaceholderText("Station name")
        add_row.addWidget(self.radio_name_input, 1)
        self.radio_url_input = QLineEdit()
        self.radio_url_input.setPlaceholderText("Stream URL (or add manually)")
        add_row.addWidget(self.radio_url_input, 2)
        radio_add_button = QPushButton("+ Add")
        radio_add_button.clicked.connect(self._add_radio_station_clicked)
        add_row.addWidget(radio_add_button)
        saved_layout.addLayout(add_row)
        self.radio_status_label = QLabel("")
        saved_layout.addWidget(self.radio_status_label)
        self.radio_scroll, self.radio_list_layout = _scroll_list()
        saved_layout.addWidget(self.radio_scroll)
        splitter.addWidget(saved_section)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 320])
        layout.addWidget(splitter, 1)
        return page

    def _search_radio_stations_clicked(self):
        query = self.radio_search_input.text().strip()
        if not query:
            self.radio_search_status_label.setText("Enter a search term first.")
            return
        self.radio_search_status_label.setText("Searching...")
        _clear_layout(self.radio_search_results_layout)

        def work():
            return search_radio_stations(query)

        def handle(results):
            if results is None:
                self.radio_search_status_label.setText("Search temporarily unavailable.")
                return
            if not results:
                self.radio_search_status_label.setText(f'No stations found for "{query}".')
                return
            self.radio_search_status_label.setText(f'{len(results)} result(s) for "{query}".')
            for result in results:
                row = QFrame()
                row_layout = QVBoxLayout(row)
                row_layout.setContentsMargins(6, 4, 6, 4)
                top = QHBoxLayout()
                name_label = QLabel(result["name"])
                name_label.setStyleSheet("font-weight: bold;")
                top.addWidget(name_label, 1)
                preview_button = QPushButton("▶ Preview")
                preview_button.clicked.connect(lambda _c=False, r=result: self._play_stream(r["stream_url"], r["name"]))
                top.addWidget(preview_button)
                add_button = QPushButton("+ Add")
                add_button.clicked.connect(lambda _c=False, r=result: self._add_radio_search_result_clicked(r))
                top.addWidget(add_button)
                row_layout.addLayout(top)
                detail_bits = [bit for bit in (result["country"], result["state"], result["tags"]) if bit]
                if result.get("bitrate"):
                    detail_bits.append(f'{result["bitrate"]} kbps')
                if detail_bits:
                    detail_label = QLabel(" · ".join(detail_bits))
                    detail_label.setStyleSheet("color: gray;")
                    row_layout.addWidget(detail_label)
                self.radio_search_results_layout.insertWidget(self.radio_search_results_layout.count() - 1, row)

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._radio_search_worker = worker
        worker.start()

    def _add_radio_search_result_clicked(self, result):
        try:
            add_radio_station(result["name"], result["stream_url"])
        except ValueError as exc:
            self.radio_search_status_label.setText(str(exc))
            return
        self.radio_search_status_label.setText(f'Added "{result["name"]}".')
        self._refresh_radio_stations()

    def _refresh_radio_stations(self):
        _clear_layout(self.radio_list_layout)
        self._radio_buttons = {}
        for record in list_radio_stations():
            row = QFrame()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(QLabel(record["name"]), 1)
            play_button = QPushButton("▶ Play")
            play_button.clicked.connect(
                lambda _c=False, r=record: self._toggle_row(
                    "radio", r["id"], lambda r=r: self._play_stream(r["stream_url"], r["name"], station_id=r["id"])
                )
            )
            row_layout.addWidget(play_button)
            remove_button = QPushButton("✕")
            remove_button.setFixedWidth(28)
            remove_button.clicked.connect(lambda _c=False, r=record: self._remove_radio_station_clicked(r))
            row_layout.addWidget(remove_button)
            self._radio_buttons[record["id"]] = play_button
            self.radio_list_layout.insertWidget(self.radio_list_layout.count() - 1, row)
        self._sync_row_button_labels()

    def _add_radio_station_clicked(self):
        name = self.radio_name_input.text().strip()
        url = self.radio_url_input.text().strip()
        try:
            add_radio_station(name, url)
        except ValueError as exc:
            self.radio_status_label.setText(str(exc))
            return
        self.radio_name_input.clear()
        self.radio_url_input.clear()
        self.radio_status_label.setText(f'Added "{name}".')
        self._refresh_radio_stations()

    def _remove_radio_station_clicked(self, record):
        if self._now_playing and self._now_playing["kind"] == "radio" and self._now_playing["id"] == record["id"]:
            self._stop_playback()
        remove_radio_station(record["id"])
        self.radio_status_label.setText(f'Removed "{record["name"]}".')
        self._refresh_radio_stations()

    # ------------------------------------------------------------------
    # Music & Audiobooks tab
    # ------------------------------------------------------------------
    def _build_library_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        kind_row = QHBoxLayout()
        self.library_music_button = QPushButton("🎵 Music")
        self.library_music_button.setCheckable(True)
        self.library_music_button.setChecked(True)
        self.library_music_button.clicked.connect(lambda: self._set_library_kind_filter("music"))
        kind_row.addWidget(self.library_music_button)
        self.library_audiobook_button = QPushButton("🎧 Audiobooks")
        self.library_audiobook_button.setCheckable(True)
        self.library_audiobook_button.clicked.connect(lambda: self._set_library_kind_filter("audiobook"))
        kind_row.addWidget(self.library_audiobook_button)
        kind_row.addStretch()
        add_files_button = QPushButton("+ Add Files")
        add_files_button.clicked.connect(self._add_library_files_clicked)
        kind_row.addWidget(add_files_button)
        add_folder_button = QPushButton("+ Add Folder")
        add_folder_button.clicked.connect(self._add_library_folder_clicked)
        kind_row.addWidget(add_folder_button)
        layout.addLayout(kind_row)

        catalog_row = QHBoxLayout()
        self.new_author_button = QPushButton("+ New Author")
        self.new_author_button.clicked.connect(self._new_author_clicked)
        catalog_row.addWidget(self.new_author_button)
        self.new_series_button = QPushButton("+ New Series")
        self.new_series_button.clicked.connect(self._new_series_clicked)
        catalog_row.addWidget(self.new_series_button)
        self.group_into_book_button = QPushButton("Group Unsorted Into a Book")
        self.group_into_book_button.clicked.connect(self._group_into_book_clicked)
        catalog_row.addWidget(self.group_into_book_button)
        catalog_row.addStretch()
        layout.addLayout(catalog_row)

        self.library_search_input = QLineEdit()
        self.library_search_input.setPlaceholderText("Search books, authors, series...")
        self.library_search_input.textChanged.connect(self._on_library_search_changed)
        layout.addWidget(self.library_search_input)

        self.library_status_label = QLabel("")
        layout.addWidget(self.library_status_label)

        self.library_scroll, self.library_list_layout = _scroll_list()
        layout.addWidget(self.library_scroll, 1)

        self._sync_catalog_controls_visibility()
        return page

    def _sync_catalog_controls_visibility(self):
        is_audiobook = self._library_kind_filter == "audiobook"
        self.new_author_button.setVisible(is_audiobook)
        self.new_series_button.setVisible(is_audiobook)
        self.group_into_book_button.setVisible(is_audiobook)
        self.library_search_input.setVisible(is_audiobook)

    def _set_library_kind_filter(self, kind):
        self._library_kind_filter = kind
        self.library_music_button.setChecked(kind == "music")
        self.library_audiobook_button.setChecked(kind == "audiobook")
        self._sync_catalog_controls_visibility()
        self._refresh_library()

    def _on_library_search_changed(self, text):
        self._library_search = text.strip().lower()
        self._refresh_library()

    def _add_library_files_clicked(self):
        filter_str = "Audio files (*" + " *".join(sorted(AUDIO_EXTENSIONS)) + ")"
        paths, _filter = QFileDialog.getOpenFileNames(self, "Add audio files", "", filter_str)
        if not paths:
            return
        added = add_library_paths(paths, kind=self._library_kind_filter)
        self.library_status_label.setText(
            f"Added {len(added)} file(s)." if added else "No new files added (already in your library)."
        )
        self._refresh_library()

    def _add_library_folder_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, "Add a music/audiobook folder")
        if not folder:
            return
        added = add_library_paths([folder], kind=self._library_kind_filter)
        if not added:
            self.library_status_label.setText("No new audio files found in that folder.")
            return
        if self._library_kind_filter == "audiobook":
            dialog = BookDialog(initial_title=os.path.basename(folder.rstrip(os.sep)), parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_book:
                assign_files_to_book([r["id"] for r in added], dialog.result_book["id"])
                self.library_status_label.setText(
                    f'Added {len(added)} file(s) into "{dialog.result_book["title"]}".'
                )
            else:
                self.library_status_label.setText(f"Added {len(added)} file(s) - unsorted for now.")
        else:
            self.library_status_label.setText(f"Added {len(added)} file(s) from that folder.")
        self._refresh_library()

    def _new_author_clicked(self):
        dialog = AuthorDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created_author:
            self.library_status_label.setText(f'Added author "{dialog.created_author["name"]}".')
            self._refresh_library()

    def _new_series_clicked(self):
        dialog = SeriesDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created_series:
            self.library_status_label.setText(f'Added series "{dialog.created_series["name"]}".')
            self._refresh_library()

    def _group_into_book_clicked(self):
        unsorted = [r for r in list_library_items() if r["kind"] == "audiobook" and not r.get("book_id")]
        if not unsorted:
            self.library_status_label.setText("No unsorted audiobook files to group.")
            return
        groups = {}
        for record in unsorted:
            groups.setdefault(os.path.dirname(record["path"]), []).append(record)
        if len(groups) == 1:
            folder, records = next(iter(groups.items()))
            self._open_group_folder_dialog(folder, records)
        else:
            dialog = _ChooseFolderGroupDialog(groups, self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_folder:
                self._open_group_folder_dialog(dialog.selected_folder, groups[dialog.selected_folder])

    def _open_group_folder_dialog(self, folder, records):
        records = sorted(records, key=lambda r: r["path"])
        dialog = BookDialog(initial_title=os.path.basename(folder.rstrip(os.sep)) or folder, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_book:
            assign_files_to_book([r["id"] for r in records], dialog.result_book["id"])
            self.library_status_label.setText(
                f'Grouped {len(records)} file(s) into "{dialog.result_book["title"]}".'
            )
            self._refresh_library()

    def _assign_file_clicked(self, record):
        dialog = AssignToBookDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_book_id:
            assign_files_to_book([record["id"]], dialog.selected_book_id)
            self.library_status_label.setText(f'Assigned "{record["title"]}" to a book.')
            self._refresh_library()

    def _unassign_file_clicked(self, record):
        unassign_file(record["id"])
        self.library_status_label.setText(f'Unassigned "{record["title"]}" - now in Unsorted files.')
        self._refresh_library()

    def _resume_book_clicked(self, book_id):
        files = list_book_files(book_id)
        if not files:
            self.library_status_label.setText("This book has no chapter files yet.")
            return
        book = next((b for b in list_books() if b["id"] == book_id), None)
        last_file_id = book.get("last_played_file_id") if book else None
        target = next((f for f in files if f["id"] == last_file_id), None) if last_file_id else None
        if last_file_id and target is None:
            self.library_status_label.setText(
                "⚠ The last-played chapter is missing from your library - pick a chapter below instead."
            )
            return
        self._play_library_item(target or files[0])

    def _resume_series_clicked(self, series_id):
        series = next((s for s in list_series() if s["id"] == series_id), None)
        books = sorted(
            (b for b in list_books() if b.get("series_id") == series_id),
            key=lambda b: b.get("series_index") or 0,
        )
        if not books:
            self.library_status_label.setText("This series has no books yet.")
            return
        last_book_id = series.get("last_played_book_id") if series else None
        target_book = next((b for b in books if b["id"] == last_book_id), None) if last_book_id else None
        if last_book_id and target_book is None:
            self.library_status_label.setText("⚠ The last-played book in this series is missing.")
            return
        self._resume_book_clicked((target_book or books[0])["id"])

    def _set_book_listened_clicked(self, book_id, listened):
        # If a chapter of this book is playing right now, stop it first -
        # otherwise the position-save timer would overwrite our manual mark
        # within seconds with whatever position it's actually sitting at.
        if self._now_playing and self._now_playing["kind"] == "library":
            current = next((r for r in list_library_items() if r["id"] == self._now_playing["id"]), None)
            if current and current.get("book_id") == book_id:
                self._stop_playback()
        set_book_listened(book_id, listened)
        book = next((b for b in list_books() if b["id"] == book_id), None)
        title = book["title"] if book else "This book"
        self.library_status_label.setText(
            f'Marked "{title}" as {"listened" if listened else "unlistened"}.'
        )
        self._refresh_library()

    def _edit_book_clicked(self, book):
        dialog = BookDialog(parent=self, editing_book=book)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_book:
            self.library_status_label.setText(f'Updated "{dialog.result_book["title"]}".')
            self._refresh_library()

    def _edit_series_clicked(self, series):
        dialog = SeriesDialog(parent=self, editing_series=series)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created_series:
            self.library_status_label.setText(f'Updated "{dialog.created_series["name"]}".')
            self._refresh_library()

    def _remove_book_clicked(self, book):
        remove_book(book["id"])
        self.library_status_label.setText(f'Removed "{book["title"]}" (its files are kept, now unsorted).')
        self._refresh_library()

    def _toggle_book_expanded(self, book_id):
        self._expanded_books.symmetric_difference_update({book_id})
        self._refresh_library()

    def _toggle_series_expanded(self, series_id):
        self._expanded_series.symmetric_difference_update({series_id})
        self._refresh_library()

    def _open_book_chat(self, book, author_name):
        dialog = TopicChatDialog(
            "book", book["id"], book["title"], author_name=author_name,
            synopsis=book.get("synopsis", ""), parent=self,
        )
        dialog.exec()

    def _open_series_chat(self, series, author_name):
        dialog = TopicChatDialog(
            "series", series["id"], series["name"], author_name=author_name,
            synopsis=series.get("synopsis", ""), parent=self,
        )
        dialog.exec()

    def _add_library_file_row(self, add_row, record, indent=False, show_unassign=False):
        row = QFrame()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(24 if indent else 0, 0, 0, 0)
        row_layout.addWidget(QLabel(record["title"]), 1)
        if record["kind"] == "audiobook" and record.get("finished"):
            finished_label = QLabel("✓ finished")
            finished_label.setStyleSheet("color: green;")
            row_layout.addWidget(finished_label)
        elif record["kind"] == "audiobook" and record.get("position_ms"):
            resume_label = QLabel(f'resume {_format_ms(record["position_ms"])}')
            resume_label.setStyleSheet("color: gray;")
            row_layout.addWidget(resume_label)
        play_button = QPushButton("▶ Play")
        play_button.clicked.connect(
            lambda _c=False, r=record: self._toggle_row("library", r["id"], lambda r=r: self._play_library_item(r))
        )
        row_layout.addWidget(play_button)
        if record["kind"] == "audiobook" and not record.get("book_id"):
            assign_button = QPushButton("Assign to Book...")
            assign_button.clicked.connect(lambda _c=False, r=record: self._assign_file_clicked(r))
            row_layout.addWidget(assign_button)
        if show_unassign:
            unassign_button = QPushButton("↩ Unassign")
            unassign_button.clicked.connect(lambda _c=False, r=record: self._unassign_file_clicked(r))
            row_layout.addWidget(unassign_button)
        remove_button = QPushButton("✕")
        remove_button.setFixedWidth(28)
        remove_button.clicked.connect(lambda _c=False, r=record: self._remove_library_item_clicked(r))
        row_layout.addWidget(remove_button)
        self._library_buttons[record["id"]] = play_button
        add_row(row)

    def _add_book_row(self, parent_layout, book, author_name, indent=False):
        row = QFrame()
        row.setFrameShape(QFrame.Shape.StyledPanel)
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(24 if indent else 4, 4, 4, 4)

        top = QHBoxLayout()
        expanded = book["id"] in self._expanded_books
        toggle_button = QPushButton("▾" if expanded else "▸")
        toggle_button.setFixedWidth(28)
        toggle_button.clicked.connect(lambda _c=False, bid=book["id"]: self._toggle_book_expanded(bid))
        top.addWidget(toggle_button)
        title_label = QLabel(book["title"] if indent else f'{book["title"]} — {author_name}')
        title_label.setStyleSheet("font-weight: bold;")
        top.addWidget(title_label, 1)

        summary = book_progress_summary(book["id"])
        if summary["status"] == "finished":
            progress_text, progress_color = "✓ Finished", "green"
        elif summary["status"] == "missing":
            progress_text, progress_color = "⚠ last-played chapter is missing", "orange"
        elif summary["status"] == "in_progress":
            progress_text = f'Chapter {summary["current_index"]} of {summary["total"]} · resume {_format_ms(summary["position_ms"])}'
            progress_color = "gray"
        elif summary["status"] == "not_started":
            progress_text, progress_color = f'{summary["total"]} chapter(s) · not started', "gray"
        else:
            progress_text, progress_color = "No chapter files yet", "gray"
        progress_label = QLabel(progress_text)
        progress_label.setStyleSheet(f"color: {progress_color};")
        top.addWidget(progress_label)

        resume_button = QPushButton("▶ Resume")
        resume_button.clicked.connect(lambda _c=False, bid=book["id"]: self._resume_book_clicked(bid))
        top.addWidget(resume_button)
        if summary["status"] != "empty":
            listened_button = QPushButton(
                "↺ Mark as Unlistened" if summary["status"] == "finished" else "✓ Mark as Listened"
            )
            listened_button.clicked.connect(
                lambda _c=False, bid=book["id"], listened=(summary["status"] != "finished"):
                    self._set_book_listened_clicked(bid, listened)
            )
            top.addWidget(listened_button)
        chat_button = QPushButton("💬 Ask about this book")
        chat_button.clicked.connect(lambda _c=False, b=book, a=author_name: self._open_book_chat(b, a))
        top.addWidget(chat_button)
        edit_button = QPushButton("✎ Edit")
        edit_button.clicked.connect(lambda _c=False, b=book: self._edit_book_clicked(b))
        top.addWidget(edit_button)
        remove_button = QPushButton("✕")
        remove_button.setFixedWidth(28)
        remove_button.clicked.connect(lambda _c=False, b=book: self._remove_book_clicked(b))
        top.addWidget(remove_button)
        row_layout.addLayout(top)

        if expanded:
            files = list_book_files(book["id"])
            if not files:
                empty = QLabel("No chapter files assigned yet.")
                empty.setStyleSheet("color: gray;")
                row_layout.addWidget(empty)
            for record in files:
                self._add_library_file_row(
                    lambda w, rl=row_layout: rl.addWidget(w), record, indent=True, show_unassign=True,
                )

        parent_layout.insertWidget(parent_layout.count() - 1, row)

    def _add_series_section(self, series, author_name, books):
        header = QFrame()
        header.setFrameShape(QFrame.Shape.StyledPanel)
        header_layout = QVBoxLayout(header)
        top = QHBoxLayout()
        expanded = series["id"] in self._expanded_series
        toggle_button = QPushButton("▾" if expanded else "▸")
        toggle_button.setFixedWidth(28)
        toggle_button.clicked.connect(lambda _c=False, sid=series["id"]: self._toggle_series_expanded(sid))
        top.addWidget(toggle_button)
        name_label = QLabel(f'📚 {series["name"]} — {author_name}')
        name_label.setStyleSheet("font-weight: bold;")
        top.addWidget(name_label, 1)
        resume_button = QPushButton("▶ Resume Series")
        resume_button.clicked.connect(lambda _c=False, sid=series["id"]: self._resume_series_clicked(sid))
        top.addWidget(resume_button)
        chat_button = QPushButton("💬 Ask about this series")
        chat_button.clicked.connect(lambda _c=False, s=series, a=author_name: self._open_series_chat(s, a))
        top.addWidget(chat_button)
        edit_button = QPushButton("✎ Edit")
        edit_button.clicked.connect(lambda _c=False, s=series: self._edit_series_clicked(s))
        top.addWidget(edit_button)
        header_layout.addLayout(top)
        if series.get("synopsis"):
            synopsis_label = QLabel(series["synopsis"])
            synopsis_label.setWordWrap(True)
            synopsis_label.setStyleSheet("color: gray;")
            header_layout.addWidget(synopsis_label)
        self.library_list_layout.insertWidget(self.library_list_layout.count() - 1, header)

        if expanded:
            if not books:
                empty = QLabel("No books in this series yet - use + New Book from + Add Folder, or Edit a book.")
                empty.setStyleSheet("color: gray;")
                empty.setContentsMargins(24, 0, 0, 0)
                self.library_list_layout.insertWidget(self.library_list_layout.count() - 1, empty)
            for book in books:
                self._add_book_row(self.library_list_layout, book, author_name, indent=True)

    def _add_unsorted_section(self, unsorted):
        header = QLabel("📥 Unsorted files")
        header.setStyleSheet("font-weight: bold;")
        self.library_list_layout.insertWidget(self.library_list_layout.count() - 1, header)
        for record in unsorted:
            self._add_library_file_row(
                lambda w: self.library_list_layout.insertWidget(self.library_list_layout.count() - 1, w),
                record, indent=False,
            )

    def _refresh_library(self):
        _clear_layout(self.library_list_layout)
        self._library_buttons = {}
        if self._library_kind_filter == "music":
            self._refresh_library_music()
        else:
            self._refresh_library_audiobooks()
        self._sync_row_button_labels()

    def _refresh_library_music(self):
        items = [r for r in list_library_items() if r["kind"] == "music"]
        if not items:
            placeholder = QLabel("No music files yet - use + Add Files or + Add Folder above.")
            placeholder.setStyleSheet("color: gray;")
            self.library_list_layout.insertWidget(self.library_list_layout.count() - 1, placeholder)
        for record in items:
            self._add_library_file_row(
                lambda w: self.library_list_layout.insertWidget(self.library_list_layout.count() - 1, w),
                record, indent=False,
            )

    def _refresh_library_audiobooks(self):
        authors = {a["id"]: a["name"] for a in list_authors()}
        all_series = list_series()
        all_books = list_books()
        search = self._library_search

        def matches(text):
            return not search or search in (text or "").lower()

        books_by_series = {}
        standalone_books = []
        for book in all_books:
            series_id = book.get("series_id")
            if series_id and any(s["id"] == series_id for s in all_series):
                books_by_series.setdefault(series_id, []).append(book)
            else:
                standalone_books.append(book)

        rendered_anything = False

        for series in sorted(all_series, key=lambda s: s["name"].lower()):
            author_name = authors.get(series.get("author_id"), "Unknown author")
            series_books = sorted(books_by_series.get(series["id"], []), key=lambda b: b.get("series_index") or 0)
            series_itself_matches = matches(series["name"]) or matches(author_name) or matches(series.get("synopsis"))
            visible_books = series_books if series_itself_matches else [
                b for b in series_books
                if matches(b["title"]) or matches(authors.get(b.get("author_id"), "")) or matches(b.get("synopsis"))
            ]
            if search and not series_itself_matches and not visible_books:
                continue
            rendered_anything = True
            self._add_series_section(series, author_name, visible_books)

        for book in sorted(standalone_books, key=lambda b: b["title"].lower()):
            author_name = authors.get(book.get("author_id"), "Unknown author")
            if search and not (matches(book["title"]) or matches(author_name) or matches(book.get("synopsis"))):
                continue
            rendered_anything = True
            self._add_book_row(self.library_list_layout, book, author_name, indent=False)

        unsorted = [r for r in list_library_items() if r["kind"] == "audiobook" and not r.get("book_id")]
        visible_unsorted = [r for r in unsorted if matches(r["title"])]
        if visible_unsorted:
            rendered_anything = True
            self._add_unsorted_section(visible_unsorted)

        if not rendered_anything:
            message = f'No matches for "{search}".' if search else \
                "No audiobooks yet - use + Add Files or + Add Folder above."
            placeholder = QLabel(message)
            placeholder.setStyleSheet("color: gray;")
            self.library_list_layout.insertWidget(self.library_list_layout.count() - 1, placeholder)

    def _remove_library_item_clicked(self, record):
        if self._now_playing and self._now_playing["kind"] == "library" and self._now_playing["id"] == record["id"]:
            self._stop_playback()
        remove_library_item(record["id"])
        self.library_status_label.setText(f'Removed "{record["title"]}".')
        self._refresh_library()

    # ------------------------------------------------------------------
    # Soundscapes tab
    # ------------------------------------------------------------------
    def _build_soundscapes_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel("Loopable ambience, generated locally the first time you play one - no internet or files needed.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.soundscape_status_label = QLabel("")
        layout.addWidget(self.soundscape_status_label)

        self.soundscape_scroll, self.soundscape_list_layout = _scroll_list()
        layout.addWidget(self.soundscape_scroll, 1)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        add_row = QHBoxLayout()
        self.custom_soundscape_name_input = QLineEdit()
        self.custom_soundscape_name_input.setPlaceholderText("Name for your own loop")
        add_row.addWidget(self.custom_soundscape_name_input, 1)
        add_button = QPushButton("+ Add Your Own Audio Loop")
        add_button.clicked.connect(self._add_custom_soundscape_clicked)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)
        return page

    def _refresh_soundscapes(self):
        _clear_layout(self.soundscape_list_layout)
        self._soundscape_buttons = {}
        for preset in BUILTIN_SOUNDSCAPES:
            self._add_soundscape_row(preset["id"], preset["name"], preset["description"], is_custom=False)
        for record in list_custom_soundscapes():
            self._add_soundscape_row(record["id"], record["name"], record["path"], is_custom=True, record=record)
        self._sync_row_button_labels()

    def _add_soundscape_row(self, soundscape_id, name, description, is_custom, record=None):
        row = QFrame()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(6, 4, 6, 4)
        top = QHBoxLayout()
        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: bold;")
        top.addWidget(name_label, 1)
        play_button = QPushButton("▶ Play")
        if is_custom:
            play_button.clicked.connect(
                lambda _c=False: self._toggle_row(
                    "soundscape", soundscape_id, lambda: self._play_soundscape(record["path"], name, soundscape_id)
                )
            )
        else:
            play_button.clicked.connect(
                lambda _c=False: self._toggle_row(
                    "soundscape", soundscape_id, lambda: self._play_builtin_soundscape(soundscape_id, name)
                )
            )
        top.addWidget(play_button)
        if is_custom:
            remove_button = QPushButton("✕")
            remove_button.setFixedWidth(28)
            remove_button.clicked.connect(lambda _c=False, r=record: self._remove_custom_soundscape_clicked(r))
            top.addWidget(remove_button)
        row_layout.addLayout(top)
        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: gray;")
        row_layout.addWidget(desc_label)
        self._soundscape_buttons[soundscape_id] = play_button
        self.soundscape_list_layout.insertWidget(self.soundscape_list_layout.count() - 1, row)

    def _play_builtin_soundscape(self, soundscape_id, name):
        cache_path = builtin_soundscape_cache_path(soundscape_id)
        if os.path.isfile(cache_path):
            self._play_soundscape(cache_path, name, soundscape_id)
            return
        button = self._soundscape_buttons.get(soundscape_id)
        self.soundscape_status_label.setText(f'Generating "{name}" loop (one-time, a few seconds)...')
        if button:
            button.setEnabled(False)

        def work():
            return generate_soundscape_wav(soundscape_id)

        def handle(path):
            if button:
                button.setEnabled(True)
            self.soundscape_status_label.setText("")
            self._play_soundscape(path, name, soundscape_id)

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._soundscape_gen_worker = worker
        worker.start()

    def _add_custom_soundscape_clicked(self):
        name = self.custom_soundscape_name_input.text().strip()
        if not name:
            self.soundscape_status_label.setText("Enter a name for the loop first.")
            return
        filter_str = "Audio files (*" + " *".join(sorted(AUDIO_EXTENSIONS)) + ")"
        path, _filter = QFileDialog.getOpenFileName(self, "Choose an audio file to loop", "", filter_str)
        if not path:
            return
        try:
            add_custom_soundscape(name, path)
        except ValueError as exc:
            self.soundscape_status_label.setText(str(exc))
            return
        self.custom_soundscape_name_input.clear()
        self.soundscape_status_label.setText(f'Added "{name}".')
        self._refresh_soundscapes()

    def _remove_custom_soundscape_clicked(self, record):
        if self._now_playing and self._now_playing["kind"] == "soundscape" and self._now_playing["id"] == record["id"]:
            self._stop_playback()
        remove_custom_soundscape(record["id"])
        self.soundscape_status_label.setText(f'Removed "{record["name"]}".')
        self._refresh_soundscapes()
