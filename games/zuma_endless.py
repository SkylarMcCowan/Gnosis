"""An endless Zuma clone: a chain of colored balls spirals inward along a
fixed track toward a shooter parked at the center. Match 3+ of the same
color to pop them; survive as long as possible while the chain speeds up
and more colors get mixed in over time. No levels, no ending track - it
just keeps going until a ball reaches the center.

Pure PyQt6 (QPainter + QTimer), no extra dependencies - the same pattern
webagent_gui.py's mouth-animation widget already uses for a self-painted,
timer-driven widget.
"""
import json
import math
import os
import random
import time
from bisect import bisect_left

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core import config as core_config

CANVAS_WIDTH = 880
CANVAS_HEIGHT = 560

BALL_RADIUS = 16
BALL_SPACING = BALL_RADIUS * 2
PROJECTILE_SPEED = 640.0  # px/sec

CHAIN_SPEED_START = 42.0  # px/sec
CHAIN_SPEED_MAX = 130.0
CHAIN_SPEED_STEP = 8.0
DIFFICULTY_INTERVAL = 20.0  # seconds between each ramp-up

SPAWN_INTERVAL = 1.1  # seconds between new balls appended at the back

PALETTE = [
    QColor("#e5484d"),  # red
    QColor("#4c8bf5"),  # blue
    QColor("#3ecf8e"),  # green
    QColor("#f5c344"),  # yellow
    QColor("#7c5cff"),  # purple (matches the app's own accent color)
    QColor("#f5799d"),  # pink
]
STARTING_COLOR_COUNT = 4

BG_CANVAS = QColor("#12121a")
TRACK_COLOR = QColor("#2a2a38")
TEXT_COLOR = QColor("#eaeaf2")
MUTED_COLOR = QColor("#9494a6")


def _spiral_path_samples(width, height, turns=2.2, sample_count=700):
    """An inward Archimedean spiral from an outer edge to a small central
    hole, sampled into many points - built parametrically instead of from
    hand-picked waypoints, so it's guaranteed smooth and always fits
    whatever canvas size it's given. The shooter sits at the spiral's own
    center, which is both visually authentic to Zuma (the frog usually
    sits in the middle of the track) and keeps aiming math trivial (every
    shot just radiates outward from one fixed point).
    """
    cx, cy = width / 2, height / 2
    r_outer = min(width, height) / 2 - 30
    r_inner = 34
    theta_max = turns * 2 * math.pi
    b = (r_outer - r_inner) / theta_max
    samples = []
    for i in range(sample_count + 1):
        theta = theta_max * i / sample_count
        r = r_outer - b * theta
        x = cx + r * math.cos(theta)
        y = cy + r * math.sin(theta) * 0.86  # slight vertical squash for a rectangular canvas
        samples.append((x, y))
    return samples, (cx, cy)


def _cumulative_lengths(samples):
    cum = [0.0]
    for i in range(1, len(samples)):
        x0, y0 = samples[i - 1]
        x1, y1 = samples[i]
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    return cum


class ZumaEndlessWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(CANVAS_WIDTH, CANVAS_HEIGHT)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.path_samples, self.shooter_pos = _spiral_path_samples(CANVAS_WIDTH, CANVAS_HEIGHT)
        self.path_cum = _cumulative_lengths(self.path_samples)
        self.total_length = self.path_cum[-1]

        saved = self._load_save()
        if saved:
            self._restore_from_save(saved)
        else:
            self.high_score = 0
            self._reset_game()

        self._last_tick = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.save_now)
        self.autosave_timer.start(15_000)

    # ------------------------------------------------------------------
    # Game state
    # ------------------------------------------------------------------
    def _reset_game(self):
        self.state = "playing"  # or "game_over"
        self.chain = []
        self.projectiles = []
        self.score = 0
        self.combo_level = 0
        self.elapsed = 0.0
        self.chain_speed = CHAIN_SPEED_START
        self.color_count = STARTING_COLOR_COUNT
        self.spawn_timer = 0.0
        self.difficulty_timer = 0.0
        self.aim_angle = -math.pi / 2  # pointing up initially
        self.loaded_color = self._random_color()
        self.next_color = self._random_color()
        # A short head start so the player isn't immediately under pressure.
        for i in range(4):
            self.chain.append({"color": self._random_color(), "dist": i * BALL_SPACING})

    def _random_color(self):
        return PALETTE[random.randrange(self.color_count)]

    # ------------------------------------------------------------------
    # Path geometry
    # ------------------------------------------------------------------
    def _point_at(self, dist):
        dist = max(0.0, min(dist, self.total_length))
        i = bisect_left(self.path_cum, dist)
        if i <= 0:
            return self.path_samples[0]
        if i >= len(self.path_samples):
            return self.path_samples[-1]
        d0, d1 = self.path_cum[i - 1], self.path_cum[i]
        p0, p1 = self.path_samples[i - 1], self.path_samples[i]
        t = 0.0 if d1 == d0 else (dist - d0) / (d1 - d0)
        return (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)

    def _nearest_path_dist(self, x, y):
        best_i, best_d2 = 0, float("inf")
        for i, (sx, sy) in enumerate(self.path_samples):
            d2 = (sx - x) ** 2 + (sy - y) ** 2
            if d2 < best_d2:
                best_d2, best_i = d2, i
        return self.path_cum[best_i]

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------
    def _tick(self):
        now = time.monotonic()
        dt = min(now - self._last_tick, 0.05)  # clamp so a stall/pause never causes a huge jump
        self._last_tick = now
        if self.state == "playing":
            self.elapsed += dt
            self._update_difficulty(dt)
            self._update_chain(dt)
            self._update_projectiles(dt)
        self.update()

    def _update_difficulty(self, dt):
        self.difficulty_timer += dt
        if self.difficulty_timer < DIFFICULTY_INTERVAL:
            return
        self.difficulty_timer = 0.0
        self.chain_speed = min(CHAIN_SPEED_MAX, self.chain_speed + CHAIN_SPEED_STEP)
        self.color_count = min(len(PALETTE), self.color_count + 1)

    def _update_chain(self, dt):
        self.chain.sort(key=lambda b: b["dist"], reverse=True)
        ahead_dist = None
        for ball in self.chain:
            target = ball["dist"] + self.chain_speed * dt
            if ahead_dist is not None:
                target = min(target, ahead_dist - BALL_SPACING)
            ball["dist"] = target
            ahead_dist = ball["dist"]

        self.spawn_timer += dt
        back_clear = not self.chain or self.chain[-1]["dist"] >= BALL_SPACING
        if self.spawn_timer >= SPAWN_INTERVAL and back_clear:
            self.spawn_timer = 0.0
            self.chain.append({"color": self._random_color(), "dist": 0.0})

        if self.chain and self.chain[0]["dist"] >= self.total_length:
            self._trigger_game_over()

    def _update_projectiles(self, dt):
        survivors = []
        for p in self.projectiles:
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            if not (0 <= p["x"] <= self.width() and 0 <= p["y"] <= self.height()):
                continue
            hit = self._find_collision(p)
            if hit is not None:
                self._insert_ball(p["color"], hit, p["x"], p["y"])
                continue
            survivors.append(p)
        self.projectiles = survivors

    def _find_collision(self, projectile):
        for ball in self.chain:
            bx, by = self._point_at(ball["dist"])
            if math.hypot(bx - projectile["x"], by - projectile["y"]) < BALL_RADIUS * 2:
                return ball
        return None

    def _insert_ball(self, color, hit_ball, px, py):
        p_dist = self._nearest_path_dist(px, py)
        new_dist = hit_ball["dist"] + BALL_SPACING if p_dist > hit_ball["dist"] else hit_ball["dist"] - BALL_SPACING
        new_ball = {"color": color, "dist": max(0.0, new_dist)}
        self.chain.append(new_ball)
        self._resolve_matches(new_ball)

    def _resolve_matches(self, seed_ball):
        while True:
            ordered = sorted(self.chain, key=lambda b: b["dist"], reverse=True)
            idx = next(i for i, b in enumerate(ordered) if b is seed_ball)
            color = seed_ball["color"]
            lo = idx
            while lo > 0 and ordered[lo - 1]["color"] == color:
                lo -= 1
            hi = idx
            while hi < len(ordered) - 1 and ordered[hi + 1]["color"] == color:
                hi += 1
            run_len = hi - lo + 1
            if run_len < 3:
                self.combo_level = 0
                return
            removed = ordered[lo:hi + 1]
            for b in removed:
                self.chain.remove(b)
            self.combo_level += 1
            self.score += run_len * 10 * self.combo_level
            if self.score > self.high_score:
                self.high_score = self.score
            left_neighbor = ordered[lo - 1] if lo > 0 else None
            right_neighbor = ordered[hi + 1] if hi < len(ordered) - 1 else None
            if left_neighbor is not None and right_neighbor is not None and left_neighbor["color"] == right_neighbor["color"]:
                seed_ball = left_neighbor
                continue
            return

    def _trigger_game_over(self):
        self.state = "game_over"
        if self.score >= self.high_score:
            self.high_score = self.score
        self.save_now()

    # ------------------------------------------------------------------
    # Firing
    # ------------------------------------------------------------------
    def _fire(self):
        if self.state != "playing":
            return
        cx, cy = self.shooter_pos
        self.projectiles.append({
            "x": cx, "y": cy,
            "vx": math.cos(self.aim_angle) * PROJECTILE_SPEED,
            "vy": math.sin(self.aim_angle) * PROJECTILE_SPEED,
            "color": self.loaded_color,
        })
        self.loaded_color = self.next_color
        self.next_color = self._random_color()

    def _swap_loaded(self):
        if self.state != "playing":
            return
        self.loaded_color, self.next_color = self.next_color, self.loaded_color

    # ------------------------------------------------------------------
    # Persistence - the whole in-progress run, not just the high score, so
    # closing the app mid-game and reopening it resumes exactly where the
    # player left off. Same lazy-mkdir-on-write-only pattern as
    # core/activity_log.py and core/subscriptions.py: a read must never
    # create the directory, only a write does. In-flight projectiles are
    # dropped on save/restore - a transient visual detail, not meaningful
    # progress worth preserving.
    # ------------------------------------------------------------------
    def _save_path(self):
        return os.path.join(core_config.path("games"), "zuma_endless_save.json")

    def _load_save(self):
        path = self._save_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _restore_from_save(self, data):
        self.high_score = data.get("high_score", 0)
        self.state = data.get("state", "playing")
        self.score = data.get("score", 0)
        self.combo_level = data.get("combo_level", 0)
        self.elapsed = data.get("elapsed", 0.0)
        self.chain_speed = data.get("chain_speed", CHAIN_SPEED_START)
        self.color_count = data.get("color_count", STARTING_COLOR_COUNT)
        self.spawn_timer = data.get("spawn_timer", 0.0)
        self.difficulty_timer = data.get("difficulty_timer", 0.0)
        self.aim_angle = data.get("aim_angle", -math.pi / 2)
        self.loaded_color = QColor(data.get("loaded_color", "#e5484d"))
        self.next_color = QColor(data.get("next_color", "#4c8bf5"))
        self.projectiles = []
        self.chain = [{"color": QColor(b["color"]), "dist": b["dist"]} for b in data.get("chain", [])]
        if not self.chain:
            self._reset_game()

    def save_now(self):
        """Called periodically (self.autosave_timer) and by the main
        window before it closes - see webagent_gui.py's closeEvent."""
        data = {
            "high_score": self.high_score, "state": self.state, "score": self.score,
            "combo_level": self.combo_level, "elapsed": self.elapsed, "chain_speed": self.chain_speed,
            "color_count": self.color_count, "spawn_timer": self.spawn_timer,
            "difficulty_timer": self.difficulty_timer, "aim_angle": self.aim_angle,
            "loaded_color": self.loaded_color.name(), "next_color": self.next_color.name(),
            "chain": [{"color": b["color"].name(), "dist": b["dist"]} for b in self.chain],
        }
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
    def mouseMoveEvent(self, event):
        cx, cy = self.shooter_pos
        pos = event.position()
        self.aim_angle = math.atan2(pos.y() - cy, pos.x() - cx)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.state == "game_over":
                self._reset_game()
            else:
                self._fire()
        elif event.button() == Qt.MouseButton.RightButton:
            self._swap_loaded()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            if self.state == "game_over":
                self._reset_game()
            else:
                self._fire()
        elif event.key() == Qt.Key.Key_Q:
            self._swap_loaded()
        elif event.key() == Qt.Key.Key_R:
            self._reset_game()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), BG_CANVAS)

        self._draw_track(painter)
        self._draw_chain(painter)
        self._draw_projectiles(painter)
        self._draw_shooter(painter)
        self._draw_hud(painter)
        if self.state == "game_over":
            self._draw_game_over(painter)
        painter.end()

    def _draw_track(self, painter):
        pen = QPen(TRACK_COLOR, BALL_RADIUS * 2 + 6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        for i in range(1, len(self.path_samples)):
            x0, y0 = self.path_samples[i - 1]
            x1, y1 = self.path_samples[i]
            painter.drawLine(int(x0), int(y0), int(x1), int(y1))

    def _draw_ball(self, painter, x, y, color, radius=BALL_RADIUS):
        painter.setPen(QPen(QColor("#0c0c12"), 1.5))
        painter.setBrush(QBrush(color))
        painter.drawEllipse(int(x - radius), int(y - radius), radius * 2, radius * 2)

    def _draw_chain(self, painter):
        for ball in self.chain:
            x, y = self._point_at(ball["dist"])
            self._draw_ball(painter, x, y, ball["color"])

    def _draw_projectiles(self, painter):
        for p in self.projectiles:
            self._draw_ball(painter, p["x"], p["y"], p["color"], radius=BALL_RADIUS - 2)

    def _draw_shooter(self, painter):
        cx, cy = self.shooter_pos
        aim_len = 34
        ax = cx + math.cos(self.aim_angle) * aim_len
        ay = cy + math.sin(self.aim_angle) * aim_len
        painter.setPen(QPen(MUTED_COLOR, 2))
        painter.drawLine(int(cx), int(cy), int(ax), int(ay))

        painter.setPen(QPen(QColor("#484858"), 2))
        painter.setBrush(QBrush(QColor("#1c1c26")))
        painter.drawEllipse(int(cx - 24), int(cy - 24), 48, 48)

        self._draw_ball(painter, cx, cy, self.loaded_color, radius=BALL_RADIUS - 1)
        self._draw_ball(painter, cx + 30, cy + 30, self.next_color, radius=BALL_RADIUS - 6)

    def _draw_hud(self, painter):
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        painter.drawText(16, 28, f"Score: {self.score}")
        painter.setFont(QFont("Arial", 11))
        painter.setPen(QPen(MUTED_COLOR))
        painter.drawText(16, 48, f"High Score: {self.high_score}")
        painter.drawText(16, 66, f"Speed: {self.chain_speed:.0f} px/s")
        painter.drawText(self.width() - 210, 28, "Left click / Space: shoot")
        painter.drawText(self.width() - 210, 46, "Right click / Q: swap ball")

    def _draw_game_over(self, painter):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"Game Over\nScore: {self.score}\nClick to restart")
