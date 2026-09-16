"""A small, self-contained zoomable/pannable slippy-map widget (no
QtWebEngine - see games/__init__.py's policy against embedding a browser)
built from plain QPainter blitting of 256px raster tiles, used by
weather_station.py's Map tab.

Base layer is OpenStreetMap's standard tile set (disk-cached under
core_config.path("weather_station", "tile_cache") since it's static map
data - exactly what OSM's tile usage policy asks automated/desktop
clients to do). Overlay layers are RainViewer's keyless precipitation
radar and satellite-infrared mosaics (both worldwide, animated through
their last few frames), plus OpenWeatherMap's temperature/wind/clouds/
pressure tile layers when the user has supplied a free API key (see
weather_station.load_config/set_openweathermap_api_key) - those two
overlay families are never disk-cached since they go stale within
minutes to hours and an unbounded cache would just accumulate garbage.

Tile math is the standard Web Mercator slippy-map formulas (the same ones
OSM/RainViewer/OWM all key their tile URLs on).
"""
import csv
import io
import math
import os
import queue
from datetime import datetime, timezone

import requests
from PyQt6.QtCore import QPoint, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QWidget

from core import config as core_config

TILE_SIZE = 256
MIN_ZOOM = 2
MAX_ZOOM = 12
DEFAULT_ZOOM = 7
_TILE_CACHE_CAP = 400
_ANIMATION_INTERVAL_MS = 900
# Hold on the latest (most current) frame for a few extra beats before
# looping back to the start, rather than cycling through every frame at
# a flat interval - reads as a more deliberate "here's now, then replay
# the recent past" loop instead of a jittery flicker.
_ANIMATION_HOLD_FRAMES = 3

# RainViewer's radar/satellite tiles return a literal "Zoom Level Not
# Supported" placeholder image past this zoom (confirmed live: real data
# at 7, a fixed placeholder graphic at 8+) - matches NEXRAD's actual
# ground resolution anyway, so there's no real detail to gain by zooming
# the overlay in further. The base OSM map and OWM layers aren't affected
# and keep zooming up to MAX_ZOOM.
RAINVIEWER_MAX_ZOOM = 7

# NASA GIBS' "best available" true-color satellite mosaic (VIIRS SNPP daily
# Corrected Reflectance) - global, keyless, confirmed live. Its
# GoogleMapsCompatible_Level9 tile matrix set only defines zoom 0-9 (matches
# the sensor's native ~250m/pixel resolution - there's no real detail to
# gain by zooming further, same reasoning as RAINVIEWER_MAX_ZOOM above).
# Refreshed once or twice a day per point (polar-orbiting satellite passes),
# not minute-to-minute - GIBS carries no geostationary (GOES/Himawari)
# layers, confirmed absent from Worldview's own layer config.
GIBS_MAX_ZOOM = 9
GIBS_LAYER = "VIIRS_SNPP_CorrectedReflectance_TrueColor"

_TILE_HEADERS = {"User-Agent": "GnosisWeatherStation/1.0 (personal desktop app)"}

OWM_LAYERS = {
    "temperature": ("temp_new", "🌡️ Temperature"),
    "wind": ("wind_new", "💨 Wind"),
    "clouds": ("clouds_new", "☁️ Clouds"),
    "pressure": ("pressure_new", "🔵 Pressure"),
}


def lonlat_to_tile_xy(lon, lat, zoom):
    """Fractional tile coordinates (can be off-grid mid-tile) for a
    lon/lat at a given integer zoom - the standard Web Mercator slippy-map
    projection."""
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def tile_xy_to_lonlat(x, y, zoom):
    n = 2.0 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    return lon, math.degrees(lat_rad)


def osm_tile_url(z, x, y):
    return f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def owm_tile_url(layer_id, z, x, y, api_key):
    tile_name, _ = OWM_LAYERS[layer_id]
    return f"https://tile.openweathermap.org/map/{tile_name}/{z}/{x}/{y}.png?appid={api_key}"


def rainviewer_tile_url(host, frame_path, z, x, y, color=2):
    return f"{host}{frame_path}/256/{z}/{x}/{y}/{color}/1_1.png"


def gibs_tile_url(layer, date, z, x, y):
    """GIBS' WMTS-REST path order is {TileMatrix}/{TileRow}/{TileCol} - i.e.
    z/row/col - the reverse of the z/x/y order every other tile URL builder
    in this file uses (OSM/RainViewer/OWM are all standard XYZ). Confirmed
    live against the real service before wiring this in: a z/row/col URL
    returns a real 256x256 JPEG tile; row and col are transposed here to
    keep this function's own signature consistent (x=col, y=row) with its
    callers and with lonlat_to_tile_xy's (x, y) convention."""
    return (
        f"https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{layer}/default/"
        f"{date}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg"
    )


def fetch_rainviewer_frames():
    """RainViewer's public frame index: which radar/satellite mosaics
    exist right now and where to fetch their tiles. Returns
    {"host": ..., "radar_frames": [(unix_time, path), ...],
    "satellite_frames": [...]} (either list may be empty - satellite
    coverage in particular isn't always published) or None on failure."""
    try:
        response = requests.get(
            "https://api.rainviewer.com/public/weather-maps.json",
            headers=_TILE_HEADERS, timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return {
            "host": data["host"],
            "radar_frames": [(f["time"], f["path"]) for f in data.get("radar", {}).get("past", [])],
            "satellite_frames": [(f["time"], f["path"]) for f in data.get("satellite", {}).get("infrared", [])],
        }
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


def fetch_firms_hotspots(map_key, bbox, day_range=1, source="VIIRS_SNPP_NRT"):
    """NASA FIRMS' area API: active fire/thermal-anomaly detections inside
    a bounding box over the last `day_range` day(s) - global, refreshed a
    few times a day per satellite pass, needs a free MAP_KEY (see
    weather_station.load_config/set_firms_map_key, same UX shape as the
    OpenWeatherMap key above). bbox is (west, south, east, north) degrees.

    A bad/expired key gets FIRMS' own plain-text error body (e.g. "Invalid
    MAP_KEY.") instead of CSV - confirmed live before writing this -
    detected here by the response not parsing as the expected CSV columns,
    and surfaced as None rather than silently returning zero hotspots as
    if the sky were simply clear (see MEMORY: "No silent fallbacks").

    Returns a list of {"lat", "lon", "confidence", "acq_date", "acq_time",
    "frp"} dicts, or None on failure."""
    west, south, east, north = bbox
    area = f"{west},{south},{east},{north}"
    try:
        response = requests.get(
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{source}/{area}/{day_range}",
            headers=_TILE_HEADERS, timeout=15,
        )
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))
        if reader.fieldnames is None or "latitude" not in reader.fieldnames:
            return None
        hotspots = []
        for row in reader:
            try:
                hotspots.append({
                    "lat": float(row["latitude"]),
                    "lon": float(row["longitude"]),
                    "confidence": row.get("confidence"),
                    "acq_date": row.get("acq_date"),
                    "acq_time": row.get("acq_time"),
                    "frp": row.get("frp"),
                })
            except (KeyError, ValueError):
                continue
        return hotspots
    except requests.RequestException:
        return None


def _osm_disk_cache_path(z, x, y):
    return os.path.join(core_config.path("weather_station", "tile_cache"), f"{z}_{x}_{y}.png")


class _CallableThread(QThread):
    """Runs one zero-arg callable off the GUI thread and emits its return
    value - used for the (infrequent, one-shot) RainViewer frame-index
    fetch, as opposed to _TileFetchThread's persistent worker pool for the
    much more frequent per-tile requests."""
    result_ready = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        self.result_ready.emit(self.fn())


class _TileFetchThread(QThread):
    """One of a small pool of workers pulling jobs off a shared
    queue.Queue and emitting the result back to the GUI thread - Qt
    marshals cross-thread signal/slot connections onto the receiver's
    thread automatically, so no other synchronization is needed.

    Each job is (kind, key, payload, job_zoom):
      - kind "osm": payload is (disk_path, url) - check the on-disk tile
        cache first (this used to happen synchronously on the GUI thread
        inside paintEvent's call path, which stalled painting whenever the
        disk cache was warm; doing it here keeps it off the GUI thread and
        gives it the same in-flight/retry handling as a network miss) and
        fall back to downloading it.
      - kind "network": payload is a URL to fetch directly (used for the
        OWM/RainViewer overlay layers, which are never disk-cached).

    job_zoom is the map's zoom level at the moment the job was queued; if
    the viewport has since moved to a different zoom (e.g. the user spun
    the scroll wheel through several levels before any of them finished
    loading) the tile is no longer useful, so the fetch is skipped rather
    than burning a worker slot and bandwidth on it. This is a best-effort,
    lock-free check against a shared one-element list - a torn read just
    means an occasional wasted fetch, not a correctness problem.

    A requests.Session is reused for the life of the thread so repeated
    fetches to the same host (OSM/RainViewer/OWM) reuse HTTP keep-alive
    connections instead of paying a fresh TCP+TLS handshake per tile,
    which was the single biggest contributor to slow bulk tile loading.

    Also emits the HTTP status code on failure (or None for a non-HTTP
    failure like a timeout, or "stale" for a skipped stale job) - an
    OpenWeatherMap 401 in particular needs to reach the user as an
    explicit "your key was rejected" message rather than just a blank
    tile, per this project's "no silent fallbacks" rule."""
    tile_ready = pyqtSignal(object, object, object, bool)

    def __init__(self, job_queue, live_zoom):
        super().__init__()
        self._queue = job_queue
        self._live_zoom = live_zoom

    def run(self):
        session = requests.Session()
        while True:
            kind, key, payload, job_zoom = self._queue.get()
            if kind is None:
                return
            if job_zoom is not None and job_zoom != self._live_zoom[0]:
                self.tile_ready.emit(key, None, "stale", False)
                continue
            if kind == "osm":
                disk_path, url = payload
                data, status_code, from_disk = self._fetch_osm(session, disk_path, url)
            else:
                data, status_code, from_disk = self._fetch_network(session, payload)
            self.tile_ready.emit(key, data, status_code, from_disk)

    @staticmethod
    def _fetch_osm(session, disk_path, url):
        try:
            with open(disk_path, "rb") as f:
                return f.read(), 200, True
        except OSError:
            pass
        return _TileFetchThread._fetch_network(session, url)

    @staticmethod
    def _fetch_network(session, url):
        status_code = None
        try:
            response = session.get(url, headers=_TILE_HEADERS, timeout=10)
            status_code = response.status_code
            response.raise_for_status()
            return response.content, status_code, False
        except requests.RequestException:
            return None, status_code, False


class SlippyMapWidget(QWidget):
    """A pannable (drag), zoomable (scroll wheel, cursor-anchored) map:
    an OpenStreetMap base layer plus one optional weather overlay layer
    (precipitation/satellite/true_color/temperature/wind/clouds/pressure)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(False)

        self.center_lon = 0.0
        self.center_lat = 0.0
        self.zoom = DEFAULT_ZOOM
        self.active_layer = None  # None | "precipitation" | "satellite" | "true_color" | "temperature" | "wind" | "clouds" | "pressure"
        self.owm_api_key = None
        self.owm_auth_error = False
        self.attribution_extra = ""

        self._tile_cache = {}  # key -> QPixmap
        self._cache_order = []  # LRU order of keys
        self._pending = set()
        self._retry_counts = {}  # key -> number of retries already scheduled
        self._drag_origin = None
        self._drag_origin_center_tile = None

        self._rainviewer = None  # last fetch_rainviewer_frames() result
        self._rainviewer_workers = set()  # in-flight _CallableThreads - see _refresh_rainviewer_frames
        self._frame_index = -1  # -1 = latest
        self._hold_counter = 0  # ticks spent paused on the latest frame - see _ANIMATION_HOLD_FRAMES
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._advance_animation_frame)
        self.frame_label_text = ""

        # FIRMS thermal hotspots - an independent point overlay (not one of
        # active_layer's mutually-exclusive full-viewport layers), so it
        # can be shown alongside any of them. Refetched on set_center
        # (explicit recenter/navigation) rather than on every pan/zoom -
        # hotspots update a few times a day per satellite pass, not
        # continuously, so tracking the viewport pixel-perfectly during a
        # drag isn't worth the extra request traffic.
        self.firms_map_key = None
        self.show_firms_hotspots = False
        self._firms_hotspots = []
        self._firms_workers = set()
        self.firms_status_text = ""

        self._live_zoom = [self.zoom]  # shared with worker threads - see _TileFetchThread

        # Separate pools/queues for the OSM base layer and the overlay
        # layers: OSM's tile usage policy asks clients to keep concurrent
        # downloads low (around 2), and a full-viewport overlay layer
        # (e.g. temperature) sharing one pool with OSM would otherwise
        # crowd out base-map tiles and vice versa.
        self._osm_queue = queue.Queue()
        self._overlay_queue = queue.Queue()
        self._osm_workers = [_TileFetchThread(self._osm_queue, self._live_zoom) for _ in range(2)]
        self._overlay_workers = [_TileFetchThread(self._overlay_queue, self._live_zoom) for _ in range(2)]
        for worker in (*self._osm_workers, *self._overlay_workers):
            worker.tile_ready.connect(self._on_tile_ready)
            worker.start()

    def shutdown(self):
        self._animation_timer.stop()
        for _ in self._osm_workers:
            self._osm_queue.put((None, None, None, None))
        for _ in self._overlay_workers:
            self._overlay_queue.put((None, None, None, None))
        for worker in (*self._osm_workers, *self._overlay_workers):
            worker.wait(2000)

    # ------------------------------------------------------------------
    # Public controls
    # ------------------------------------------------------------------
    def set_center(self, lon, lat, zoom=None):
        self.center_lon = lon
        self.center_lat = lat
        if zoom is not None:
            self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
            self._live_zoom[0] = self.zoom
        self._request_visible_tiles()
        if self.show_firms_hotspots:
            self._refresh_firms_hotspots()
        self.update()

    def set_layer(self, layer_id):
        self.active_layer = layer_id
        self._frame_index = -1
        self._hold_counter = 0
        self._animation_timer.stop()
        if layer_id in ("precipitation", "satellite"):
            self._refresh_rainviewer_frames()
        self._update_attribution()
        self._request_visible_tiles()
        self.update()

    def set_owm_api_key(self, api_key):
        self.owm_api_key = api_key or None
        self.owm_auth_error = False
        self._update_attribution()
        self._request_visible_tiles()
        self.update()

    def set_firms_map_key(self, map_key):
        self.firms_map_key = map_key or None
        if not self.firms_map_key:
            self.show_firms_hotspots = False
            self._firms_hotspots = []
            self.firms_status_text = ""
        self.update()

    def set_show_firms_hotspots(self, enabled):
        self.show_firms_hotspots = bool(enabled and self.firms_map_key)
        if self.show_firms_hotspots:
            self._refresh_firms_hotspots()
        else:
            self.firms_status_text = ""
        self.update()

    def _current_bbox(self):
        z, _n, top_left_px_x, top_left_px_y, *_rest = self._visible_tile_range()
        west, north = tile_xy_to_lonlat(top_left_px_x / TILE_SIZE, top_left_px_y / TILE_SIZE, z)
        east, south = tile_xy_to_lonlat(
            (top_left_px_x + self.width()) / TILE_SIZE, (top_left_px_y + self.height()) / TILE_SIZE, z
        )
        return (max(west, -180.0), max(south, -85.0), min(east, 180.0), min(north, 85.0))

    def _refresh_firms_hotspots(self):
        if not self.firms_map_key:
            return
        self.firms_status_text = "Loading thermal hotspots..."
        bbox = self._current_bbox()
        map_key = self.firms_map_key
        worker = _CallableThread(lambda: fetch_firms_hotspots(map_key, bbox))
        worker.result_ready.connect(self._on_firms_hotspots_ready)
        self._firms_workers.add(worker)
        worker.finished.connect(lambda: self._firms_workers.discard(worker))
        worker.start()

    def _on_firms_hotspots_ready(self, hotspots):
        if hotspots is None:
            self._firms_hotspots = []
            self.firms_status_text = "Thermal hotspots unavailable - check your FIRMS key in Settings."
        elif not hotspots:
            self._firms_hotspots = []
            self.firms_status_text = "No thermal hotspots detected in this view."
        else:
            self._firms_hotspots = hotspots
            self.firms_status_text = f"{len(hotspots)} thermal hotspot(s) in view (FIRMS)"
        self.update()

    def animation_available(self):
        frames = self._current_frame_list()
        return frames is not None and len(frames) > 1

    def toggle_animation(self):
        if self._animation_timer.isActive():
            self._animation_timer.stop()
            return False
        if self.animation_available():
            self._hold_counter = 0
            self._animation_timer.start(_ANIMATION_INTERVAL_MS)
            return True
        return False

    def zoom_by(self, delta):
        self._zoom_toward(delta, self.width() / 2, self.height() / 2)

    # ------------------------------------------------------------------
    # RainViewer frame handling
    # ------------------------------------------------------------------
    def _refresh_rainviewer_frames(self):
        self.frame_label_text = "Loading..."
        self.update()
        worker = _CallableThread(fetch_rainviewer_frames)
        worker.result_ready.connect(self._on_rainviewer_frames_ready)
        # Keep a strong reference until the thread actually finishes,
        # rather than just until the next refresh - overwriting a single
        # self._rainviewer_worker attribute (e.g. from quickly switching
        # between the precipitation/satellite layers) could drop the last
        # Python reference to a still-running QThread and crash.
        self._rainviewer_workers.add(worker)
        worker.finished.connect(lambda: self._rainviewer_workers.discard(worker))
        worker.start()

    def _on_rainviewer_frames_ready(self, result):
        self._rainviewer = result
        self._update_attribution()
        self._request_visible_tiles()
        self.update()

    def _current_frame_list(self):
        if self._rainviewer is None:
            return None
        if self.active_layer == "precipitation":
            return self._rainviewer["radar_frames"]
        if self.active_layer == "satellite":
            return self._rainviewer["satellite_frames"]
        return None

    def _advance_animation_frame(self):
        frames = self._current_frame_list()
        if not frames:
            self._animation_timer.stop()
            return
        latest_index = len(frames) - 1
        current = self._frame_index if self._frame_index >= 0 else latest_index
        if current >= latest_index and self._hold_counter < _ANIMATION_HOLD_FRAMES:
            self._hold_counter += 1
            self._frame_index = latest_index
        else:
            self._hold_counter = 0
            self._frame_index = 0 if current >= latest_index else current + 1
        self._update_attribution()
        self._request_visible_tiles()
        self.update()

    def _update_attribution(self):
        parts = []
        if self.active_layer in ("precipitation", "satellite"):
            if self.zoom > RAINVIEWER_MAX_ZOOM:
                self.frame_label_text = "Zoom out to see radar/satellite (past their max useful zoom)"
            else:
                frames = self._current_frame_list()
                if frames:
                    index = self._frame_index if self._frame_index >= 0 else len(frames) - 1
                    ts = frames[index][0]
                    local_time = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
                    self.frame_label_text = local_time.strftime("%b %d, %H:%M %Z")
                elif self._rainviewer is None:
                    self.frame_label_text = "Loading..."
                else:
                    self.frame_label_text = "Unavailable right now"
            parts.append("Radar/Satellite © RainViewer")
        elif self.active_layer in OWM_LAYERS:
            if not self.owm_api_key:
                self.frame_label_text = "No OpenWeatherMap API key set - add one in Settings."
            elif self.owm_auth_error:
                self.frame_label_text = (
                    "OpenWeatherMap rejected this API key (401) - new keys can take up to a "
                    "couple hours to activate after signup. Double-check it in Settings."
                )
            else:
                self.frame_label_text = ""
            parts.append("Weather layer © OpenWeatherMap")
        elif self.active_layer == "true_color":
            if self.zoom > GIBS_MAX_ZOOM:
                self.frame_label_text = "Zoom out to see True Color (past its max useful zoom)"
            else:
                self.frame_label_text = "Refreshed ~1-2x/day per satellite pass, not live"
            parts.append("True Color (VIIRS/NASA GIBS)")
        else:
            self.frame_label_text = ""
        self.attribution_extra = (" | " + " | ".join(parts)) if parts else ""

    # ------------------------------------------------------------------
    # Tile cache
    # ------------------------------------------------------------------
    def _cache_get(self, key):
        pixmap = self._tile_cache.get(key)
        if pixmap is not None and key in self._cache_order:
            self._cache_order.remove(key)
            self._cache_order.append(key)
        return pixmap

    def _cache_put(self, key, pixmap):
        self._tile_cache[key] = pixmap
        self._cache_order.append(key)
        while len(self._cache_order) > _TILE_CACHE_CAP:
            oldest = self._cache_order.pop(0)
            self._tile_cache.pop(oldest, None)

    def _on_tile_ready(self, key, data, status_code, from_disk):
        self._pending.discard(key)
        if data is None:
            if key[0] == "owm" and status_code == 401 and not self.owm_auth_error:
                self.owm_auth_error = True
                self._update_attribution()
                self.update()
            elif status_code not in (401, "stale"):
                # Transient failure (timeout, dropped connection, 5xx) -
                # without this the tile would just stay blank forever,
                # since nothing else re-requests it once _pending has
                # been cleared.
                self._schedule_retry(key)
            return
        self._retry_counts.pop(key, None)
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return
        self._cache_put(key, pixmap)
        if key[0] == "osm" and not from_disk:
            path = _osm_disk_cache_path(*key[1:])
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
            except OSError:
                pass
        self.update()

    def _schedule_retry(self, key):
        attempt = self._retry_counts.get(key, 0)
        if attempt >= 3:
            return
        self._retry_counts[key] = attempt + 1
        # Re-scan rather than re-fetching this exact key: by the time the
        # timer fires the tile may no longer be on-screen (or, for an
        # overlay tile, the layer/frame may have moved on), and the scan
        # is a no-op for anything already cached or in flight.
        QTimer.singleShot(1000 * (attempt + 1), self._request_visible_tiles)

    def _request_tile(self, key, kind, payload, z, job_queue):
        if key in self._tile_cache or key in self._pending:
            return
        self._pending.add(key)
        job_queue.put((kind, key, payload, z))

    def _base_tile(self, z, x, y):
        key = ("osm", z, x, y)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        self._request_tile(
            key, "osm", (_osm_disk_cache_path(z, x, y), osm_tile_url(z, x, y)), z, self._osm_queue
        )
        return None

    def _overlay_tile(self, z, x, y):
        if self.active_layer in OWM_LAYERS:
            if not self.owm_api_key:
                return None
            key = ("owm", self.active_layer, z, x, y)
            cached = self._cache_get(key)
            if cached is not None:
                return cached
            self._request_tile(
                key, "network", owm_tile_url(self.active_layer, z, x, y, self.owm_api_key), z, self._overlay_queue
            )
            return None
        if self.active_layer in ("precipitation", "satellite"):
            if z > RAINVIEWER_MAX_ZOOM:
                return None
            frames = self._current_frame_list()
            if not frames:
                return None
            index = self._frame_index if self._frame_index >= 0 else len(frames) - 1
            index = max(0, min(index, len(frames) - 1))
            frame_time, frame_path = frames[index]
            key = ("rv", self.active_layer, frame_time, z, x, y)
            cached = self._cache_get(key)
            if cached is not None:
                return cached
            self._request_tile(
                key, "network", rainviewer_tile_url(self._rainviewer["host"], frame_path, z, x, y), z, self._overlay_queue
            )
            return None
        if self.active_layer == "true_color":
            if z > GIBS_MAX_ZOOM:
                return None
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            key = ("gibs", date, z, x, y)
            cached = self._cache_get(key)
            if cached is not None:
                return cached
            self._request_tile(
                key, "network", gibs_tile_url(GIBS_LAYER, date, z, x, y), z, self._overlay_queue
            )
            return None
        return None

    # ------------------------------------------------------------------
    # Tile requesting - decoupled from paintEvent so a fetch starts the
    # moment the viewport changes (center/zoom/size), rather than only as
    # a side effect of whenever Qt next actually calls paintEvent. update()
    # merely *schedules* a repaint and can be coalesced/delayed, so tile
    # requests must not depend on one having already happened.
    # ------------------------------------------------------------------
    def _visible_tile_range(self):
        z = self.zoom
        n = 2 ** z
        center_tx, center_ty = lonlat_to_tile_xy(self.center_lon, self.center_lat, z)
        top_left_px_x = center_tx * TILE_SIZE - self.width() / 2
        top_left_px_y = center_ty * TILE_SIZE - self.height() / 2
        start_tx = int(math.floor(top_left_px_x / TILE_SIZE))
        end_tx = int(math.floor((top_left_px_x + self.width()) / TILE_SIZE))
        start_ty = max(0, int(math.floor(top_left_px_y / TILE_SIZE)))
        end_ty = min(n - 1, int(math.floor((top_left_px_y + self.height()) / TILE_SIZE)))
        return z, n, top_left_px_x, top_left_px_y, start_tx, end_tx, start_ty, end_ty

    def _request_visible_tiles(self):
        if self.width() <= 0 or self.height() <= 0:
            return
        z, n, _tlx, _tly, start_tx, end_tx, start_ty, end_ty = self._visible_tile_range()
        for tx in range(start_tx, end_tx + 1):
            wrapped_tx = tx % n
            for ty in range(start_ty, end_ty + 1):
                self._base_tile(z, wrapped_tx, ty)
                self._overlay_tile(z, wrapped_tx, ty)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._request_visible_tiles()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)

        z, n, top_left_px_x, top_left_px_y, start_tx, end_tx, start_ty, end_ty = self._visible_tile_range()

        for tx in range(start_tx, end_tx + 1):
            wrapped_tx = tx % n
            for ty in range(start_ty, end_ty + 1):
                dest_x = tx * TILE_SIZE - top_left_px_x
                dest_y = ty * TILE_SIZE - top_left_px_y
                base = self._base_tile(z, wrapped_tx, ty)
                if base is not None:
                    painter.drawPixmap(QPoint(round(dest_x), round(dest_y)), base)
                overlay = self._overlay_tile(z, wrapped_tx, ty)
                if overlay is not None:
                    painter.setOpacity(0.75)
                    painter.drawPixmap(QPoint(round(dest_x), round(dest_y)), overlay)
                    painter.setOpacity(1.0)

        if self.show_firms_hotspots and self._firms_hotspots:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(255, 60, 0)))
            for hotspot in self._firms_hotspots:
                hx, hy = lonlat_to_tile_xy(hotspot["lon"], hotspot["lat"], z)
                px = hx * TILE_SIZE - top_left_px_x
                py = hy * TILE_SIZE - top_left_px_y
                if -6 <= px <= self.width() + 6 and -6 <= py <= self.height() + 6:
                    painter.drawEllipse(QPoint(round(px), round(py)), 4, 4)

        attribution = f"© OpenStreetMap contributors{self.attribution_extra}"
        if self.show_firms_hotspots:
            attribution += " | Hotspots © NASA FIRMS"
        # Black text needs a light backing bar to stay legible over the
        # map imagery (a black-on-black pairing would be invisible), so
        # the bars switch to a translucent off-white instead of black.
        label_bg = QColor(255, 255, 255, 215)
        painter.setPen(Qt.GlobalColor.black)
        painter.fillRect(0, self.height() - 18, self.width(), 18, label_bg)
        painter.drawText(4, self.height() - 5, attribution)
        if self.frame_label_text:
            painter.fillRect(0, 0, self.width(), 18, label_bg)
            painter.drawText(4, 14, self.frame_label_text)
        if self.firms_status_text:
            painter.fillRect(0, 18, self.width(), 18, label_bg)
            painter.drawText(4, 32, self.firms_status_text)
        painter.end()

    # ------------------------------------------------------------------
    # Mouse/wheel interaction
    # ------------------------------------------------------------------
    def _zoom_toward(self, delta_steps, widget_x, widget_y):
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom + delta_steps))
        if new_zoom == self.zoom:
            return
        center_tx, center_ty = lonlat_to_tile_xy(self.center_lon, self.center_lat, self.zoom)
        center_px_x = center_tx * TILE_SIZE
        center_px_y = center_ty * TILE_SIZE
        cursor_tile_x = (center_px_x - self.width() / 2 + widget_x) / TILE_SIZE
        cursor_tile_y = (center_px_y - self.height() / 2 + widget_y) / TILE_SIZE
        cursor_lon, cursor_lat = tile_xy_to_lonlat(cursor_tile_x, cursor_tile_y, self.zoom)

        self.zoom = new_zoom
        self._live_zoom[0] = new_zoom
        new_cursor_tx, new_cursor_ty = lonlat_to_tile_xy(cursor_lon, cursor_lat, self.zoom)
        new_center_px_x = new_cursor_tx * TILE_SIZE - (widget_x - self.width() / 2)
        new_center_px_y = new_cursor_ty * TILE_SIZE - (widget_y - self.height() / 2)
        self.center_lon, self.center_lat = tile_xy_to_lonlat(
            new_center_px_x / TILE_SIZE, new_center_px_y / TILE_SIZE, self.zoom
        )
        self._update_attribution()
        self._request_visible_tiles()
        self.update()

    def wheelEvent(self, event):
        delta = 1 if event.angleDelta().y() > 0 else -1
        pos = event.position()
        self._zoom_toward(delta, pos.x(), pos.y())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position()
            self._drag_origin_center_tile = lonlat_to_tile_xy(self.center_lon, self.center_lat, self.zoom)

    def mouseMoveEvent(self, event):
        if self._drag_origin is None:
            return
        pos = event.position()
        dx = pos.x() - self._drag_origin.x()
        dy = pos.y() - self._drag_origin.y()
        origin_tx, origin_ty = self._drag_origin_center_tile
        new_tx = origin_tx - dx / TILE_SIZE
        new_ty = origin_ty - dy / TILE_SIZE
        self.center_lon, self.center_lat = tile_xy_to_lonlat(new_tx, new_ty, self.zoom)
        self._request_visible_tiles()
        self.update()

    def mouseReleaseEvent(self, event):
        self._drag_origin = None
        self._drag_origin_center_tile = None
