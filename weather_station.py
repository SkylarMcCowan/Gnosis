"""Weather Station pane: NWS-backed forecast/alerts for the user's home
address (user_details.log's `home_address` field), a zoomable/pannable
multi-layer weather map (weather_map.py), and a compact internet radio tab
- searchable via Radio-Browser's directory, not just manual paste-in - for
streaming a NOAA Weather Radio relay or any other weather/emergency
stream. The radio backend and saved-station store now live in radio.py,
which also has its own full-featured Radio pane (search/library/
soundscapes/visualizer); this tab is kept as a quick-access shortcut and
shares the same saved stations.

Deliberately keyless wherever a keyless option exists - Open-Meteo's
geocoder resolves the home address to lat/lon (same free service
webagent.fetch_current_weather already uses), then forecast/alerts come
from api.weather.gov (NWS), which needs no API key, only a descriptive
User-Agent per its usage policy. NWS alerts/active already covers
fire-weather products (Red Flag Warning, Fire Weather Watch, etc.)
alongside ordinary weather alerts, so both "weather alerts" and "fire
alerts" come from one feed, tagged by event name, rather than a second
data source. The map's precipitation/satellite layers are RainViewer
(also keyless); its temperature/wind/clouds/pressure layers need a free
OpenWeatherMap API key, which the user pastes into the Settings tab -
that field starts empty and stays empty until they do, and every OWM
layer button stays visibly disabled with a tooltip pointing at Settings
until it's set, rather than silently doing nothing when clicked.

No fallback to a guessed/cached location or stale data on failure - every
fetch surfaces its failure as an explicit status message instead of
silently reusing old data or a different field (see MEMORY: "No silent
fallbacks").
"""
import json
import os
from datetime import datetime, timedelta, timezone

import requests
from PyQt6.QtCore import QThread, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from core import config as core_config
import webagent
from weather_map import DEFAULT_ZOOM, OWM_LAYERS, SlippyMapWidget
from radio import add_radio_station, list_radio_stations, remove_radio_station, search_radio_stations
from satellite import SatelliteWidget

_NWS_USER_AGENT = "GnosisWeatherStation/1.0 (personal desktop app)"
_NWS_HEADERS = {"User-Agent": _NWS_USER_AGENT, "Accept": "application/geo+json"}
FIRE_ALERT_KEYWORDS = ("fire", "red flag")

GDACS_EVENT_TYPES = {
    "EQ": ("🌎", "Earthquake"),
    "TC": ("🌀", "Tropical Cyclone"),
    "FL": ("🌊", "Flood"),
    "VO": ("🌋", "Volcano"),
    "WF": ("🔥", "Wildfire"),
    "DR": ("🏜️", "Drought"),
}
GDACS_ALERT_ORDER = {"Red": 0, "Orange": 1, "Green": 2}


# ----------------------------------------------------------------------
# Backend - home address, geocoding, NWS forecast/alerts/radar
# ----------------------------------------------------------------------
def home_address():
    """The user's configured home address (user_details.log's
    `home_address` field) - kept distinct from the free-text `location`
    field since this one specifically must be geocodable. Returns None on
    empty rather than falling back to `location`, so a missing address is
    an explicit, visible failure instead of a guess."""
    address = webagent.load_user_profile().get("home_address", "").strip()
    return address or None


def geocode(address):
    """Resolve a free-text address to lat/lon via Open-Meteo's keyless
    geocoder - same service and pattern as webagent.fetch_current_weather.
    Returns None on any failure or no match."""
    try:
        response = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": address, "count": 1}, timeout=8,
        )
        response.raise_for_status()
        matches = response.json().get("results") or []
        if not matches:
            return None
        place = matches[0]
        place_name = ", ".join(
            part for part in (place.get("name"), place.get("admin1"), place.get("country")) if part
        )
        return {"lat": place["latitude"], "lon": place["longitude"], "place": place_name}
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return None


def fetch_point_metadata(lat, lon):
    """NWS's /points lookup: which forecast office/grid cell and radar
    station cover this lat/lon, plus the two forecast URLs to hit next.

    NWS only covers the US/territories - a point outside that footprint
    gets a distinct, confirmed-live 404 ("InvalidPoint"), which is returned
    here as {"out_of_coverage": True} rather than being lumped in with a
    real outage - callers need to tell "this place will never have NWS
    data" apart from "NWS is down right now" to fall back to a global
    forecast source explicitly instead of just failing silently.

    Returns None on any other failure (network, unexpected shape, a
    non-404 HTTP error)."""
    try:
        response = requests.get(
            f"https://api.weather.gov/points/{lat},{lon}",
            headers=_NWS_HEADERS, timeout=10,
        )
        response.raise_for_status()
        props = response.json()["properties"]
        relative = props.get("relativeLocation", {}).get("properties", {})
        return {
            "forecast_url": props["forecast"],
            "hourly_url": props["forecastHourly"],
            "radar_station": props.get("radarStation"),
            "city": relative.get("city"),
            "state": relative.get("state"),
        }
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return {"out_of_coverage": True}
        return None
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return None


def fetch_forecast_periods(forecast_url):
    try:
        response = requests.get(forecast_url, headers=_NWS_HEADERS, timeout=10)
        response.raise_for_status()
        return response.json()["properties"]["periods"]
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return None


def fetch_hourly_periods(hourly_url, limit=12):
    try:
        response = requests.get(hourly_url, headers=_NWS_HEADERS, timeout=10)
        response.raise_for_status()
        return response.json()["properties"]["periods"][:limit]
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return None


_COMPASS_POINTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _degrees_to_compass(degrees):
    return _COMPASS_POINTS[round(degrees / 45) % 8]


def fetch_open_meteo_forecast(lat, lon):
    """Global keyless forecast fallback for points outside NWS's US-only
    footprint (see fetch_point_metadata's out_of_coverage case) - same
    Open-Meteo service geocode()/webagent.fetch_current_weather already
    use. Shaped into the same period-list form fetch_forecast_periods
    returns (name/temperature/temperatureUnit/shortForecast/windSpeed/
    windDirection) so the existing forecast-card rendering needs no
    special-casing per source. Returns None on any failure."""
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "daily": "weather_code,temperature_2m_max,wind_speed_10m_max,wind_direction_10m_dominant",
                "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "auto",
                "forecast_days": 7,
            }, timeout=10,
        )
        response.raise_for_status()
        daily = response.json()["daily"]
        periods = []
        for index, date_str in enumerate(daily["time"]):
            if index == 0:
                name = "Today"
            else:
                name = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A")
            code = daily["weather_code"][index]
            periods.append({
                "name": name,
                "temperature": round(daily["temperature_2m_max"][index]),
                "temperatureUnit": "F",
                "shortForecast": webagent._WMO_WEATHER_DESCRIPTIONS.get(code, "Unknown conditions").capitalize(),
                "windSpeed": f"{round(daily['wind_speed_10m_max'][index])} mph",
                "windDirection": _degrees_to_compass(daily["wind_direction_10m_dominant"][index]),
            })
        return periods
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return None


def fetch_active_alerts(lat, lon):
    """All active NWS alerts for this point, each tagged is_fire based on
    event name (Red Flag Warning, Fire Weather Watch, etc.)."""
    try:
        response = requests.get(
            "https://api.weather.gov/alerts/active",
            params={"point": f"{lat},{lon}"}, headers=_NWS_HEADERS, timeout=10,
        )
        response.raise_for_status()
        alerts = []
        for feature in response.json()["features"]:
            props = feature["properties"]
            event = props.get("event") or ""
            alerts.append({
                "event": event,
                "severity": props.get("severity"),
                "headline": props.get("headline"),
                "description": props.get("description"),
                "instruction": props.get("instruction"),
                "effective": props.get("effective"),
                "expires": props.get("expires"),
                "area_desc": props.get("areaDesc"),
                "is_fire": any(keyword in event.lower() for keyword in FIRE_ALERT_KEYWORDS),
            })
        return alerts
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return None


def fetch_gdacs_events(from_date, to_date):
    """Global Disaster Alert and Coordination System - keyless GeoJSON,
    worldwide earthquakes/cyclones/floods/volcanoes/wildfires/droughts,
    each carrying its own lat/lon - the global analogue of NWS's US-only
    /alerts/active above, and not gated by the currently-viewed location
    (GDACS is inherently global in scope). from_date/to_date are
    "YYYY-MM-DD" strings. Returns a list sorted by alert level (Red then
    Orange then Green) and, within a level, most recent first. Returns
    None on failure."""
    try:
        response = requests.get(
            "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH",
            params={"fromDate": from_date, "toDate": to_date}, timeout=15,
        )
        response.raise_for_status()
        events = []
        for feature in response.json()["features"]:
            props = feature["properties"]
            lon, lat = (feature.get("geometry") or {}).get("coordinates") or (None, None)
            events.append({
                "event_type": props.get("eventtype"),
                "name": props.get("name") or "",
                "country": props.get("country"),
                "alert_level": props.get("alertlevel"),
                "description": props.get("description"),
                "from_date": props.get("fromdate"),
                "lat": lat,
                "lon": lon,
                "url": (props.get("url") or {}).get("report"),
            })
        events.sort(key=lambda e: e["from_date"] or "", reverse=True)
        events.sort(key=lambda e: GDACS_ALERT_ORDER.get(e["alert_level"], 3))
        return events
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return None


# ----------------------------------------------------------------------
# Module config - currently just the optional OpenWeatherMap API key that
# unlocks the map's temperature/wind/clouds/pressure layers. Own small
# JSON store (not user_details.log): an API key is app config, not a
# profile fact about the user.
# ----------------------------------------------------------------------
def _config_path():
    return os.path.join(core_config.path("weather_station"), "config.json")


def load_config():
    path = _config_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return config if isinstance(config, dict) else {}


def save_config(config):
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def openweathermap_api_key():
    return (load_config().get("openweathermap_api_key") or "").strip() or None


def set_openweathermap_api_key(api_key):
    config = load_config()
    config["openweathermap_api_key"] = (api_key or "").strip()
    save_config(config)


def firms_map_key():
    return (load_config().get("firms_map_key") or "").strip() or None


def set_firms_map_key(map_key):
    config = load_config()
    config["firms_map_key"] = (map_key or "").strip()
    save_config(config)


# ----------------------------------------------------------------------
# Widget
# ----------------------------------------------------------------------
class _FetchWorker(QThread):
    """Runs one zero-arg callable off the GUI thread - same shape as
    webagent_gui.CycleWorker, duplicated locally so this module doesn't
    have to import the GUI module."""
    result_ready = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        self.result_ready.emit(self.fn())


def _scroll_list(container_layout_holder_attr):
    """A QScrollArea wrapping a vertical list of cards, returned alongside
    the inner layout callers append/clear cards through."""
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


class WeatherStationWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._lat = None
        self._lon = None
        self._place = None
        self._point = None
        self._nws_covers_location = True
        self._home_geo = None
        self._home_point = None
        self._map_centered = False
        self._playing_station_id = None
        self._radio_buttons = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(15, 15, 15, 15)
        outer.setSpacing(10)

        header_row = QHBoxLayout()
        title = QLabel("🌦️ Weather Station")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        header_row.addWidget(title)
        header_row.addStretch()
        self.location_search_input = QLineEdit()
        self.location_search_input.setPlaceholderText('Go to any place, e.g. "Tokyo, Japan"')
        self.location_search_input.setFixedWidth(220)
        self.location_search_input.returnPressed.connect(self._search_location_clicked)
        header_row.addWidget(self.location_search_input)
        location_search_button = QPushButton("🔍")
        location_search_button.setFixedWidth(32)
        location_search_button.setToolTip("Go to this place - forecast/map/alerts follow it, everywhere on Earth")
        location_search_button.clicked.connect(self._search_location_clicked)
        header_row.addWidget(location_search_button)
        self.location_status_label = QLabel("")
        header_row.addWidget(self.location_status_label)
        outer.addLayout(header_row)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self.forecast_tab = self._build_forecast_tab()
        self.map_tab = self._build_map_tab()
        self.satellite_tab = SatelliteWidget()
        self.alerts_tab = self._build_alerts_tab()
        self.radio_tab = self._build_radio_tab()
        self.settings_tab = self._build_settings_tab()
        self.tabs.addTab(self.forecast_tab, "Forecast")
        self.tabs.addTab(self.map_tab, "🗺️ Map")
        self.tabs.addTab(self.satellite_tab, "🛰️ Satellite")
        self.tabs.addTab(self.alerts_tab, "🔥 Alerts")
        self.tabs.addTab(self.radio_tab, "📻 Radio")
        self.tabs.addTab(self.settings_tab, "⚙️ Settings")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._media_player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._media_player.setAudioOutput(self._audio_output)
        self._media_devices = QMediaDevices(self)
        self._media_devices.audioOutputsChanged.connect(self._on_audio_outputs_changed)

        self.layer_buttons["precipitation"].setChecked(True)
        self.map_widget.set_layer("precipitation")
        self._apply_owm_api_key(openweathermap_api_key())
        self._apply_firms_map_key(firms_map_key())

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.map_widget.shutdown)
            app.aboutToQuit.connect(self.satellite_tab.shutdown)

        self._refresh_forecast()
        self._refresh_radio_stations()

    def _on_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if widget is self.forecast_tab:
            self._refresh_forecast()
        elif widget is self.map_tab:
            self._refresh_map()
        elif widget is self.satellite_tab:
            self.satellite_tab.refresh()
        elif widget is self.alerts_tab:
            self._refresh_alerts()

    # ------------------------------------------------------------------
    # Location resolution, shared by Forecast/Map/Alerts. `_lat`/`_lon`/
    # `_place`/`_point` are the *currently viewed* location, not
    # necessarily home - `_resolve_location` only resolves home once (on
    # first use, then cached) as the starting point; after that, explicit
    # navigation (`_navigate_to`, the search box, or the Home button) is
    # what changes it, and always re-resolves rather than trusting a cache.
    # ------------------------------------------------------------------
    def _apply_resolved_location(self, geo, point):
        self._lat = geo["lat"]
        self._lon = geo["lon"]
        self._place = geo["place"]
        self._point = point
        self._nws_covers_location = not (point or {}).get("out_of_coverage")
        self.location_status_label.setText(f"📍 {self._place}")

    def _resolve_location(self, on_ready, on_error):
        if self._lat is not None:
            on_ready()
            return
        address = home_address()
        if not address:
            on_error('No home address set - add "home_address: <city, state>" to user_details.log.')
            return

        def work():
            geo = geocode(address)
            if geo is None:
                return {"error": f'Could not geocode home address "{address}".'}
            point = fetch_point_metadata(geo["lat"], geo["lon"])
            if point is None:
                return {"error": "NWS point lookup failed - the service may be unavailable."}
            return {"geo": geo, "point": point}

        def handle(result):
            if "error" in result:
                on_error(result["error"])
                return
            self._apply_resolved_location(result["geo"], result["point"])
            self._home_geo = result["geo"]
            self._home_point = result["point"]
            on_ready()

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._location_worker = worker
        worker.start()

    def _navigate_to(self, address):
        """Explicit "go here" - unlike _resolve_location this always
        re-resolves, even if a location is already cached, since the user
        is deliberately asking to move somewhere else."""
        self.location_status_label.setText(f'Looking up "{address}"...')

        def work():
            geo = geocode(address)
            if geo is None:
                return {"error": f'Could not find "{address}".'}
            point = fetch_point_metadata(geo["lat"], geo["lon"])
            if point is None:
                return {"error": "NWS point lookup failed - the service may be unavailable."}
            return {"geo": geo, "point": point}

        def handle(result):
            if "error" in result:
                self.location_status_label.setText(result["error"])
                return
            self._apply_resolved_location(result["geo"], result["point"])
            self._after_navigation()

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._navigate_worker = worker
        worker.start()

    def _after_navigation(self):
        """Every tab follows the newly-viewed location: forecast/alerts
        refetch for it, and the map is forced to recenter (bypassing
        _refresh_map's "already centered" guard, which exists for passive
        tab switches, not deliberate navigation)."""
        self._map_centered = False
        self._refresh_forecast()
        self._refresh_map()
        self._refresh_alerts()

    def _search_location_clicked(self):
        address = self.location_search_input.text().strip()
        if not address:
            self.location_status_label.setText("Enter a place to search.")
            return
        self._navigate_to(address)

    def _go_home_clicked(self):
        if self._home_geo is not None:
            self._apply_resolved_location(self._home_geo, self._home_point)
            self._after_navigation()
            return
        address = home_address()
        if not address:
            self.location_status_label.setText(
                'No home address set - add "home_address: <city, state>" to user_details.log.'
            )
            return
        self._navigate_to(address)

    # ------------------------------------------------------------------
    # Forecast
    # ------------------------------------------------------------------
    def _build_forecast_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        top_row = QHBoxLayout()
        self.forecast_refresh_button = QPushButton("↻ Refresh")
        self.forecast_refresh_button.clicked.connect(self._refresh_forecast)
        top_row.addWidget(self.forecast_refresh_button)
        top_row.addStretch()
        layout.addLayout(top_row)
        self.forecast_status_label = QLabel("Loading forecast...")
        layout.addWidget(self.forecast_status_label)
        self.forecast_scroll, self.forecast_list_layout = _scroll_list(page)
        layout.addWidget(self.forecast_scroll, 1)
        return page

    def _refresh_forecast(self):
        self.forecast_status_label.setText("Loading forecast...")
        _clear_layout(self.forecast_list_layout)

        def on_error(message):
            self.forecast_status_label.setText(message)

        def on_ready():
            def work():
                if self._nws_covers_location:
                    return {"source": "nws", "periods": fetch_forecast_periods(self._point["forecast_url"])}
                return {"source": "open-meteo", "periods": fetch_open_meteo_forecast(self._lat, self._lon)}

            def handle(result):
                periods = result["periods"]
                if periods is None:
                    self.forecast_status_label.setText("Forecast temporarily unavailable.")
                    return
                if result["source"] == "nws":
                    self.forecast_status_label.setText(f"NWS forecast for {self._place}")
                else:
                    self.forecast_status_label.setText(
                        f"Forecast via Open-Meteo (global) for {self._place} - NWS doesn't cover this location"
                    )
                for period in periods:
                    card = QFrame()
                    card.setFrameShape(QFrame.Shape.StyledPanel)
                    card_layout = QVBoxLayout(card)
                    name_label = QLabel(f"{period['name']} - {period['temperature']}°{period['temperatureUnit']}")
                    name_label.setStyleSheet("font-weight: bold;")
                    card_layout.addWidget(name_label)
                    card_layout.addWidget(QLabel(period.get("shortForecast", "")))
                    wind = f"Wind: {period.get('windSpeed', '')} {period.get('windDirection', '')}".strip()
                    card_layout.addWidget(QLabel(wind))
                    self.forecast_list_layout.insertWidget(self.forecast_list_layout.count() - 1, card)

            worker = _FetchWorker(work)
            worker.result_ready.connect(handle)
            self._forecast_worker = worker
            worker.start()

        self._resolve_location(on_ready, on_error)

    # ------------------------------------------------------------------
    # Map - zoomable/pannable, one overlay layer at a time: keyless
    # precipitation/satellite (RainViewer), or temperature/wind/clouds/
    # pressure once an OpenWeatherMap key is set in Settings.
    # ------------------------------------------------------------------
    def _build_map_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        top_row = QHBoxLayout()
        self.map_status_label = QLabel("Loading map...")
        top_row.addWidget(self.map_status_label, 1)
        home_button = QPushButton("🏠 Home")
        home_button.setToolTip("Recenter on your home address")
        home_button.clicked.connect(self._go_home_clicked)
        top_row.addWidget(home_button)
        zoom_out_button = QPushButton("−")
        zoom_out_button.setFixedWidth(28)
        zoom_out_button.clicked.connect(lambda: self.map_widget.zoom_by(-1))
        top_row.addWidget(zoom_out_button)
        zoom_in_button = QPushButton("+")
        zoom_in_button.setFixedWidth(28)
        zoom_in_button.clicked.connect(lambda: self.map_widget.zoom_by(1))
        top_row.addWidget(zoom_in_button)
        self.animate_button = QPushButton("▶ Animate")
        self.animate_button.clicked.connect(self._toggle_map_animation)
        top_row.addWidget(self.animate_button)
        layout.addLayout(top_row)

        layer_row = QHBoxLayout()
        self.layer_buttons = {}
        for layer_id, label in (
            ("precipitation", "🌧️ Precipitation"),
            ("satellite", "☁️ Satellite (IR)"),
            ("true_color", "🌍 True Color"),
        ):
            button = QPushButton(label)
            button.setObjectName("modeToggle")
            button.setCheckable(True)
            button.clicked.connect(lambda checked, lid=layer_id: self._on_layer_button_clicked(lid, checked))
            self.layer_buttons[layer_id] = button
            layer_row.addWidget(button)
        for layer_id, (_tile_name, label) in OWM_LAYERS.items():
            button = QPushButton(label)
            button.setObjectName("modeToggle")
            button.setCheckable(True)
            button.setEnabled(False)
            button.setToolTip("Set a free OpenWeatherMap API key in the Settings tab to enable this layer.")
            button.clicked.connect(lambda checked, lid=layer_id: self._on_layer_button_clicked(lid, checked))
            self.layer_buttons[layer_id] = button
            layer_row.addWidget(button)
        layer_row.addStretch()
        self.firms_toggle_button = QPushButton("🔥 Thermal Hotspots")
        self.firms_toggle_button.setObjectName("modeToggle")
        self.firms_toggle_button.setCheckable(True)
        self.firms_toggle_button.setEnabled(False)
        self.firms_toggle_button.setToolTip("Set a free FIRMS MAP_KEY in the Settings tab to enable this.")
        self.firms_toggle_button.clicked.connect(self._on_firms_toggle_clicked)
        layer_row.addWidget(self.firms_toggle_button)
        layout.addLayout(layer_row)

        self.map_widget = SlippyMapWidget()
        layout.addWidget(self.map_widget, 1)
        return page

    def _on_firms_toggle_clicked(self, checked):
        self.map_widget.set_show_firms_hotspots(checked)

    def _on_layer_button_clicked(self, layer_id, checked):
        if checked:
            for other_id, other_button in self.layer_buttons.items():
                if other_id != layer_id:
                    other_button.setChecked(False)
            self.map_widget.set_layer(layer_id)
        else:
            self.map_widget.set_layer(None)
        self._sync_animate_button()

    def _sync_animate_button(self):
        animatable = self.map_widget.active_layer in ("precipitation", "satellite")
        self.animate_button.setEnabled(animatable)
        if not animatable:
            self.animate_button.setText("▶ Animate")

    def _toggle_map_animation(self):
        playing = self.map_widget.toggle_animation()
        self.animate_button.setText("⏸ Pause" if playing else "▶ Animate")

    def _map_status_text(self):
        bits = [f"📍 {self._place}"]
        radar_station = (self._point or {}).get("radar_station")
        if radar_station:
            bits.append(f"Nearest NWS radar: {radar_station}")
        return " | ".join(bits)

    def _refresh_map(self):
        if self._map_centered:
            return

        def on_error(message):
            self.map_status_label.setText(message)

        def on_ready():
            self._map_centered = True
            self.map_widget.set_center(self._lon, self._lat, zoom=DEFAULT_ZOOM)
            self.map_status_label.setText(self._map_status_text())

        self._resolve_location(on_ready, on_error)

    # ------------------------------------------------------------------
    # Settings - OpenWeatherMap API key (optional, unlocks 4 map layers)
    # ------------------------------------------------------------------
    def _build_settings_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        title_label = QLabel("OpenWeatherMap API key")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)
        hint = QLabel(
            "Unlocks the Map tab's Temperature/Wind/Clouds/Pressure layers. Get a free key "
            "(no credit card) at openweathermap.org/api, then paste it below."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        self.owm_key_input = QLineEdit()
        self.owm_key_input.setPlaceholderText("OpenWeatherMap API key (currently unset)")
        self.owm_key_input.setText(openweathermap_api_key() or "")
        row.addWidget(self.owm_key_input, 1)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self._save_owm_api_key_clicked)
        row.addWidget(save_button)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._clear_owm_api_key_clicked)
        row.addWidget(clear_button)
        layout.addLayout(row)

        self.owm_key_status_label = QLabel(self._owm_key_status_text())
        layout.addWidget(self.owm_key_status_label)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        firms_title_label = QLabel("NASA FIRMS MAP_KEY")
        firms_title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(firms_title_label)
        firms_hint = QLabel(
            "Unlocks the Map tab's 🔥 Thermal Hotspots overlay (global fire/thermal-anomaly detections). "
            "Get a free key at firms.modaps.eosdis.nasa.gov/api/map_key, then paste it below."
        )
        firms_hint.setWordWrap(True)
        layout.addWidget(firms_hint)

        firms_row = QHBoxLayout()
        self.firms_key_input = QLineEdit()
        self.firms_key_input.setPlaceholderText("FIRMS MAP_KEY (currently unset)")
        self.firms_key_input.setText(firms_map_key() or "")
        firms_row.addWidget(self.firms_key_input, 1)
        firms_save_button = QPushButton("Save")
        firms_save_button.clicked.connect(self._save_firms_map_key_clicked)
        firms_row.addWidget(firms_save_button)
        firms_clear_button = QPushButton("Clear")
        firms_clear_button.clicked.connect(self._clear_firms_map_key_clicked)
        firms_row.addWidget(firms_clear_button)
        layout.addLayout(firms_row)

        self.firms_key_status_label = QLabel(self._firms_key_status_text())
        layout.addWidget(self.firms_key_status_label)
        layout.addStretch()
        return page

    def _owm_key_status_text(self):
        return (
            "An OpenWeatherMap API key is set - Temperature/Wind/Clouds/Pressure are enabled on the Map tab."
            if openweathermap_api_key() else
            "No API key set - Temperature/Wind/Clouds/Pressure stay disabled on the Map tab until you add one."
        )

    def _save_owm_api_key_clicked(self):
        key = self.owm_key_input.text().strip()
        set_openweathermap_api_key(key)
        self._apply_owm_api_key(key)
        self.owm_key_status_label.setText(self._owm_key_status_text())

    def _clear_owm_api_key_clicked(self):
        self.owm_key_input.clear()
        set_openweathermap_api_key("")
        self._apply_owm_api_key("")
        self.owm_key_status_label.setText(self._owm_key_status_text())

    def _apply_owm_api_key(self, key):
        self.map_widget.set_owm_api_key(key or None)
        for layer_id in OWM_LAYERS:
            button = self.layer_buttons[layer_id]
            button.setEnabled(bool(key))
            if not key and button.isChecked():
                button.setChecked(False)
                self.map_widget.set_layer(None)
        self._sync_animate_button()

    def _firms_key_status_text(self):
        return (
            "A FIRMS MAP_KEY is set - Thermal Hotspots is enabled on the Map tab."
            if firms_map_key() else
            "No MAP_KEY set - Thermal Hotspots stays disabled on the Map tab until you add one."
        )

    def _save_firms_map_key_clicked(self):
        key = self.firms_key_input.text().strip()
        set_firms_map_key(key)
        self._apply_firms_map_key(key)
        self.firms_key_status_label.setText(self._firms_key_status_text())

    def _clear_firms_map_key_clicked(self):
        self.firms_key_input.clear()
        set_firms_map_key("")
        self._apply_firms_map_key("")
        self.firms_key_status_label.setText(self._firms_key_status_text())

    def _apply_firms_map_key(self, key):
        self.map_widget.set_firms_map_key(key or None)
        self.firms_toggle_button.setEnabled(bool(key))
        if not key and self.firms_toggle_button.isChecked():
            self.firms_toggle_button.setChecked(False)

    # ------------------------------------------------------------------
    # Alerts (weather + fire)
    # ------------------------------------------------------------------
    def _build_alerts_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        top_row = QHBoxLayout()
        self.alerts_refresh_button = QPushButton("↻ Refresh")
        self.alerts_refresh_button.clicked.connect(self._refresh_alerts)
        top_row.addWidget(self.alerts_refresh_button)
        top_row.addStretch()
        layout.addLayout(top_row)
        self.alerts_status_label = QLabel("Loading alerts...")
        layout.addWidget(self.alerts_status_label)
        self.alerts_scroll, self.alerts_list_layout = _scroll_list(page)
        layout.addWidget(self.alerts_scroll, 1)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        gdacs_title = QLabel("🌐 Global Disasters (GDACS)")
        gdacs_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(gdacs_title)
        self.gdacs_status_label = QLabel("Loading...")
        layout.addWidget(self.gdacs_status_label)
        self.gdacs_scroll, self.gdacs_list_layout = _scroll_list(page)
        layout.addWidget(self.gdacs_scroll, 1)
        return page

    def _refresh_alerts(self):
        self._refresh_nws_alerts()
        self._refresh_gdacs_alerts()

    def _refresh_nws_alerts(self):
        self.alerts_status_label.setText("Loading alerts...")
        _clear_layout(self.alerts_list_layout)

        def on_error(message):
            self.alerts_status_label.setText(message)

        def on_ready():
            if not self._nws_covers_location:
                self.alerts_status_label.setText(
                    f"NWS alerts aren't available for {self._place} - NWS only covers the US/territories."
                )
                return

            def work():
                return fetch_active_alerts(self._lat, self._lon)

            def handle(alerts):
                if alerts is None:
                    self.alerts_status_label.setText("Alerts temporarily unavailable.")
                    return
                if not alerts:
                    self.alerts_status_label.setText(f"No active alerts for {self._place}.")
                    return
                fire_count = sum(1 for alert in alerts if alert["is_fire"])
                self.alerts_status_label.setText(
                    f"{len(alerts)} active alert(s) for {self._place}"
                    + (f" - {fire_count} fire-related" if fire_count else "")
                )
                for alert in alerts:
                    card = QFrame()
                    card.setFrameShape(QFrame.Shape.StyledPanel)
                    card.setStyleSheet(
                        "background-color: #4a1f1f;" if alert["is_fire"] else "background-color: #4a3d1f;"
                    )
                    card_layout = QVBoxLayout(card)
                    prefix = "🔥 " if alert["is_fire"] else "⚠️ "
                    title_label = QLabel(f"{prefix}{alert['event']} ({alert.get('severity') or 'Unknown'})")
                    title_label.setStyleSheet("font-weight: bold;")
                    card_layout.addWidget(title_label)
                    if alert.get("area_desc"):
                        card_layout.addWidget(QLabel(alert["area_desc"]))
                    if alert.get("headline"):
                        headline_label = QLabel(alert["headline"])
                        headline_label.setWordWrap(True)
                        card_layout.addWidget(headline_label)
                    self.alerts_list_layout.insertWidget(self.alerts_list_layout.count() - 1, card)

            worker = _FetchWorker(work)
            worker.result_ready.connect(handle)
            self._alerts_worker = worker
            worker.start()

        self._resolve_location(on_ready, on_error)

    def _refresh_gdacs_alerts(self):
        """Global disaster alerts - unlike NWS's alerts, this is never
        gated by _nws_covers_location or even by the currently-viewed
        location at all: GDACS covers the whole planet in one feed."""
        self.gdacs_status_label.setText("Loading...")
        _clear_layout(self.gdacs_list_layout)

        def work():
            today = datetime.now(timezone.utc).date()
            from_date = (today - timedelta(days=30)).isoformat()
            return fetch_gdacs_events(from_date, today.isoformat())

        def handle(events):
            if events is None:
                self.gdacs_status_label.setText("Global disaster feed temporarily unavailable.")
                return
            if not events:
                self.gdacs_status_label.setText("No active global disaster alerts.")
                return
            self.gdacs_status_label.setText(f"{len(events)} active event(s) worldwide (GDACS)")
            level_colors = {"Red": "#4a1f1f", "Orange": "#4a3d1f", "Green": "#234a1f"}
            for event in events:
                card = QFrame()
                card.setFrameShape(QFrame.Shape.StyledPanel)
                level = event["alert_level"]
                card.setStyleSheet(f"background-color: {level_colors.get(level, '#333333')};")
                card_layout = QVBoxLayout(card)
                emoji, type_label = GDACS_EVENT_TYPES.get(event["event_type"], ("⚠️", event["event_type"] or "Event"))
                title_label = QLabel(f"{emoji} {type_label} - {event['name']} ({level or 'Unknown'})")
                title_label.setStyleSheet("font-weight: bold;")
                card_layout.addWidget(title_label)
                if event.get("country"):
                    card_layout.addWidget(QLabel(event["country"]))
                if event.get("description"):
                    desc_label = QLabel(event["description"])
                    desc_label.setWordWrap(True)
                    card_layout.addWidget(desc_label)
                self.gdacs_list_layout.insertWidget(self.gdacs_list_layout.count() - 1, card)

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._gdacs_worker = worker
        worker.start()

    # ------------------------------------------------------------------
    # Radio - search Radio-Browser's directory in-app, or add a stream
    # URL manually for anything not listed there.
    # ------------------------------------------------------------------
    def _build_radio_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        search_row = QHBoxLayout()
        self.radio_search_input = QLineEdit()
        self.radio_search_input.setPlaceholderText('Search stations, e.g. "NOAA Weather Radio Arizona"')
        self.radio_search_input.returnPressed.connect(self._search_radio_stations_clicked)
        search_row.addWidget(self.radio_search_input, 1)
        search_button = QPushButton("🔍 Search")
        search_button.clicked.connect(self._search_radio_stations_clicked)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        self.radio_search_status_label = QLabel(
            "Search Radio-Browser's free station directory - real NOAA Weather Radio relays are listed there."
        )
        self.radio_search_status_label.setWordWrap(True)
        layout.addWidget(self.radio_search_status_label)

        self.radio_search_scroll, self.radio_search_results_layout = _scroll_list(page)
        self.radio_search_scroll.setMaximumHeight(220)
        layout.addWidget(self.radio_search_scroll)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        layout.addWidget(QLabel("Saved stations"))
        add_row = QHBoxLayout()
        self.radio_name_input = QLineEdit()
        self.radio_name_input.setPlaceholderText("Station name")
        add_row.addWidget(self.radio_name_input, 1)
        self.radio_url_input = QLineEdit()
        self.radio_url_input.setPlaceholderText("Stream URL (or add manually)")
        add_row.addWidget(self.radio_url_input, 2)
        self.radio_add_button = QPushButton("+ Add")
        self.radio_add_button.clicked.connect(self._add_radio_station_clicked)
        add_row.addWidget(self.radio_add_button)
        layout.addLayout(add_row)

        self.radio_status_label = QLabel("")
        layout.addWidget(self.radio_status_label)

        self.radio_scroll, self.radio_list_layout = _scroll_list(page)
        layout.addWidget(self.radio_scroll, 1)

        stop_row = QHBoxLayout()
        self.radio_stop_button = QPushButton("■ Stop")
        self.radio_stop_button.clicked.connect(self._stop_radio)
        stop_row.addWidget(self.radio_stop_button)
        stop_row.addStretch()
        layout.addLayout(stop_row)
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
                preview_button.clicked.connect(lambda _checked=False, r=result: self._preview_radio_result_clicked(r))
                top.addWidget(preview_button)
                add_button = QPushButton("+ Add")
                add_button.clicked.connect(lambda _checked=False, r=result: self._add_radio_search_result_clicked(r))
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

    def _preview_radio_result_clicked(self, result):
        self._play_stream(result["stream_url"], result["name"])

    def _refresh_radio_stations(self):
        _clear_layout(self.radio_list_layout)
        self._radio_buttons = {}
        for record in list_radio_stations():
            row = QFrame()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(QLabel(record["name"]), 1)
            play_button = QPushButton("▶ Play")
            play_button.clicked.connect(lambda _checked=False, r=record: self._toggle_radio_station(r))
            row_layout.addWidget(play_button)
            remove_button = QPushButton("✕")
            remove_button.setFixedWidth(28)
            remove_button.clicked.connect(lambda _checked=False, r=record: self._remove_radio_station_clicked(r))
            row_layout.addWidget(remove_button)
            self._radio_buttons[record["id"]] = play_button
            self.radio_list_layout.insertWidget(self.radio_list_layout.count() - 1, row)
        self._sync_radio_button_labels()

    def _sync_radio_button_labels(self):
        for station_id, button in self._radio_buttons.items():
            button.setText("⏸ Stop" if station_id == self._playing_station_id else "▶ Play")

    def _play_stream(self, stream_url, label, station_id=None):
        self._media_player.setSource(QUrl(stream_url))
        self._media_player.play()
        self._playing_station_id = station_id
        self.radio_status_label.setText(f'Playing "{label}"...')
        self._sync_radio_button_labels()

    def _toggle_radio_station(self, record):
        if self._playing_station_id == record["id"]:
            self._stop_radio()
            return
        self._play_stream(record["stream_url"], record["name"], station_id=record["id"])

    def _stop_radio(self):
        self._media_player.stop()
        self._playing_station_id = None
        self.radio_status_label.setText("Stopped.")
        self._sync_radio_button_labels()

    def _on_audio_outputs_changed(self):
        self._audio_output.setDevice(QMediaDevices.defaultAudioOutput())

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
        if self._playing_station_id == record["id"]:
            self._stop_radio()
        remove_radio_station(record["id"])
        self.radio_status_label.setText(f'Removed "{record["name"]}".')
        self._refresh_radio_stations()
