"""Satellite tab: live full-disk imagery of the whole Earth from four
independent, keyless sources, each verified live before wiring in -

- GOES-19 (East, Americas) / GOES-18 (West, Pacific) - NOAA STAR's public
  CDN mirrors each satellite's GeoColor composite as a single static
  full-disk JPEG, refreshed ~every 10 minutes. Not tile-based - there's
  nothing to pan/zoom, just a photo.
- Himawari-9 (Asia-Pacific/Australia) - NICT's public real-time system
  (the same one the open-source `himawaripy` project uses) publishes the
  latest full disk as a grid of small tiles rather than one image; this
  composites the 4x4/550px grid (2200x2200 total) into one QImage.
- NASA EPIC (DSCOVR, whole *sunlit* Earth disk from the L1 point, ~1
  million miles out) - a handful of images a day, each labeled with its
  own real capture time so staleness is always visible rather than
  implied to be "now".

Each view fetches and fails independently - no fallback to a different
source or a stale image on failure (see MEMORY: "No silent fallbacks");
a failed fetch surfaces its own explicit status message.

Deliberately NOT included: EUMETSAT/Meteosat (Europe/Africa/Middle East/
Atlantic coverage) - no confirmed keyless full-disk endpoint was found
before writing this (their real-time-imagery page 403'd, and their actual
API needs a registered account), so it's left out rather than guessed at.
"""
from datetime import datetime, timezone

import requests
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

_HEADERS = {"User-Agent": "GnosisWeatherStation/1.0 (personal desktop app)"}

GOES_SATELLITES = {
    "goes_east": "GOES19",
    "goes_west": "GOES18",
}
GOES_IMAGE_SIZE = "1808x1808"

HIMAWARI_GRID = 4  # 4x4 tiles -> 2200x2200 composite (matches GOES's rough size)
HIMAWARI_TILE_SIZE = 550

VIEWS = {
    "goes_east": "🌎 GOES-East (Americas)",
    "goes_west": "🌎 GOES-West (Pacific)",
    "himawari": "🌏 Himawari-9 (Asia-Pacific)",
    "epic": "🌐 Whole Earth (EPIC)",
}

_AUTO_REFRESH_MS = 10 * 60 * 1000  # matches GOES/Himawari's real refresh cadence


# ----------------------------------------------------------------------
# Backend
# ----------------------------------------------------------------------
def goes_image_url(view_id, size=GOES_IMAGE_SIZE):
    return f"https://cdn.star.nesdis.noaa.gov/{GOES_SATELLITES[view_id]}/ABI/FD/GEOCOLOR/{size}.jpg"


def fetch_goes_image(view_id):
    """Raw JPEG bytes of the latest full-disk GeoColor composite, or None
    on failure. NOAA STAR's CDN doesn't expose a capture timestamp in the
    response (only baked into the image itself as a text overlay), so
    callers show "refreshes ~every 10 min" rather than claiming an exact
    time they don't actually have."""
    try:
        response = requests.get(goes_image_url(view_id), headers=_HEADERS, timeout=15)
        response.raise_for_status()
        return response.content
    except requests.RequestException:
        return None


def fetch_himawari_latest_info():
    """NICT's real-time index of the most recent timestamp with tiles
    available. Returns {"captured_at": aware datetime} or None on
    failure."""
    try:
        response = requests.get(
            "https://himawari8-dl.nict.go.jp/himawari8/img/D531106/latest.json",
            headers=_HEADERS, timeout=10,
        )
        response.raise_for_status()
        captured_at = datetime.strptime(response.json()["date"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return {"captured_at": captured_at}
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


def himawari_tile_url(captured_at, x, y):
    return (
        f"https://himawari8-dl.nict.go.jp/himawari8/img/D531106/{HIMAWARI_GRID}d/{HIMAWARI_TILE_SIZE}/"
        f"{captured_at.strftime('%Y/%m/%d/%H%M%S')}_{x}_{y}.png"
    )


def fetch_himawari_tile(captured_at, x, y):
    try:
        response = requests.get(himawari_tile_url(captured_at, x, y), headers=_HEADERS, timeout=15)
        response.raise_for_status()
        return response.content
    except requests.RequestException:
        return None


def fetch_himawari_composite(captured_at):
    """Downloads and pastes the full HIMAWARI_GRID x HIMAWARI_GRID tile
    set into one QImage (never QPixmap - QPixmap depends on the GUI
    thread's paint engine and this runs on a worker thread; QImage is the
    Qt type explicitly meant for off-thread manipulation). Returns None if
    any tile fails, since a partially-composited disk would misrepresent
    what's actually there instead of surfacing the failure."""
    composite = QImage(
        HIMAWARI_GRID * HIMAWARI_TILE_SIZE, HIMAWARI_GRID * HIMAWARI_TILE_SIZE, QImage.Format.Format_RGB32
    )
    composite.fill(Qt.GlobalColor.black)
    painter = QPainter(composite)
    try:
        for x in range(HIMAWARI_GRID):
            for y in range(HIMAWARI_GRID):
                tile_bytes = fetch_himawari_tile(captured_at, x, y)
                if tile_bytes is None:
                    return None
                tile_image = QImage()
                tile_image.loadFromData(tile_bytes)
                painter.drawImage(x * HIMAWARI_TILE_SIZE, y * HIMAWARI_TILE_SIZE, tile_image)
    finally:
        painter.end()
    return composite


def fetch_epic_latest():
    """Latest NASA EPIC natural-color full-disk image's metadata + a
    constructed image URL. The API returns every image captured on the
    most recent date it has data for, oldest first, so [-1] is the most
    recent - which can genuinely be a day or more old (real EPIC
    processing latency, not a bug), always reported via captured_at rather
    than assumed to be "now". Returns None on failure."""
    try:
        response = requests.get("https://epic.gsfc.nasa.gov/api/natural", headers=_HEADERS, timeout=10)
        response.raise_for_status()
        images = response.json()
        if not images:
            return None
        latest = images[-1]
        date_path = latest["date"].split(" ")[0].replace("-", "/")
        captured_at = datetime.strptime(latest["date"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return {
            "image_url": f"https://epic.gsfc.nasa.gov/archive/natural/{date_path}/png/{latest['image']}.png",
            "captured_at": captured_at,
        }
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return None


def fetch_epic_image(image_url):
    try:
        response = requests.get(image_url, headers=_HEADERS, timeout=15)
        response.raise_for_status()
        return response.content
    except requests.RequestException:
        return None


# ----------------------------------------------------------------------
# Widget
# ----------------------------------------------------------------------
class _FetchWorker(QThread):
    """Runs one zero-arg callable off the GUI thread - duplicated locally
    rather than imported from weather_station.py, which imports this
    module (see weather_station.py's own _FetchWorker docstring for the
    same rationale)."""
    result_ready = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        self.result_ready.emit(self.fn())


class SatelliteWidget(QWidget):
    """A row of mutually-exclusive picker buttons (exactly one view is
    always active - unlike the Map tab's overlay layers, a satellite view
    with nothing selected doesn't mean anything) plus one scaled full-disk
    image and its status/refresh controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_view = "goes_east"
        self._last_pixmap = None
        self._workers = set()  # strong refs to in-flight QThreads until they finish

        outer = QVBoxLayout(self)

        picker_row = QHBoxLayout()
        self._view_buttons = {}
        for view_id, label in VIEWS.items():
            button = QPushButton(label)
            button.setObjectName("modeToggle")
            button.setCheckable(True)
            button.clicked.connect(lambda checked, vid=view_id: self._on_view_button_clicked(vid, checked))
            self._view_buttons[view_id] = button
            picker_row.addWidget(button)
        picker_row.addStretch()
        outer.addLayout(picker_row)

        control_row = QHBoxLayout()
        self.status_label = QLabel("")
        control_row.addWidget(self.status_label, 1)
        self.refresh_button = QPushButton("↻ Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        control_row.addWidget(self.refresh_button)
        self.auto_refresh_button = QPushButton("▶ Auto-refresh")
        self.auto_refresh_button.setCheckable(True)
        self.auto_refresh_button.clicked.connect(self._toggle_auto_refresh)
        control_row.addWidget(self.auto_refresh_button)
        outer.addLayout(control_row)

        self.image_label = QLabel("Not loaded yet - open this tab to fetch live imagery.")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(300, 300)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self.image_label, 1)

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self.refresh)

        self._view_buttons[self._active_view].setChecked(True)
        # Deliberately no eager fetch here - like the Map/Alerts tabs, this
        # only hits the network once the tab is actually opened (see
        # weather_station.py's _on_tab_changed), so simply constructing the
        # widget (e.g. at app startup, or many times over in tests) never
        # triggers a live network call on its own.

    def shutdown(self):
        self._auto_refresh_timer.stop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._last_pixmap is not None:
            self._show_pixmap(self._last_pixmap)

    def _on_view_button_clicked(self, view_id, checked):
        if not checked:
            self._view_buttons[view_id].setChecked(True)
            return
        for other_id, button in self._view_buttons.items():
            if other_id != view_id:
                button.setChecked(False)
        self._active_view = view_id
        self._last_pixmap = None
        self.image_label.setText("Loading...")
        self.refresh()

    def _toggle_auto_refresh(self, checked):
        if checked:
            self._auto_refresh_timer.start(_AUTO_REFRESH_MS)
            self.auto_refresh_button.setText("⏸ Auto-refresh")
        else:
            self._auto_refresh_timer.stop()
            self.auto_refresh_button.setText("▶ Auto-refresh")

    def _show_pixmap(self, pixmap):
        self._last_pixmap = pixmap
        self.image_label.setPixmap(pixmap.scaled(
            self.image_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))

    def refresh(self):
        view = self._active_view
        self.status_label.setText("Loading...")

        def work():
            if view in GOES_SATELLITES:
                image_bytes = fetch_goes_image(view)
                if image_bytes is None:
                    return {"error": "GOES imagery temporarily unavailable."}
                return {"image_bytes": image_bytes, "caption": "GOES GeoColor (NOAA STAR) - refreshes ~every 10 min"}
            if view == "himawari":
                info = fetch_himawari_latest_info()
                if info is None:
                    return {"error": "Himawari imagery temporarily unavailable."}
                composite = fetch_himawari_composite(info["captured_at"])
                if composite is None:
                    return {"error": "Himawari imagery incomplete - some tiles failed to load."}
                caption = f"Himawari-9 (NICT) - captured {info['captured_at'].strftime('%b %d, %H:%M UTC')}"
                return {"image": composite, "caption": caption}
            if view == "epic":
                info = fetch_epic_latest()
                if info is None:
                    return {"error": "EPIC imagery temporarily unavailable."}
                image_bytes = fetch_epic_image(info["image_url"])
                if image_bytes is None:
                    return {"error": "EPIC image download failed."}
                caption = f"DSCOVR/NASA EPIC - captured {info['captured_at'].strftime('%b %d, %H:%M UTC')}"
                return {"image_bytes": image_bytes, "caption": caption}
            return {"error": f"Unknown view {view!r}."}

        worker = _FetchWorker(work)
        worker.result_ready.connect(lambda result: self._on_result(view, result))
        self._workers.add(worker)
        worker.finished.connect(lambda: self._workers.discard(worker))
        worker.start()

    def _on_result(self, view, result):
        if view != self._active_view:
            return  # the user switched views before this fetch finished
        if "error" in result:
            self.status_label.setText(result["error"])
            return
        if "image" in result:
            pixmap = QPixmap.fromImage(result["image"])
        else:
            pixmap = QPixmap()
            pixmap.loadFromData(result["image_bytes"])
        self._show_pixmap(pixmap)
        self.status_label.setText(result["caption"])
