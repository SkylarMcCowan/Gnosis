"""A Wipeout-style anti-gravity racer: pilot a hover-ship around a closed
neon circuit against three AI rivals, sliding through corners, grabbing
speed pads, and bouncing off the barriers when you clip a wall. Three laps,
best lap and best race time are the only things persisted - a race is a
few-minute session, not an in-progress board worth freezing mid-game like
games/zuma_endless.py, so there's no full-state resume here.

Pure PyQt6 (QPainter + QTimer), no extra dependencies - same pattern as the
other games/ widgets.
"""
import json
import math
import os
import random
import time

from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF, QRadialGradient
from PyQt6.QtWidgets import QWidget

from core import config as core_config
from games.start_screen import consume_start_input, draw_start_screen

CANVAS_WIDTH = 880
CANVAS_HEIGHT = 560

TRACK_HALF_WIDTH = 92.0
LAPS_TO_WIN = 3
COUNTDOWN_SECONDS = 3.0

# World-space control points for the circuit's centerline - a closed loop,
# smoothed into a dense sample list by a Catmull-Rom spline (see
# _closed_catmull_rom below) rather than driven on directly, so the track
# reads as a set of sweeping curves instead of straight-line segments
# between hand-picked points.
TRACK_CONTROL_POINTS = [
    (0, 0), (420, -60), (760, -220), (900, -520), (700, -760),
    (300, -720), (120, -560), (260, -380), (140, -200), (-260, -260),
    (-560, -140), (-680, 160), (-460, 420), (-100, 380), (60, 180),
]
SAMPLES_PER_SEGMENT = 22

# Speed pads sit at fixed cumulative-distance fractions around the loop.
BOOST_PAD_FRACTIONS = [0.08, 0.30, 0.55, 0.78]
BOOST_PAD_HALF_LEN = 26.0
BOOST_SPEED = 760.0
BOOST_DURATION = 1.6

THRUST_ACCEL = 560.0
BRAKE_ACCEL = 720.0
NATURAL_DECEL = 90.0
MAX_FORWARD_SPEED = 560.0
MAX_REVERSE_SPEED = -160.0
TURN_RATE = 2.9  # rad/sec at full effectiveness
LATERAL_GRIP = 7.0  # per-second decay applied to sideways velocity - higher = less drift
LATERAL_GRIP_DRIFT = 0.9  # grip while holding the handbrake, for a Wipeout-ish power-slide
WALL_BOUNCE_DAMPING = 0.45

AI_BASE_SPEED = 380.0
AI_SPEED_VARIATION = 40.0
AI_RUBBER_BAND = 0.06  # fraction of the progress gap converted into a speed adjustment
AI_LANE_OFFSETS = [-46.0, 0.0, 46.0]

TRAIL_LIFETIME = 0.5

BG_CANVAS = QColor("#0b0620")
GRID_COLOR = QColor(124, 92, 255, 40)
TRACK_SURFACE = QColor("#1c1430")
TRACK_EDGE_A = QColor("#3ef7ff")
TRACK_EDGE_B = QColor("#ff3ec8")
CENTERLINE_COLOR = QColor(255, 255, 255, 35)
TEXT_COLOR = QColor("#eaeaf2")
MUTED_COLOR = QColor("#9494a6")
BOOST_COLOR = QColor("#f5c344")
PLAYER_COLOR = QColor("#3ef7ff")
AI_COLORS = [QColor("#ff3ec8"), QColor("#7c5cff"), QColor("#3ecf8e")]


def _catmull_rom_point(p0, p1, p2, p3, t):
    t2 = t * t
    t3 = t2 * t
    x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
               + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
               + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
    y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
               + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
               + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
    return (x, y)


def _closed_catmull_rom(points, samples_per_segment):
    n = len(points)
    samples = []
    for i in range(n):
        p0 = points[(i - 1) % n]
        p1 = points[i]
        p2 = points[(i + 1) % n]
        p3 = points[(i + 2) % n]
        for s in range(samples_per_segment):
            samples.append(_catmull_rom_point(p0, p1, p2, p3, s / samples_per_segment))
    return samples


def _cumulative_lengths(samples, closed=True):
    cum = [0.0]
    count = len(samples) + (1 if closed else 0)
    for i in range(1, count):
        x0, y0 = samples[(i - 1) % len(samples)]
        x1, y1 = samples[i % len(samples)]
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    return cum


def _tangent_at(samples, i):
    n = len(samples)
    x0, y0 = samples[(i - 1) % n]
    x1, y1 = samples[(i + 1) % n]
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1.0
    return dx / length, dy / length


class _Racer:
    """Shared per-ship progress bookkeeping: which sample index it's
    nearest to (for rendering and wall/pad checks), how many laps it's
    completed, and its total cumulative distance traveled (for the HUD's
    race order and AI rubber-banding) - used for both the player and the
    AI opponents."""

    def __init__(self, color, is_player=False, lane_offset=0.0):
        self.color = color
        self.is_player = is_player
        self.lane_offset = lane_offset
        self.nearest_index = 0
        self.laps = 0
        # Signed cumulative arc-length traveled since the race started - the
        # authoritative progress measure (see _shortest_cum_delta). Raw
        # nearest-sample-index fractions are NOT safe for this: the sample
        # just before the finish line and the sample just after it are
        # spatially adjacent (that's what makes it a closed loop), so a car
        # merely idling at the start could flip between them and look like
        # it crossed the line.
        self.dist_traveled = 0.0
        self.finished = False
        self.finish_time = None
        self.boost_timer = 0.0

    def progress(self):
        return self.dist_traveled


class NeonRacerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(CANVAS_WIDTH, CANVAS_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.centerline = _closed_catmull_rom(TRACK_CONTROL_POINTS, SAMPLES_PER_SEGMENT)
        self.cum = _cumulative_lengths(self.centerline, closed=True)
        self.total_length = self.cum[-1]
        self.sample_count = len(self.centerline)
        self.boost_pad_indices = [
            int(frac * self.sample_count) for frac in BOOST_PAD_FRACTIONS
        ]

        self.best_lap_time, self.best_race_time = self._load_best_times()
        self.started = False  # gated by a start screen - see games/start_screen.py
        self._keys_down = set()
        self._reset_race()

        self._last_tick = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # ------------------------------------------------------------------
    # Track geometry helpers
    # ------------------------------------------------------------------
    def _nearest_index_near(self, x, y, hint, window=40):
        best_i, best_d2 = hint, float("inf")
        for offset in range(-window, window + 1):
            i = (hint + offset) % self.sample_count
            sx, sy = self.centerline[i]
            d2 = (sx - x) ** 2 + (sy - y) ** 2
            if d2 < best_d2:
                best_d2, best_i = d2, i
        return best_i, math.sqrt(best_d2)

    def _signed_offset(self, x, y, index):
        sx, sy = self.centerline[index]
        tx, ty = _tangent_at(self.centerline, index)
        nx, ny = -ty, tx  # left-hand perpendicular
        return (x - sx) * nx + (y - sy) * ny

    def _shortest_cum_delta(self, old_index, new_index):
        """Real-distance delta between two nearest-sample lookups, taking
        whichever direction around the closed loop is shorter. A search
        right at the start/finish line can report a big raw index jump
        (idx 7 -> idx 315, say) even though the car barely moved, because
        both samples sit right next to the line; wrapping the delta into
        (-total_length/2, total_length/2] turns that into the tiny distance
        it actually is instead of a bogus near-full-lap jump."""
        delta = self.cum[new_index] - self.cum[old_index]
        half = self.total_length / 2
        if delta > half:
            delta -= self.total_length
        elif delta < -half:
            delta += self.total_length
        return delta

    # ------------------------------------------------------------------
    # Race state
    # ------------------------------------------------------------------
    def _reset_race(self):
        self.state = "countdown"  # countdown -> racing -> finished
        self.countdown = COUNTDOWN_SECONDS
        start_x, start_y = self.centerline[0]
        self.player = _Racer(PLAYER_COLOR, is_player=True)
        self.px, self.py = start_x, start_y
        start_tx, start_ty = _tangent_at(self.centerline, 0)
        self.pangle = math.atan2(start_ty, start_tx)
        self.pspeed = 0.0  # forward component
        self.plateral = 0.0  # sideways (drift) component
        self.race_elapsed = 0.0
        self.lap_elapsed = 0.0
        self.last_lap_time = None
        self.trail = []
        self.wipeout_flash = 0.0

        self.ai = []
        for i, color in enumerate(AI_COLORS):
            racer = _Racer(color, lane_offset=AI_LANE_OFFSETS[i % len(AI_LANE_OFFSETS)])
            racer.speed_bias = random.uniform(-AI_SPEED_VARIATION, AI_SPEED_VARIATION)
            racer.wobble_phase = random.uniform(0, math.tau)
            self.ai.append(racer)

        self.camera_x, self.camera_y = start_x, start_y

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------
    def _tick(self):
        now = time.monotonic()
        dt = min(now - self._last_tick, 0.05)
        self._last_tick = now
        if not self.started:
            self.update()
            return
        if self.state == "countdown":
            self.countdown -= dt
            if self.countdown <= 0:
                self.state = "racing"
        elif self.state == "racing":
            self.race_elapsed += dt
            self.lap_elapsed += dt
            self._update_player(dt)
            self._update_ai(dt)
            self._update_trail(dt)
            self.wipeout_flash = max(0.0, self.wipeout_flash - dt)
        camera_k = 1 - math.exp(-6.0 * dt)
        self.camera_x += (self.px - self.camera_x) * camera_k
        self.camera_y += (self.py - self.camera_y) * camera_k
        self.update()

    def _update_player(self, dt):
        throttle = Qt.Key.Key_W in self._keys_down or Qt.Key.Key_Up in self._keys_down
        brake = Qt.Key.Key_S in self._keys_down or Qt.Key.Key_Down in self._keys_down
        left = Qt.Key.Key_A in self._keys_down or Qt.Key.Key_Left in self._keys_down
        right = Qt.Key.Key_D in self._keys_down or Qt.Key.Key_Right in self._keys_down
        drifting = Qt.Key.Key_Space in self._keys_down

        max_speed = BOOST_SPEED if self.player.boost_timer > 0 else MAX_FORWARD_SPEED
        if throttle:
            self.pspeed = min(max_speed, self.pspeed + THRUST_ACCEL * dt)
        elif brake:
            self.pspeed = max(MAX_REVERSE_SPEED, self.pspeed - BRAKE_ACCEL * dt)
        else:
            self.pspeed -= math.copysign(min(abs(self.pspeed), NATURAL_DECEL * dt), self.pspeed)

        if self.player.boost_timer > 0:
            self.player.boost_timer = max(0.0, self.player.boost_timer - dt)

        speed_factor = max(0.35, min(1.15, abs(self.pspeed) / 260.0))
        steer = (1 if right else 0) - (1 if left else 0)
        direction = 1 if self.pspeed >= 0 else -1
        self.pangle += steer * TURN_RATE * speed_factor * dt * direction

        grip = LATERAL_GRIP_DRIFT if drifting else LATERAL_GRIP
        self.plateral *= max(0.0, 1 - grip * dt)
        if drifting and steer != 0:
            self.plateral += steer * 90.0 * dt

        fx, fy = math.cos(self.pangle), math.sin(self.pangle)
        lx, ly = -fy, fx
        vx = fx * self.pspeed + lx * self.plateral
        vy = fy * self.pspeed + ly * self.plateral
        new_x = self.px + vx * dt
        new_y = self.py + vy * dt

        old_index = self.player.nearest_index
        self.player.nearest_index, _ = self._nearest_index_near(new_x, new_y, old_index)
        self.player.dist_traveled += self._shortest_cum_delta(old_index, self.player.nearest_index)
        offset = self._signed_offset(new_x, new_y, self.player.nearest_index)
        if abs(offset) > TRACK_HALF_WIDTH:
            sx, sy = self.centerline[self.player.nearest_index]
            tx, ty = _tangent_at(self.centerline, self.player.nearest_index)
            nx, ny = -ty, tx
            along = (new_x - sx) * tx + (new_y - sy) * ty
            clamped = math.copysign(TRACK_HALF_WIDTH, offset)
            new_x = sx + nx * clamped + tx * along
            new_y = sy + ny * clamped + ty * along
            self.pspeed *= WALL_BOUNCE_DAMPING
            self.plateral *= WALL_BOUNCE_DAMPING
            self.wipeout_flash = 0.25

        self.px, self.py = new_x, new_y
        self._check_boost_pad(self.player)
        self._advance_lap_tracking(self.player)
        if self.player.laps >= LAPS_TO_WIN and not self.player.finished:
            self._finish_race(self.player)

    def _update_ai(self, dt):
        for racer in self.ai:
            gap = self.player.progress() - racer.progress()
            rubber_band = max(-70.0, min(70.0, gap * AI_RUBBER_BAND))
            wobble = math.sin(self.race_elapsed * 1.3 + racer.wobble_phase) * 12.0
            speed = AI_BASE_SPEED + racer.speed_bias + rubber_band + wobble
            if racer.boost_timer > 0:
                speed = max(speed, BOOST_SPEED)
                racer.boost_timer = max(0.0, racer.boost_timer - dt)
            racer.dist_traveled += speed * dt
            racer.nearest_index = self._index_for_cum(racer.dist_traveled)
            self._check_boost_pad(racer)
            self._advance_lap_tracking(racer)
            if racer.laps >= LAPS_TO_WIN and not racer.finished:
                self._finish_race(racer)

    def _index_for_cum(self, target_cum):
        target_cum %= self.total_length
        lo, hi = 0, self.sample_count - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.cum[mid] < target_cum:
                lo = mid + 1
            else:
                hi = mid
        return lo % self.sample_count

    def _check_boost_pad(self, racer):
        if racer.boost_timer > 0:
            return
        for pad_index in self.boost_pad_indices:
            dist = abs(self.cum[racer.nearest_index] - self.cum[pad_index])
            dist = min(dist, self.total_length - dist)
            if dist <= BOOST_PAD_HALF_LEN:
                racer.boost_timer = BOOST_DURATION
                if racer.is_player:
                    self.pspeed = max(self.pspeed, BOOST_SPEED)
                break

    def _advance_lap_tracking(self, racer):
        new_laps = math.floor(racer.dist_traveled / self.total_length)
        if new_laps > racer.laps:
            if racer.is_player:
                self.last_lap_time = self.lap_elapsed
                if self.best_lap_time is None or self.lap_elapsed < self.best_lap_time:
                    self.best_lap_time = self.lap_elapsed
                self.lap_elapsed = 0.0
        racer.laps = max(0, new_laps)

    def _finish_race(self, racer):
        racer.finished = True
        racer.finish_time = self.race_elapsed
        if racer.is_player:
            self.state = "finished"
            if self.best_race_time is None or self.race_elapsed < self.best_race_time:
                self.best_race_time = self.race_elapsed
            self.save_now()

    def _update_trail(self, dt):
        self.trail.append([self.px, self.py, TRAIL_LIFETIME])
        for point in self.trail:
            point[2] -= dt
        self.trail = [p for p in self.trail if p[2] > 0]

    def _current_place(self):
        all_racers = [self.player] + self.ai
        ranked = sorted(all_racers, key=lambda r: r.progress(), reverse=True)
        return ranked.index(self.player) + 1, len(all_racers)

    # ------------------------------------------------------------------
    # Persistence - only the records, not mid-race state (see module
    # docstring). Same lazy-mkdir-on-write pattern as
    # games/zuma_endless.py's save file.
    # ------------------------------------------------------------------
    def _save_path(self):
        return os.path.join(core_config.path("games"), "neon_racer_save.json")

    def _load_best_times(self):
        try:
            with open(self._save_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("best_lap_time"), data.get("best_race_time")
        except (OSError, ValueError, json.JSONDecodeError):
            return None, None

    def save_now(self):
        """Called by the main window before it closes - see
        webagent_gui.py's closeEvent - and right when a race finishes."""
        data = {"best_lap_time": self.best_lap_time, "best_race_time": self.best_race_time}
        path = self._save_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def keyPressEvent(self, event):
        if consume_start_input(self):
            return
        if event.isAutoRepeat():
            return
        if event.key() == Qt.Key.Key_R:
            self._reset_race()
            return
        self._keys_down.add(event.key())

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat():
            return
        self._keys_down.discard(event.key())

    def focusOutEvent(self, event):
        # Without this, a key held down when focus leaves the widget (e.g.
        # switching tabs mid-throttle) would never get its release event
        # and the ship would keep accelerating forever in the background.
        self._keys_down.clear()
        super().focusOutEvent(event)

    def mousePressEvent(self, event):
        if consume_start_input(self):
            return

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _world_to_screen(self, x, y):
        return (x - self.camera_x + CANVAS_WIDTH / 2, y - self.camera_y + CANVAS_HEIGHT / 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), BG_CANVAS)

        self._draw_grid(painter)
        self._draw_track(painter)
        self._draw_boost_pads(painter)
        self._draw_trail(painter)
        self._draw_ai(painter)
        self._draw_player(painter)
        if self.wipeout_flash > 0:
            painter.fillRect(self.rect(), QColor(255, 60, 60, int(60 * self.wipeout_flash / 0.25)))
        self._draw_hud(painter)

        if not self.started:
            draw_start_screen(painter, self.rect(), "Neon Racer", [
                "Anti-gravity racing - 3 laps against 3 rivals on a closed neon circuit.",
                "W/Up thrust, S/Down brake, A/D or arrows steer, Space to power-slide.",
                "Hit the glowing pads for a speed boost. R restarts the race.",
                "Click or press any key to begin.",
            ])
        elif self.state == "countdown":
            self._draw_countdown(painter)
        elif self.state == "finished":
            self._draw_finish(painter)
        painter.end()

    def _draw_grid(self, painter):
        spacing = 80
        offset_x = self.camera_x % spacing
        offset_y = self.camera_y % spacing
        painter.setPen(QPen(GRID_COLOR, 1))
        x = -offset_x
        while x < CANVAS_WIDTH:
            painter.drawLine(int(x), 0, int(x), CANVAS_HEIGHT)
            x += spacing
        y = -offset_y
        while y < CANVAS_HEIGHT:
            painter.drawLine(0, int(y), CANVAS_WIDTH, int(y))
            y += spacing

    def _draw_track(self, painter):
        pen = QPen(TRACK_SURFACE, TRACK_HALF_WIDTH * 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path_screen = [self._world_to_screen(x, y) for x, y in self.centerline]
        for i in range(len(path_screen)):
            x0, y0 = path_screen[i - 1]
            x1, y1 = path_screen[i]
            painter.drawLine(int(x0), int(y0), int(x1), int(y1))

        for edge_color, side in ((TRACK_EDGE_A, 1), (TRACK_EDGE_B, -1)):
            painter.setPen(QPen(edge_color, 3))
            pts = []
            for i in range(len(self.centerline)):
                sx, sy = self.centerline[i]
                tx, ty = _tangent_at(self.centerline, i)
                nx, ny = -ty, tx
                pts.append(self._world_to_screen(sx + nx * TRACK_HALF_WIDTH * side, sy + ny * TRACK_HALF_WIDTH * side))
            for i in range(len(pts)):
                x0, y0 = pts[i - 1]
                x1, y1 = pts[i]
                painter.drawLine(int(x0), int(y0), int(x1), int(y1))

        start_x, start_y = self._world_to_screen(*self.centerline[0])
        tx, ty = _tangent_at(self.centerline, 0)
        nx, ny = -ty, tx
        painter.setPen(QPen(CENTERLINE_COLOR, 6))
        painter.drawLine(
            int(start_x + nx * TRACK_HALF_WIDTH), int(start_y + ny * TRACK_HALF_WIDTH),
            int(start_x - nx * TRACK_HALF_WIDTH), int(start_y - ny * TRACK_HALF_WIDTH),
        )

    def _draw_boost_pads(self, painter):
        for pad_index in self.boost_pad_indices:
            sx, sy = self._world_to_screen(*self.centerline[pad_index])
            if not (-40 < sx < CANVAS_WIDTH + 40 and -40 < sy < CANVAS_HEIGHT + 40):
                continue
            painter.setPen(QPen(BOOST_COLOR, 2))
            painter.setBrush(QBrush(QColor(245, 195, 68, 90)))
            painter.drawEllipse(QPointF(sx, sy), 20, 20)

    def _draw_trail(self, painter):
        for x, y, life in self.trail:
            sx, sy = self._world_to_screen(x, y)
            alpha = int(120 * (life / TRAIL_LIFETIME))
            painter.setBrush(QBrush(QColor(62, 247, 255, alpha)))
            painter.setPen(Qt.PenStyle.NoPen)
            r = 3 + 3 * (life / TRAIL_LIFETIME)
            painter.drawEllipse(QPointF(sx, sy), r, r)

    def _draw_ship(self, painter, x, y, angle, color, glow=False):
        sx, sy = self._world_to_screen(x, y)
        if glow:
            gradient = QRadialGradient(QPointF(sx, sy), 26)
            glow_color = QColor(color)
            glow_color.setAlpha(110)
            gradient.setColorAt(0.0, glow_color)
            gradient.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
            painter.setBrush(QBrush(gradient))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(sx, sy), 26, 26)

        length, width = 16.0, 10.0
        nose = QPointF(sx + math.cos(angle) * length, sy + math.sin(angle) * length)
        back_angle_a = angle + math.pi * 0.78
        back_angle_b = angle - math.pi * 0.78
        left = QPointF(sx + math.cos(back_angle_a) * width, sy + math.sin(back_angle_a) * width)
        right = QPointF(sx + math.cos(back_angle_b) * width, sy + math.sin(back_angle_b) * width)
        painter.setPen(QPen(QColor("#0c0c12"), 1.5))
        painter.setBrush(QBrush(color))
        painter.drawPolygon(QPolygonF([nose, left, right]))

    def _draw_ai(self, painter):
        for racer in self.ai:
            sx, sy = self.centerline[racer.nearest_index]
            tx, ty = _tangent_at(self.centerline, racer.nearest_index)
            nx, ny = -ty, tx
            x = sx + nx * racer.lane_offset
            y = sy + ny * racer.lane_offset
            angle = math.atan2(ty, tx)
            self._draw_ship(painter, x, y, angle, racer.color)

    def _draw_player(self, painter):
        self._draw_ship(painter, self.px, self.py, self.pangle, PLAYER_COLOR, glow=True)

    def _draw_hud(self, painter):
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        lap_display = min(self.player.laps + 1, LAPS_TO_WIN)
        painter.drawText(16, 28, f"Lap {lap_display}/{LAPS_TO_WIN}")

        place, total = self._current_place()
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(place, "th")
        painter.drawText(16, 50, f"{place}{suffix} / {total}")

        painter.setFont(QFont("Arial", 11))
        painter.setPen(QPen(MUTED_COLOR))
        painter.drawText(16, 70, f"Speed: {abs(self.pspeed):.0f}")
        painter.drawText(16, 88, f"Time: {self.race_elapsed:0.1f}s")
        if self.best_lap_time is not None:
            painter.drawText(self.width() - 200, 28, f"Best lap: {self.best_lap_time:0.1f}s")
        if self.best_race_time is not None:
            painter.drawText(self.width() - 200, 46, f"Best race: {self.best_race_time:0.1f}s")
        if self.player.boost_timer > 0:
            painter.setPen(QPen(BOOST_COLOR))
            painter.drawText(self.width() - 200, 64, "BOOST")

    def _draw_countdown(self, painter):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 48, QFont.Weight.Bold))
        label = str(max(1, math.ceil(self.countdown))) if self.countdown > 0 else "GO!"
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, label)

    def _draw_finish(self, painter):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 160))
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 26, QFont.Weight.Bold))
        place, total = self._current_place()
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(place, "th")
        text = f"Race Complete!\nFinished {place}{suffix} / {total}\nTime: {self.race_elapsed:0.1f}s\nR to race again"
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
