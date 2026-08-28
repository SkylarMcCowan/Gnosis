"""Cozy World - a small picker of animated cozy scenes (fireplace, beach,
tent, cabin) you can sit and look at. Each scene is a hand-drawn QPainter
animation, no sprite assets.

Split the same way as idle_island.py: plain-Python scene definitions up top
(no Qt, unit-testable on its own) with the Qt widgets below as a thin UI
layer over that state.

Optionally audio-reactive: a background QThread reads the microphone (via
pyaudio, already a project dependency for voice mode) and emits a smoothed
0..1 loudness level that nudges each scene's animation - bigger fire,
windier waves/brighter sun, faster-twinkling stars. Off by default (never
auto-starts listening); if the mic can't be opened, the real error surfaces
in a dialog instead of the toggle silently doing nothing.
"""
import json
import math
import os
import random

from PyQt6.QtCore import QPointF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from core import config as core_config

try:
    import pyaudio
    PYAUDIO_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment-dependent
    pyaudio = None
    PYAUDIO_IMPORT_ERROR = str(exc)

try:
    import audioop
except Exception as exc:  # pragma: no cover - environment-dependent
    audioop = None
    if PYAUDIO_IMPORT_ERROR is None:
        PYAUDIO_IMPORT_ERROR = f"audioop unavailable: {exc}"

BG_PANEL = "#1e1e26"

# Each scene: (key, label, kind, default weather, default night, weather
# options offered in the UI). "kind" picks which paintEvent branch draws
# it; weather is only meaningful for the "cabin" kind.
SCENES = [
    {"key": "fireplace", "label": "🔥 Fireplace", "kind": "fireplace", "night": True, "weather": None, "weather_options": []},
    {"key": "beach", "label": "🏖️ Beach", "kind": "beach", "night": False, "weather": None, "weather_options": []},
    {"key": "tent", "label": "⛺ Tent", "kind": "tent", "night": True, "weather": None, "weather_options": []},
    {"key": "cabin", "label": "🏡 Cabin", "kind": "cabin", "night": True, "weather": "rain", "weather_options": ["clear", "rain", "snow"]},
]
SCENES_BY_KEY = {s["key"]: s for s in SCENES}
DEFAULT_SCENE_KEY = SCENES[0]["key"]


# ----------------------------------------------------------------------
# Persistence - remembers only which scene you last had open, same
# lazy-mkdir-on-write-only discipline as core/subscriptions.py: a read
# must never create the directory.
# ----------------------------------------------------------------------

DEFAULT_STATE = {"last_scene": DEFAULT_SCENE_KEY}


def _state_path():
    return os.path.join(core_config.path("games"), "cozy_world_state.json")


def load_state():
    path = _state_path()
    if not os.path.isfile(path):
        return dict(DEFAULT_STATE)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    state = {**DEFAULT_STATE, **data}
    if state["last_scene"] not in SCENES_BY_KEY:
        state["last_scene"] = DEFAULT_SCENE_KEY
    return state


def save_state(state):
    path = _state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ----------------------------------------------------------------------
# Audio reactivity
# ----------------------------------------------------------------------

AUDIO_CHUNK = 1024
AUDIO_RATE = 44100
# RMS value that maps to level=1.0 - tuned against normal room/speech
# volume, not a physical limit; loud sustained sound just clips at 1.0.
AUDIO_NORMALIZE_MAX = 4000


def list_input_devices():
    """[(device_index, name), ...] for every audio input device pyaudio can
    see, or [] if pyaudio/audioop aren't available - never raises, since
    this runs at tab-build time and a missing audio backend shouldn't take
    the whole tab down with it (the UI shows this as a disabled toggle with
    an explanatory tooltip instead)."""
    if pyaudio is None or audioop is None:
        return []
    try:
        pa = pyaudio.PyAudio()
    except Exception:
        return []
    try:
        devices = []
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                devices.append((i, info["name"]))
        return devices
    finally:
        pa.terminate()


def describe_audio_error(exc):
    text = str(exc) or type(exc).__name__
    lowered = text.lower()
    if "permission" in lowered or "not authorized" in lowered or "denied" in lowered or "not permitted" in lowered:
        return (
            f"{text}\n\nMicrophone access may be blocked. Check System Settings → "
            "Privacy & Security → Microphone and allow this app, then try again."
        )
    return text


class AudioLevelWorker(QThread):
    level_changed = pyqtSignal(float)
    error_occurred = pyqtSignal(str)

    def __init__(self, device_index):
        super().__init__()
        self.device_index = device_index
        self._running = True
        self._smoothed = 0.0

    def stop(self):
        self._running = False

    def run(self):
        pa = pyaudio.PyAudio()
        # PortAudio can segfault the whole process on a stale/out-of-range
        # device index instead of raising a catchable exception - re-check
        # the device is still there (e.g. a USB mic unplugged after the
        # dropdown was populated) before ever calling open().
        try:
            info = pa.get_device_info_by_index(self.device_index) if self.device_index is not None else None
        except Exception:
            info = None
        if self.device_index is not None and (info is None or info.get("maxInputChannels", 0) <= 0):
            self.error_occurred.emit(
                f"Audio input device (index {self.device_index}) is no longer available - "
                "it may have been disconnected. Reopen this tab to refresh the device list."
            )
            pa.terminate()
            return
        try:
            stream = pa.open(
                format=pyaudio.paInt16, channels=1, rate=AUDIO_RATE, input=True,
                frames_per_buffer=AUDIO_CHUNK, input_device_index=self.device_index,
            )
        except Exception as e:
            self.error_occurred.emit(describe_audio_error(e))
            pa.terminate()
            return

        try:
            while self._running:
                try:
                    data = stream.read(AUDIO_CHUNK, exception_on_overflow=False)
                except Exception as e:
                    self.error_occurred.emit(describe_audio_error(e))
                    break
                raw_level = audioop.rms(data, 2) / AUDIO_NORMALIZE_MAX
                level = min(1.0, raw_level)
                # exponential smoothing so scenes pulse rather than jitter
                self._smoothed = self._smoothed * 0.7 + level * 0.3
                self.level_changed.emit(self._smoothed)
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()


# ----------------------------------------------------------------------
# The scene itself
# ----------------------------------------------------------------------


class CozySceneWidget(QWidget):
    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.is_night = scene["night"]
        self.weather = scene["weather"]
        self.audio_level = 0.0  # 0..1, nudged live by AudioLevelWorker when audio-reactive is on
        self._phase = 0
        self.setMinimumHeight(360)

        rng = random.Random(scene["key"])
        self._stars = [(rng.random(), rng.random(), rng.uniform(0, 6.283)) for _ in range(80)]
        self._drops = [[rng.random(), rng.random()] for _ in range(120)]
        self._waves = [rng.uniform(0, 6.283) for _ in range(4)]
        self._embers = [[rng.random(), rng.random(), rng.uniform(0, 6.283)] for _ in range(24)]

        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def stop(self):
        self.timer.stop()

    def set_weather(self, weather):
        self.weather = weather
        self.update()

    def set_night(self, is_night):
        self.is_night = is_night
        self.update()

    def _tick(self):
        self._phase += 1
        if self.weather in ("rain", "snow"):
            speed = 0.03 if self.weather == "rain" else 0.01
            for drop in self._drops:
                drop[1] += speed
                if drop[1] > 1:
                    drop[1] = 0
        for ember in self._embers:
            ember[1] -= 0.01
            if ember[1] < 0:
                ember[0] = random.Random(self._phase + id(ember)).random()
                ember[1] = 1.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        kind = self.scene["kind"]
        if kind == "fireplace":
            self._paint_fireplace(painter, w, h)
        elif kind == "beach":
            self._paint_beach(painter, w, h)
        elif kind == "tent":
            self._paint_outdoor(painter, w, h, structure="tent")
        elif kind == "cabin":
            self._paint_outdoor(painter, w, h, structure="cabin")
        painter.end()

    # ------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------
    def _sky_gradient(self, w, h, day_top, day_bottom, night_top, night_bottom):
        gradient = QLinearGradient(0, 0, 0, h)
        if self.is_night:
            gradient.setColorAt(0, QColor(night_top))
            gradient.setColorAt(1, QColor(night_bottom))
        else:
            gradient.setColorAt(0, QColor(day_top))
            gradient.setColorAt(1, QColor(day_bottom))
        return gradient

    def _draw_stars_and_sky_body(self, painter, w, h, sky_h_fraction=0.6):
        level = self.audio_level
        body_cx, body_cy = w * 0.78 + 23, h * 0.12 + 23
        if self.is_night:
            twinkle_speed = 0.05 + level * 0.15
            for sx, sy, phase in self._stars:
                twinkle = 0.5 + 0.5 * math.sin(self._phase * twinkle_speed + phase)
                alpha = min(255, int(120 + (120 + level * 100) * twinkle))
                painter.setPen(QPen(QColor(255, 255, 255, alpha)))
                painter.drawPoint(int(sx * w), int(sy * h * sky_h_fraction))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(200, 210, 255, int(30 + level * 90)))
            painter.drawEllipse(QPointF(body_cx, body_cy), 23 + level * 18, 23 + level * 18)
            painter.setBrush(QColor("#f4f1de"))
            painter.drawEllipse(int(w * 0.78), int(h * 0.12), 46, 46)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 240, 180, int(40 + level * 100)))
            painter.drawEllipse(QPointF(body_cx, body_cy), 28 + level * 22, 28 + level * 22)
            painter.setBrush(QColor("#fff7e0"))
            painter.drawEllipse(int(w * 0.78), int(h * 0.12), 56, 56)

    def _draw_weather(self, painter, w, h):
        if self.weather == "rain":
            painter.setPen(QPen(QColor(180, 200, 255, 160), 1))
            for x, y in self._drops:
                px, py = x * w, y * h
                painter.drawLine(int(px), int(py), int(px - 2), int(py + 8))
        elif self.weather == "snow":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 220))
            for x, y in self._drops:
                px, py = x * w, y * h
                painter.drawEllipse(int(px), int(py), 3, 3)

    def _draw_flame(self, painter, cx, base_y, scale, phase_offset=0.0):
        colors = [QColor(255, 140, 20, 230), QColor(255, 190, 60, 230), QColor(255, 235, 150, 230)]
        for i, color in enumerate(colors):
            jitter = math.sin(self._phase * 0.3 + phase_offset + i) * 0.15 * scale
            flame_h = scale * (1.0 - i * 0.28) + jitter
            flame_w = scale * (0.55 - i * 0.12)
            cy = base_y - flame_h / 2
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(cx + jitter * 0.4, cy), flame_w / 2, flame_h / 2)

    # ------------------------------------------------------------
    # Fireplace - an indoor hearth, no sky
    # ------------------------------------------------------------
    def _paint_fireplace(self, painter, w, h):
        gradient = QLinearGradient(0, 0, 0, h)
        gradient.setColorAt(0, QColor("#241512"))
        gradient.setColorAt(1, QColor("#120a08"))
        painter.fillRect(0, 0, w, h, gradient)

        rug_w, rug_h = int(w * 0.6), int(h * 0.12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#5c1f1f"))
        painter.drawEllipse((w - rug_w) // 2, int(h * 0.82), rug_w, rug_h)

        hearth_w, hearth_h = int(w * 0.42), int(h * 0.55)
        hx, hy = (w - hearth_w) // 2, int(h * 0.28)
        painter.setBrush(QColor("#3a3a3f"))
        painter.drawRoundedRect(hx, hy, hearth_w, hearth_h, 12, 12)

        inner_margin = 16
        painter.setBrush(QColor("#0c0806"))
        painter.drawRoundedRect(
            hx + inner_margin, hy + inner_margin,
            hearth_w - inner_margin * 2, hearth_h - inner_margin * 2 - 20, 8, 8,
        )

        painter.setBrush(QColor("#2b2b2b"))
        for i, lx in enumerate(range(hx + inner_margin + 10, hx + hearth_w - inner_margin, 18)):
            painter.drawRect(lx, hy + hearth_h - 40, 14, 8)

        boost = 1.0 + self.audio_level * 0.8
        base_y = hy + hearth_h - 30
        self._draw_flame(painter, hx + hearth_w * 0.4, base_y, 70 * boost, phase_offset=0.0)
        self._draw_flame(painter, hx + hearth_w * 0.55, base_y, 55 * boost, phase_offset=1.7)
        self._draw_flame(painter, hx + hearth_w * 0.48, base_y, 40 * boost, phase_offset=3.1)

        glow_gradient = QLinearGradient(0, hy, 0, h)
        glow_gradient.setColorAt(0, QColor(255, 150, 60, int(60 + self.audio_level * 110)))
        glow_gradient.setColorAt(1, QColor(255, 150, 60, 0))
        painter.setBrush(glow_gradient)
        painter.drawRect(0, hy, w, h - hy)

        painter.setBrush(QColor(255, 170, 60, 160))
        painter.setPen(Qt.PenStyle.NoPen)
        for ex, ey, phase in self._embers:
            twinkle = 0.5 + 0.5 * math.sin(self._phase * 0.2 + phase)
            px = hx + hearth_w * 0.5 + (ex - 0.5) * hearth_w * 0.5
            py = base_y - ey * hearth_h * 0.7
            painter.drawEllipse(QPointF(px, py), 2 + twinkle, 2 + twinkle)

    # ------------------------------------------------------------
    # Beach - sand, ocean, sun/moon, gentle waves
    # ------------------------------------------------------------
    def _paint_beach(self, painter, w, h):
        wind = self.audio_level
        gradient = self._sky_gradient(w, h, "#8fd3f4", "#fdeec4", "#0a1533", "#233a5c")
        painter.fillRect(0, 0, w, h, gradient)
        self._draw_stars_and_sky_body(painter, w, h, sky_h_fraction=0.55)

        ocean_top = int(h * 0.55)
        sand_top = int(h * 0.78)
        ocean_gradient = QLinearGradient(0, ocean_top, 0, sand_top)
        if self.is_night:
            ocean_gradient.setColorAt(0, QColor("#123a52"))
            ocean_gradient.setColorAt(1, QColor("#0a2438"))
        else:
            ocean_gradient.setColorAt(0, QColor("#2b8fc4"))
            ocean_gradient.setColorAt(1, QColor("#1c6f9e"))
        painter.setBrush(ocean_gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(0, ocean_top, w, sand_top - ocean_top)

        painter.setPen(QPen(QColor(255, 255, 255, 130), 2))
        for i, phase in enumerate(self._waves):
            y_base = ocean_top + 20 + i * ((sand_top - ocean_top - 30) / len(self._waves))
            points = []
            for x in range(0, w + 20, 20):
                y = y_base + math.sin(self._phase * (0.08 + wind * 0.06) + x * 0.05 + phase) * (4 + wind * 12)
                points.append(QPointF(x, y))
            for a, b in zip(points, points[1:]):
                painter.drawLine(a, b)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8c07d"))
        painter.drawRect(0, sand_top, w, h - sand_top)

        trunk_x = int(w * 0.15)
        painter.setBrush(QColor("#3a2a1a"))
        painter.drawRect(trunk_x, sand_top - 70, 8, 70)
        sway = math.sin(self._phase * (0.03 + wind * 0.04)) * (6 + wind * 22)
        for angle in (-40, -10, 20, 50):
            leaf = QPolygonF([
                QPointF(trunk_x + 4, sand_top - 70),
                QPointF(trunk_x + 4 + 55 * math.cos(math.radians(angle)) + sway,
                        sand_top - 70 - 55 * math.sin(math.radians(angle))),
                QPointF(trunk_x + 4 + 20 * math.cos(math.radians(angle + 20)),
                        sand_top - 70 - 20 * math.sin(math.radians(angle + 20))),
            ])
            painter.setBrush(QColor("#1f6b3a"))
            painter.drawPolygon(leaf)

    # ------------------------------------------------------------
    # Tent / cabin - shared outdoor-at-night composition
    # ------------------------------------------------------------
    def _paint_outdoor(self, painter, w, h, structure):
        gradient = self._sky_gradient(w, h, "#8fd3f4", "#dce9f0", "#050912", "#16243a")
        painter.fillRect(0, 0, w, h, gradient)
        self._draw_stars_and_sky_body(painter, w, h, sky_h_fraction=0.6)

        ground_top = int(h * 0.78)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#3a5a35") if not self.is_night else QColor("#1f3320"))
        painter.drawRect(0, ground_top, w, h - ground_top + 1)

        cx = w // 2

        if structure == "cabin":
            cabin_w, cabin_h = 120, 70
            left = cx - cabin_w // 2
            top = ground_top - cabin_h
            painter.setBrush(QColor("#20140f"))
            painter.drawRect(left, top, cabin_w, cabin_h)
            roof = QPolygonF([
                QPointF(left - 10, top), QPointF(left + cabin_w / 2, top - 45), QPointF(left + cabin_w + 10, top),
            ])
            painter.drawPolygon(roof)
            glow = 0.6 + 0.4 * math.sin(self._phase * 0.08)
            painter.setBrush(QColor(255, 200, 90, int(180 + 60 * glow)))
            painter.drawRect(left + 20, top + 20, 22, 22)
            painter.drawRect(left + cabin_w - 42, top + 20, 22, 22)
            self._draw_weather(painter, w, h)
        else:  # tent
            tent_w, tent_h = 110, 85
            left = cx - tent_w // 2
            top = ground_top - tent_h
            painter.setBrush(QColor("#4a3423"))
            body = QPolygonF([
                QPointF(left, ground_top), QPointF(cx, top), QPointF(left + tent_w, ground_top),
            ])
            painter.drawPolygon(body)
            painter.setBrush(QColor("#2a1c12"))
            entrance = QPolygonF([
                QPointF(cx - 16, ground_top), QPointF(cx, top + 25), QPointF(cx + 16, ground_top),
            ])
            painter.drawPolygon(entrance)

            fire_x = left - 55
            painter.setBrush(QColor("#6b6b6b"))
            for i in range(5):
                angle = i * (360 / 5)
                painter.drawEllipse(
                    QPointF(fire_x + 14 * math.cos(math.radians(angle)), ground_top + 6 * math.sin(math.radians(angle))),
                    5, 3,
                )
            self._draw_flame(painter, fire_x, ground_top - 4, 34 * (1.0 + self.audio_level * 0.8), phase_offset=0.5)

            painter.setBrush(QColor(255, 170, 60, 140))
            painter.setPen(Qt.PenStyle.NoPen)
            for ex, ey, phase in self._embers:
                twinkle = 0.5 + 0.5 * math.sin(self._phase * 0.2 + phase)
                px = fire_x + (ex - 0.5) * 30
                py = ground_top - 10 - ey * 60
                painter.drawEllipse(QPointF(px, py), 1.5 + twinkle, 1.5 + twinkle)


# ----------------------------------------------------------------------
# Main widget - a row of scene buttons plus the active scene
# ----------------------------------------------------------------------


class CozyWorldWidget(QWidget):
    def __init__(self):
        super().__init__()
        # Plain QWidgets don't reliably inherit an ancestor's stylesheet
        # background (needs the widget's own stylesheet to trigger
        # WA_STYLED_BACKGROUND painting) - set explicitly so this page
        # isn't left showing the default light system background.
        self.setStyleSheet(f"background-color: {BG_PANEL};")
        state = load_state()
        self.current_key = state["last_scene"]
        self.scene_widget = None
        self.audio_worker = None
        self.current_audio_level = 0.0

        layout = QVBoxLayout(self)

        picker_row = QHBoxLayout()
        self.scene_buttons = {}
        for scene in SCENES:
            button = QPushButton(scene["label"])
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, key=scene["key"]: self.show_scene(key))
            picker_row.addWidget(button)
            self.scene_buttons[scene["key"]] = button
        picker_row.addStretch()
        layout.addLayout(picker_row)

        layout.addLayout(self._build_audio_row())

        self.controls_row = QHBoxLayout()
        layout.addLayout(self.controls_row)

        self.scene_container = QVBoxLayout()
        layout.addLayout(self.scene_container, 1)

        self.show_scene(self.current_key)

    def _build_audio_row(self):
        # Never auto-starts listening, even if the user had it on last
        # session - opening this tab shouldn't turn the mic on by itself.
        row = QHBoxLayout()
        self.audio_toggle_button = QPushButton("\U0001F399️ Audio Reactive: Off")
        self.audio_toggle_button.setCheckable(True)
        self.audio_toggle_button.clicked.connect(self._toggle_audio)
        row.addWidget(self.audio_toggle_button)

        row.addWidget(QLabel("Input:"))
        self.audio_device_combo = QComboBox()
        devices = list_input_devices()
        if devices:
            for index, name in devices:
                self.audio_device_combo.addItem(name, index)
        else:
            self.audio_device_combo.addItem("No input devices found")
            self.audio_device_combo.setEnabled(False)
            self.audio_toggle_button.setEnabled(False)
            self.audio_toggle_button.setToolTip(PYAUDIO_IMPORT_ERROR or "No audio input devices found.")
        row.addWidget(self.audio_device_combo)

        self.audio_level_bar = QProgressBar()
        self.audio_level_bar.setRange(0, 100)
        self.audio_level_bar.setValue(0)
        self.audio_level_bar.setFixedWidth(120)
        self.audio_level_bar.setTextVisible(False)
        row.addWidget(self.audio_level_bar)
        row.addStretch()
        return row

    def _toggle_audio(self, checked):
        if checked:
            device_index = self.audio_device_combo.currentData()
            self.audio_worker = AudioLevelWorker(device_index)
            self.audio_worker.level_changed.connect(self._on_audio_level)
            self.audio_worker.error_occurred.connect(self._on_audio_error)
            self.audio_worker.start()
            self.audio_toggle_button.setText("\U0001F399️ Audio Reactive: On")
            self.audio_device_combo.setEnabled(False)
        else:
            self._stop_audio()
            self.audio_toggle_button.setText("\U0001F399️ Audio Reactive: Off")
            self.audio_device_combo.setEnabled(True)
            self.current_audio_level = 0.0
            self.audio_level_bar.setValue(0)
            if self.scene_widget is not None:
                self.scene_widget.audio_level = 0.0

    def _stop_audio(self):
        if self.audio_worker is not None:
            self.audio_worker.stop()
            self.audio_worker.wait(2000)
            self.audio_worker = None

    def _on_audio_level(self, level):
        self.current_audio_level = level
        self.audio_level_bar.setValue(int(level * 100))
        if self.scene_widget is not None:
            self.scene_widget.audio_level = level

    def _on_audio_error(self, message):
        QMessageBox.critical(self, "Audio input error", message)
        self.audio_toggle_button.setChecked(False)
        self._toggle_audio(False)

    def show_scene(self, key):
        if self.scene_widget is not None:
            self.scene_widget.stop()
            self.scene_widget.setParent(None)
            self.scene_widget = None

        self.current_key = key
        for scene_key, button in self.scene_buttons.items():
            button.setChecked(scene_key == key)

        while self.controls_row.count():
            item = self.controls_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        scene = SCENES_BY_KEY[key]
        self.scene_widget = CozySceneWidget(scene)
        self.scene_widget.audio_level = self.current_audio_level

        night_button = QPushButton("☀️/\U0001F319 Day/Night")
        night_button.clicked.connect(lambda: self.scene_widget.set_night(not self.scene_widget.is_night))
        self.controls_row.addWidget(night_button)

        for weather in scene["weather_options"]:
            label = {"clear": "\U0001F324 Clear", "rain": "\U0001F327 Rain", "snow": "❄️ Snow"}[weather]
            button = QPushButton(label)
            button.clicked.connect(lambda _checked, wv=weather: self.scene_widget.set_weather(wv))
            self.controls_row.addWidget(button)
        self.controls_row.addStretch()

        self.scene_container.addWidget(self.scene_widget)
        self._save()

    def _save(self):
        save_state({"last_scene": self.current_key})

    def save_now(self):
        """Called by the main window before it closes - see
        webagent_gui.py's closeEvent."""
        if self.scene_widget is not None:
            self.scene_widget.stop()
        self._stop_audio()
        self._save()
