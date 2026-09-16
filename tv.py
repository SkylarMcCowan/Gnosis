"""TV pane: internet TV via a free, public IPTV channel directory
(iptv-org's static JSON API - https://github.com/iptv-org/iptv), embedded as
a "📺 TV" tab inside the Radio pane (radio.py).

Own module rather than folding into radio.py: video playback needs its own
QMediaPlayer + QVideoWidget (radio.py's shared transport bar is audio-only),
and the channel guide is a different kind of catalog than radio.py's
stations/library/soundscapes.

Channel guide: iptv-org publishes channels.json (name/country/category
metadata), streams.json (playable URLs, joined to a channel by id - many
have no channel id and are kept as standalone entries), countries.json,
categories.json (human-readable category names) and logos.json (channel
artwork). The combined catalog is ~20MB, so it's cached to disk
(core_config.path("tv")/catalog_cache.json) and only re-downloaded when the
cache is missing/stale or the user hits "Refresh Guide" - never fetched
automatically on startup, so opening the app/pane never makes a surprise
network call. A stale cache is still shown with its real last-updated date
rather than hidden, and a missing cache with no network is surfaced as an
explicit error rather than an empty guide silently pretending to be
complete.

Streams are third-party HLS feeds of varying quality/uptime, so playback
automatically tries the next known stream/quality for a channel on error
(announced in the status text, never silent) before giving up.

Fullscreen is handled manually (a dedicated top-level window the video
widget is reparented into, closed via Escape/double-click/button) rather
than QVideoWidget's own setFullScreen() - that call reparents the widget
into Qt's own fullscreen window internally and, on this platform, could get
stuck there with no way back to the embedded pane.
"""
import hashlib
import json
import os
import time
import uuid

import requests
from PyQt6.QtCore import QThread, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSlider, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from core import config as core_config

_CHANNELS_URL = "https://iptv-org.github.io/api/channels.json"
_STREAMS_URL = "https://iptv-org.github.io/api/streams.json"
_COUNTRIES_URL = "https://iptv-org.github.io/api/countries.json"
_CATEGORIES_URL = "https://iptv-org.github.io/api/categories.json"
_LOGOS_URL = "https://iptv-org.github.io/api/logos.json"
_CACHE_MAX_AGE_S = 7 * 24 * 3600
_HISTORY_LIMIT = 20
_HEADERS = {"User-Agent": "GnosisTV/1.0 (personal desktop app)"}


# ----------------------------------------------------------------------
# Channel guide catalog - cached on disk, network only on explicit request
# ----------------------------------------------------------------------
def _tv_dir():
    return core_config.path("tv")


def _catalog_cache_path():
    return os.path.join(_tv_dir(), "catalog_cache.json")


def load_cached_catalog():
    """Returns the on-disk cached catalog with no network access, or None if
    nothing has been cached yet (or the cache is corrupt)."""
    path = _catalog_cache_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_catalog(force=False):
    """Returns the channel/stream/country/category/logo catalog, downloading
    a fresh copy when the cache is missing, older than _CACHE_MAX_AGE_S, or
    `force` is set. If a download is needed and the network call fails,
    falls back to an existing (stale) cache rather than erroring - that's
    still real, dated data, not a guess. Raises requests.RequestException if
    a download is needed and there's no cache at all to fall back on, so the
    caller surfaces that as an explicit error instead of showing an empty
    guide."""
    cached = load_cached_catalog()
    if cached and not force and (time.time() - cached.get("fetched_at", 0) < _CACHE_MAX_AGE_S):
        return cached
    try:
        channels = requests.get(_CHANNELS_URL, headers=_HEADERS, timeout=30).json()
        streams = requests.get(_STREAMS_URL, headers=_HEADERS, timeout=30).json()
        countries = requests.get(_COUNTRIES_URL, headers=_HEADERS, timeout=30).json()
        categories = requests.get(_CATEGORIES_URL, headers=_HEADERS, timeout=30).json()
        logos = requests.get(_LOGOS_URL, headers=_HEADERS, timeout=30).json()
    except (requests.RequestException, ValueError):
        if cached:
            return cached
        raise
    catalog = {
        "fetched_at": time.time(), "channels": channels, "streams": streams,
        "countries": countries, "categories": categories, "logos": logos,
    }
    os.makedirs(_tv_dir(), exist_ok=True)
    with open(_catalog_cache_path(), "w", encoding="utf-8") as f:
        json.dump(catalog, f)
    return catalog


def build_channel_index(catalog):
    """Merges the catalog into one searchable list of {"name", "country",
    "categories", "logo_url", "streams": [{"url","quality","title"}]}
    entries, dropping closed/NSFW channels and any stream with no url.
    Streams with no channel id become their own standalone entry (keyed by
    stream title) rather than being discarded, since plenty of iptv-org
    entries are like that - they just won't have a logo or country."""
    countries_by_code = {c["code"]: c["name"] for c in catalog.get("countries", [])}
    logos_by_channel = {}
    for logo in catalog.get("logos", []):
        channel_id = logo.get("channel")
        if channel_id and not logo.get("feed") and channel_id not in logos_by_channel:
            logos_by_channel[channel_id] = logo.get("url") or None

    entries = {}
    for channel in catalog.get("channels", []):
        if channel.get("closed") or channel.get("is_nsfw"):
            continue
        entries[channel["id"]] = {
            "name": channel.get("name") or channel["id"],
            "country": countries_by_code.get(channel.get("country"), channel.get("country") or ""),
            "categories": channel.get("categories") or [],
            "logo_url": logos_by_channel.get(channel["id"]),
            "streams": [],
        }
    standalone_n = 0
    for stream in catalog.get("streams", []):
        url = stream.get("url")
        if not url:
            continue
        channel_id = stream.get("channel")
        stream_entry = {"url": url, "quality": stream.get("quality") or "", "title": stream.get("title") or ""}
        if channel_id and channel_id in entries:
            entries[channel_id]["streams"].append(stream_entry)
        elif not channel_id and stream.get("title"):
            standalone_n += 1
            entries[f"_standalone_{standalone_n}"] = {
                "name": stream["title"], "country": "", "categories": [], "logo_url": None,
                "streams": [stream_entry],
            }
    return [entry for entry in entries.values() if entry["streams"]]


def category_labels(catalog):
    return {c["id"]: c["name"] for c in catalog.get("categories", [])}


def search_tv_channels(index, query="", category=None, country=None, limit=60):
    """Matches `query` against channel name (best), then country, then
    category, case-insensitively, restricted to `category`/`country` when
    given. With no query but a category/country picked, browses that filter
    alphabetically instead of requiring free text. With no query and no
    filter, returns nothing rather than dumping the whole ~12k-entry guide.
    Returns (results, total_matched) so the caller can show "showing N of
    M" when the match count exceeds `limit`."""
    query = (query or "").strip().lower()
    filtered = index
    if category:
        filtered = [e for e in filtered if category in e["categories"]]
    if country:
        filtered = [e for e in filtered if e["country"] == country]
    if not query:
        if not (category or country):
            return [], 0
        ordered = sorted(filtered, key=lambda e: e["name"].lower())
        return ordered[:limit], len(ordered)
    scored = []
    for entry in filtered:
        name_lower = entry["name"].lower()
        if query in name_lower:
            score = 0 if name_lower.startswith(query) else 1
        elif query in entry["country"].lower():
            score = 2
        elif any(query in cat.lower() for cat in entry["categories"]):
            score = 3
        else:
            continue
        scored.append((score, name_lower, entry))
    scored.sort(key=lambda t: (t[0], t[1]))
    total = len(scored)
    return [entry for _, _, entry in scored[:limit]], total


# ----------------------------------------------------------------------
# Channel logo cache - fetched lazily per visible row, cached indefinitely
# (logos rarely change) so repeat views never re-download.
# ----------------------------------------------------------------------
def _logo_cache_dir():
    return os.path.join(_tv_dir(), "logo_cache")


def fetch_logo_path(url):
    """Downloads and disk-caches a channel logo image, returning the local
    path, or None on a missing url or failed download - a missing logo just
    means no icon is shown, never a broken-image placeholder."""
    if not url:
        return None
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()
    ext = os.path.splitext(url.split("?")[0])[1][:5] or ".img"
    path = os.path.join(_logo_cache_dir(), digest + ext)
    if os.path.isfile(path):
        return path
    try:
        response = requests.get(url, headers=_HEADERS, timeout=6)
        response.raise_for_status()
    except requests.RequestException:
        return None
    os.makedirs(_logo_cache_dir(), exist_ok=True)
    with open(path, "wb") as f:
        f.write(response.content)
    return path


# ----------------------------------------------------------------------
# Saved channels - same shape/convention as radio.py's saved stations
# ----------------------------------------------------------------------
def _saved_channels_path():
    return os.path.join(_tv_dir(), "saved_channels.json")


def list_saved_channels():
    path = _saved_channels_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return records if isinstance(records, list) else []


def _save_saved_channels(records):
    path = _saved_channels_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


def add_saved_channel(name, stream_url, country="", quality="", logo_url=""):
    name = (name or "").strip()
    stream_url = (stream_url or "").strip()
    if not name or not stream_url:
        raise ValueError("A channel needs both a name and a stream URL.")
    records = list_saved_channels()
    if any(r["stream_url"] == stream_url for r in records):
        raise ValueError(f'"{name}" is already in your saved channels.')
    record = {
        "id": uuid.uuid4().hex[:8], "name": name, "stream_url": stream_url,
        "country": country, "quality": quality, "logo_url": logo_url or "",
    }
    records.append(record)
    _save_saved_channels(records)
    return record


def remove_saved_channel(channel_id):
    records = list_saved_channels()
    remaining = [r for r in records if r.get("id") != channel_id]
    if len(remaining) == len(records):
        return False
    _save_saved_channels(remaining)
    return True


# ----------------------------------------------------------------------
# Recently watched - a lightweight, separate history from saved favorites,
# capped at _HISTORY_LIMIT and reordered to most-recent-first on replay.
# Only ever written once a stream actually starts playing (see
# TVWidget._on_playback_state_changed), never for a candidate that errored
# out during the auto-retry fallback.
# ----------------------------------------------------------------------
def _history_path():
    return os.path.join(_tv_dir(), "watch_history.json")


def list_watch_history():
    path = _history_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return records if isinstance(records, list) else []


def _save_watch_history(records):
    path = _history_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


def record_watch_history(name, stream_url, country="", quality="", logo_url=""):
    records = [r for r in list_watch_history() if r.get("stream_url") != stream_url]
    records.insert(0, {
        "id": uuid.uuid4().hex[:8], "name": name, "stream_url": stream_url,
        "country": country, "quality": quality, "logo_url": logo_url or "",
        "watched_at": time.time(),
    })
    _save_watch_history(records[:_HISTORY_LIMIT])


def clear_watch_history():
    _save_watch_history([])


def remove_watch_history_entry(entry_id):
    records = list_watch_history()
    remaining = [r for r in records if r.get("id") != entry_id]
    if len(remaining) == len(records):
        return False
    _save_watch_history(remaining)
    return True


# ----------------------------------------------------------------------
# Widget infra - own copies of the small helpers radio.py/weather_station.py
# also define locally (repo convention: duplicate rather than share a util)
# ----------------------------------------------------------------------
class _CatalogWorker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as exc:
            self.failed.emit(str(exc))


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


def _make_icon_label():
    label = QLabel()
    label.setFixedSize(28, 28)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


class _ClickableVideoWidget(QVideoWidget):
    """Plain QVideoWidget plus a double-click-to-fullscreen signal - its own
    setFullScreen() is deliberately never used (see module docstring)."""
    doubleClicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class _FullscreenVideoWindow(QWidget):
    """A dedicated top-level window the video widget is temporarily
    reparented into for fullscreen playback. Closing it (Escape,
    double-click, or the caller) always reparents the video widget back -
    there's no code path that leaves it stranded in its own window."""
    closed = pyqtSignal()

    def __init__(self, video_widget):
        super().__init__()
        self.setWindowFlag(Qt.WindowType.Window)
        self.setStyleSheet("background-color: black;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(video_widget)

    def mouseDoubleClickEvent(self, event):
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


class TVWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._index = []
        self._category_labels = {}
        self._catalog_fetched_at = None
        self._playing_url = None
        self._current_stream_urls = []
        self._current_stream_index = 0
        self._current_channel_name = ""
        self._current_channel_meta = {}
        self._saved_buttons = {}
        self._history_buttons = {}
        self._logo_workers = set()
        self._catalog_worker = None
        self._fullscreen_window = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(15, 15, 15, 15)
        outer.setSpacing(10)

        title = QLabel("📺 TV")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        outer.addWidget(title)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('Search channels, e.g. "BBC", "France", "news"')
        self.search_input.returnPressed.connect(self._search_clicked)
        search_row.addWidget(self.search_input, 1)
        search_button = QPushButton("🔍 Search")
        search_button.clicked.connect(self._search_clicked)
        search_row.addWidget(search_button)
        outer.addLayout(search_row)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Category"))
        self.category_combo = QComboBox()
        self.category_combo.setMinimumWidth(140)
        self.category_combo.currentIndexChanged.connect(self._filters_changed)
        filter_row.addWidget(self.category_combo, 1)
        filter_row.addWidget(QLabel("Country"))
        self.country_combo = QComboBox()
        self.country_combo.setMinimumWidth(140)
        self.country_combo.currentIndexChanged.connect(self._filters_changed)
        filter_row.addWidget(self.country_combo, 1)
        refresh_button = QPushButton("🔄 Refresh Guide")
        refresh_button.clicked.connect(self._refresh_guide_clicked)
        filter_row.addWidget(refresh_button)
        outer.addLayout(filter_row)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        search_section = QWidget()
        search_layout = QVBoxLayout(search_section)
        search_layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel("Channel guide not loaded yet - search or pick a filter above to fetch it (~20 MB, one-time).")
        self.status_label.setWordWrap(True)
        search_layout.addWidget(self.status_label)
        self.results_scroll, self.results_layout = _scroll_list()
        search_layout.addWidget(self.results_scroll)
        splitter.addWidget(search_section)

        bottom_tabs = QTabWidget()
        saved_section = QWidget()
        saved_layout = QVBoxLayout(saved_section)
        saved_layout.setContentsMargins(0, 0, 0, 0)
        self.saved_scroll, self.saved_layout = _scroll_list()
        saved_layout.addWidget(self.saved_scroll)
        bottom_tabs.addTab(saved_section, "⭐ Saved")

        history_section = QWidget()
        history_layout = QVBoxLayout(history_section)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_header = QHBoxLayout()
        history_header.addStretch()
        clear_history_button = QPushButton("Clear History")
        clear_history_button.clicked.connect(self._clear_history_clicked)
        history_header.addWidget(clear_history_button)
        history_layout.addLayout(history_header)
        self.history_scroll, self.history_layout = _scroll_list()
        history_layout.addWidget(self.history_scroll)
        bottom_tabs.addTab(history_section, "🕓 Recently Watched")
        splitter.addWidget(bottom_tabs)

        splitter.addWidget(self._build_player())

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([320, 160, 220])
        outer.addWidget(splitter, 1)

        self._refresh_saved_channels()
        self._refresh_watch_history()
        self._load_cache_only()

    # ------------------------------------------------------------------
    # Video player - own QMediaPlayer/QVideoWidget, separate from
    # radio.py's audio-only transport bar
    # ------------------------------------------------------------------
    def _build_player(self):
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        self._video_container_layout = layout

        self.video_widget = _ClickableVideoWidget()
        self.video_widget.setMinimumHeight(90)
        self.video_widget.setStyleSheet("background-color: black;")
        self.video_widget.doubleClicked.connect(self._toggle_fullscreen)
        layout.addWidget(self.video_widget, 1)

        self._media_player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(0.7)
        self._media_player.setAudioOutput(self._audio_output)
        self._media_player.setVideoOutput(self.video_widget)
        self._media_devices = QMediaDevices(self)
        self._media_devices.audioOutputsChanged.connect(self._on_audio_outputs_changed)
        self._media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._media_player.errorOccurred.connect(self._on_player_error)

        self.now_playing_label = QLabel("Nothing playing.")
        layout.addWidget(self.now_playing_label)

        controls_row = QHBoxLayout()
        self.play_pause_button = QPushButton("▶ Play")
        self.play_pause_button.setEnabled(False)
        self.play_pause_button.clicked.connect(self._toggle_play_pause)
        controls_row.addWidget(self.play_pause_button)
        self.stop_button = QPushButton("■ Stop")
        self.stop_button.clicked.connect(self._stop_playback)
        controls_row.addWidget(self.stop_button)
        self.fullscreen_button = QPushButton("⛶ Fullscreen")
        self.fullscreen_button.clicked.connect(self._toggle_fullscreen)
        controls_row.addWidget(self.fullscreen_button)
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
        return frame

    def _toggle_play_pause(self):
        state = self._media_player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._media_player.play()

    def _stop_playback(self):
        if self._fullscreen_window is not None:
            self._fullscreen_window.close()
        self._media_player.stop()
        self._playing_url = None
        self._current_stream_urls = []
        self._current_stream_index = 0
        self._current_channel_name = ""
        self._current_channel_meta = {}
        self.now_playing_label.setText("Nothing playing.")
        self.play_pause_button.setEnabled(False)
        self._sync_playback_button_labels()

    # ------------------------------------------------------------------
    # Fullscreen - manual top-level window, see module docstring for why
    # ------------------------------------------------------------------
    def _toggle_fullscreen(self):
        if self._fullscreen_window is not None:
            self._fullscreen_window.close()
            return
        self._video_container_layout.removeWidget(self.video_widget)
        window = _FullscreenVideoWindow(self.video_widget)
        window.closed.connect(self._on_fullscreen_closed)
        self._fullscreen_window = window
        window.showFullScreen()
        window.setFocus()

    def _on_fullscreen_closed(self):
        self._fullscreen_window = None
        self._video_container_layout.insertWidget(0, self.video_widget)
        self.video_widget.show()

    def _on_playback_state_changed(self, state):
        self.play_pause_button.setText(
            "⏸ Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "▶ Play"
        )
        if state == QMediaPlayer.PlaybackState.PlayingState and self._playing_url:
            record_watch_history(
                self._current_channel_name, self._playing_url,
                country=self._current_channel_meta.get("country", ""),
                quality=self._current_channel_meta.get("quality", ""),
                logo_url=self._current_channel_meta.get("logo_url", ""),
            )
            self._refresh_watch_history()
        self._sync_playback_button_labels()

    def _on_player_error(self, error, error_string):
        if error == QMediaPlayer.Error.NoError:
            return
        if self._current_stream_index + 1 < len(self._current_stream_urls):
            self._current_stream_index += 1
            total = len(self._current_stream_urls)
            self.now_playing_label.setText(
                f"⚠ {self._current_channel_name}: stream failed ({error_string}) - "
                f"trying next stream ({self._current_stream_index + 1}/{total})..."
            )
            self._start_current_stream()
        else:
            self.now_playing_label.setText(f"⚠ {self._current_channel_name}: {error_string}")

    def _on_audio_outputs_changed(self):
        self._audio_output.setDevice(QMediaDevices.defaultAudioOutput())

    def _play_channel(self, name, stream_urls, country="", quality="", logo_url=""):
        """stream_urls: ordered candidates, first preferred. On playback
        error the player automatically advances to the next one (status
        text announces it) rather than just failing - these are unreliable
        third-party feeds."""
        self._current_stream_urls = list(stream_urls)
        self._current_stream_index = 0
        self._current_channel_name = name
        self._current_channel_meta = {"country": country, "quality": quality, "logo_url": logo_url}
        self._start_current_stream()

    def _start_current_stream(self):
        url = self._current_stream_urls[self._current_stream_index]
        self._media_player.stop()
        self._playing_url = url
        self.now_playing_label.setText(f"📺 {self._current_channel_name}")
        self.play_pause_button.setEnabled(True)
        self._media_player.setSource(QUrl(url))
        self._media_player.play()
        self._sync_playback_button_labels()

    def _sync_playback_button_labels(self):
        playing = self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        for group in (self._saved_buttons, self._history_buttons):
            for url, button in group.items():
                button.setText("⏹ Stop" if (playing and url == self._playing_url) else "▶ Play")

    def _load_logo_async(self, url, icon_label):
        if not url:
            return

        def handle(path):
            self._logo_workers.discard(worker)
            if not path:
                return
            try:
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    icon_label.setPixmap(pixmap.scaled(
                        28, 28, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                    ))
            except RuntimeError:
                pass  # row was already discarded by a newer search/refresh

        worker = _CatalogWorker(lambda u=url: fetch_logo_path(u))
        worker.done.connect(handle)
        self._logo_workers.add(worker)
        worker.start()

    # ------------------------------------------------------------------
    # Channel guide loading/searching
    # ------------------------------------------------------------------
    def _load_cache_only(self):
        """Populates the index from disk cache at startup - no network, so
        opening this pane never makes a surprise request."""
        def work():
            cached = load_cached_catalog()
            if cached is None:
                return None
            return cached, build_channel_index(cached)

        def handle(result):
            if result is None:
                return
            self._apply_catalog(*result)

        worker = _CatalogWorker(work)
        worker.done.connect(handle)
        self._catalog_worker = worker
        worker.start()

    def _load_index(self, force, on_done=None):
        self.status_label.setText("Refreshing channel guide..." if force else "Loading channel guide...")

        def work():
            catalog = refresh_catalog(force=force)
            return catalog, build_channel_index(catalog)

        def handle(result):
            self._apply_catalog(*result)
            if on_done:
                on_done()

        def failed(message):
            self.status_label.setText(f"Couldn't load the channel guide: {message}")

        worker = _CatalogWorker(work)
        worker.done.connect(handle)
        worker.failed.connect(failed)
        self._catalog_worker = worker
        worker.start()

    def _apply_catalog(self, catalog, index):
        self._index = index
        self._category_labels = category_labels(catalog)
        self._catalog_fetched_at = catalog.get("fetched_at")
        self._populate_filters()
        updated = (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(self._catalog_fetched_at))
            if self._catalog_fetched_at else "unknown"
        )
        self.status_label.setText(f"{len(self._index)} channel(s) available. Guide last updated {updated}.")

    def _populate_filters(self):
        categories_present = sorted({cat for e in self._index for cat in e["categories"]})
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("All categories", None)
        for cat_id in categories_present:
            self.category_combo.addItem(self._category_labels.get(cat_id, cat_id.title()), cat_id)
        self.category_combo.blockSignals(False)

        countries_present = sorted({e["country"] for e in self._index if e["country"]})
        self.country_combo.blockSignals(True)
        self.country_combo.clear()
        self.country_combo.addItem("All countries", None)
        for country in countries_present:
            self.country_combo.addItem(country, country)
        self.country_combo.blockSignals(False)

    def _refresh_guide_clicked(self):
        self._load_index(force=True)

    def _filters_changed(self, _index=None):
        if not self._index:
            return
        self._run_search(self.search_input.text().strip())

    def _search_clicked(self):
        query = self.search_input.text().strip()
        category = self.category_combo.currentData() if self._index else None
        country = self.country_combo.currentData() if self._index else None
        if not query and not category and not country:
            self.status_label.setText("Enter a search term or choose a category/country filter.")
            return
        if not self._index:
            self._load_index(force=False, on_done=lambda: self._run_search(query))
            return
        self._run_search(query)

    def _run_search(self, query):
        category = self.category_combo.currentData()
        country = self.country_combo.currentData()
        results, total = search_tv_channels(self._index, query, category=category, country=country)
        _clear_layout(self.results_layout)
        if not total:
            self.status_label.setText("No channels matched - try a different term or filter.")
            return
        shown = len(results)
        suffix = f" - showing first {shown}" if total > shown else ""
        self.status_label.setText(f"{total} channel(s) matched{suffix}.")
        for entry in results:
            self._add_result_row(entry)

    def _add_result_row(self, entry):
        row = QFrame()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(6, 4, 6, 4)
        top = QHBoxLayout()
        icon_label = _make_icon_label()
        top.addWidget(icon_label)
        name_label = QLabel(entry["name"])
        name_label.setStyleSheet("font-weight: bold;")
        top.addWidget(name_label, 1)

        quality_combo = QComboBox()
        for stream in entry["streams"]:
            quality_combo.addItem(stream["quality"] or stream["title"] or "stream", stream["url"])
        top.addWidget(quality_combo)

        play_button = QPushButton("▶ Play")
        play_button.clicked.connect(
            lambda _c=False, e=entry, combo=quality_combo: self._play_result_clicked(e, combo)
        )
        top.addWidget(play_button)
        add_button = QPushButton("+ Save")
        add_button.clicked.connect(
            lambda _c=False, e=entry, combo=quality_combo: self._save_result_clicked(e, combo)
        )
        top.addWidget(add_button)
        row_layout.addLayout(top)

        detail_bits = [bit for bit in (entry["country"], ", ".join(entry["categories"])) if bit]
        if detail_bits:
            detail_label = QLabel(" · ".join(detail_bits))
            detail_label.setStyleSheet("color: gray;")
            row_layout.addWidget(detail_label)
        self.results_layout.insertWidget(self.results_layout.count() - 1, row)
        self._load_logo_async(entry.get("logo_url"), icon_label)

    def _play_result_clicked(self, entry, quality_combo):
        urls = [s["url"] for s in entry["streams"]]
        chosen = quality_combo.currentData()
        if chosen in urls:
            urls.remove(chosen)
        urls.insert(0, chosen)
        self._play_channel(
            entry["name"], urls, country=entry["country"],
            quality=quality_combo.currentText(), logo_url=entry.get("logo_url") or "",
        )

    def _save_result_clicked(self, entry, quality_combo):
        try:
            add_saved_channel(
                entry["name"], quality_combo.currentData(), country=entry["country"],
                quality=quality_combo.currentText(), logo_url=entry.get("logo_url") or "",
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._refresh_saved_channels()

    # ------------------------------------------------------------------
    # Saved channels / recently watched - same row shape, one stored URL
    # each (no auto-retry fallback list, unlike a fresh search result)
    # ------------------------------------------------------------------
    def _refresh_saved_channels(self):
        _clear_layout(self.saved_layout)
        self._saved_buttons = {}
        records = list_saved_channels()
        if not records:
            placeholder = QLabel("No saved channels yet - search above and hit + Save.")
            placeholder.setStyleSheet("color: gray;")
            self.saved_layout.insertWidget(self.saved_layout.count() - 1, placeholder)
            return
        for record in records:
            row = QFrame()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 4, 6, 4)
            icon_label = _make_icon_label()
            row_layout.addWidget(icon_label)
            label_bits = [record["name"]]
            if record.get("country"):
                label_bits.append(record["country"])
            if record.get("quality"):
                label_bits.append(record["quality"])
            row_layout.addWidget(QLabel(" · ".join(label_bits)), 1)
            play_button = QPushButton("▶ Play")
            play_button.clicked.connect(lambda _c=False, r=record: self._toggle_playback_record(r))
            row_layout.addWidget(play_button)
            self._saved_buttons[record["stream_url"]] = play_button
            remove_button = QPushButton("🗑")
            remove_button.clicked.connect(lambda _c=False, r=record: self._remove_saved_clicked(r))
            row_layout.addWidget(remove_button)
            self.saved_layout.insertWidget(self.saved_layout.count() - 1, row)
            self._load_logo_async(record.get("logo_url"), icon_label)
        self._sync_playback_button_labels()

    def _remove_saved_clicked(self, record):
        remove_saved_channel(record["id"])
        if self._playing_url == record["stream_url"]:
            self._stop_playback()
        self._refresh_saved_channels()

    def _refresh_watch_history(self):
        _clear_layout(self.history_layout)
        self._history_buttons = {}
        records = list_watch_history()
        if not records:
            placeholder = QLabel("Nothing watched yet.")
            placeholder.setStyleSheet("color: gray;")
            self.history_layout.insertWidget(self.history_layout.count() - 1, placeholder)
            return
        for record in records:
            row = QFrame()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 4, 6, 4)
            icon_label = _make_icon_label()
            row_layout.addWidget(icon_label)
            label_bits = [record["name"]]
            if record.get("country"):
                label_bits.append(record["country"])
            row_layout.addWidget(QLabel(" · ".join(label_bits)), 1)
            play_button = QPushButton("▶ Play")
            play_button.clicked.connect(lambda _c=False, r=record: self._toggle_playback_record(r))
            row_layout.addWidget(play_button)
            self._history_buttons[record["stream_url"]] = play_button
            save_button = QPushButton("+ Save")
            save_button.clicked.connect(lambda _c=False, r=record: self._save_from_history_clicked(r))
            row_layout.addWidget(save_button)
            remove_button = QPushButton("✕")
            remove_button.setFixedWidth(28)
            remove_button.clicked.connect(lambda _c=False, r=record: self._remove_history_entry_clicked(r))
            row_layout.addWidget(remove_button)
            self.history_layout.insertWidget(self.history_layout.count() - 1, row)
            self._load_logo_async(record.get("logo_url"), icon_label)
        self._sync_playback_button_labels()

    def _toggle_playback_record(self, record):
        playing = self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if playing and self._playing_url == record["stream_url"]:
            self._stop_playback()
        else:
            self._play_channel(
                record["name"], [record["stream_url"]], country=record.get("country", ""),
                quality=record.get("quality", ""), logo_url=record.get("logo_url", ""),
            )

    def _save_from_history_clicked(self, record):
        try:
            add_saved_channel(
                record["name"], record["stream_url"], country=record.get("country", ""),
                quality=record.get("quality", ""), logo_url=record.get("logo_url", ""),
            )
        except ValueError as exc:
            self.now_playing_label.setText(str(exc))
            return
        self._refresh_saved_channels()

    def _remove_history_entry_clicked(self, record):
        remove_watch_history_entry(record["id"])
        self._refresh_watch_history()

    def _clear_history_clicked(self):
        clear_watch_history()
        self._refresh_watch_history()
