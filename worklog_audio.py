"""Tiny synthesized sound-effect player for the Work Tracker's Focus Timer -
same approach as games/audio.py: no external audio assets, no extra
dependencies. Effects are built from plain sine waves and filtered noise
(stdlib `wave`/`math`/`random`/`struct` only), written once as real .wav
files under core_config.path("worklog", "sounds") and cached there
permanently, then played via QSoundEffect (part of QtMultimedia, which
ships bundled with PyQt6-Qt6 - no separate install).

Two effects: "bell" (a short three-strike ding, played once when a work or
break session's countdown hits zero) and "breeze" (a soft, slowly-swelling
filtered-noise loop, played on repeat for as long as a break's countdown is
actively running).
"""
import math
import os
import random
import struct
import wave

from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QSoundEffect

from core import config as core_config

SAMPLE_RATE = 44100


def _bell_strike_samples(duration=0.4, fundamental=1567.98, volume=0.5):
    """One percussive bell strike: a fundamental plus a couple of
    inharmonic partials, each decaying fast - what makes it read as a
    struck bell instead of a sustained organ tone."""
    partials = ((1.0, 1.0), (2.4, 0.5), (3.9, 0.25))
    n = max(1, int(SAMPLE_RATE * duration))
    samples = [0.0] * n
    for ratio, amp in partials:
        freq = fundamental * ratio
        for i in range(n):
            t = i / SAMPLE_RATE
            samples[i] += math.sin(2 * math.pi * freq * t) * amp * math.exp(-t * 10)
    peak = max((abs(s) for s in samples), default=1.0) or 1.0
    attack_n = max(1, int(SAMPLE_RATE * 0.003))
    return [(s / peak) * volume * min(1.0, i / attack_n) for i, s in enumerate(samples)]


def _bell_recipe():
    """Three quick dings back to back - the classic "timer's up" pattern,
    played once whenever a work or break countdown reaches zero."""
    strike = _bell_strike_samples()
    gap = [0.0] * int(SAMPLE_RATE * 0.18)
    return strike + gap + strike + gap + strike


def _breeze_recipe(duration=10.0, volume=0.3):
    """Filtered noise with a slow amplitude swell - approximates a beach
    breeze/wave-wash ambience for the break's calm period. Loops via
    QSoundEffect, so both ends fade to silence to keep the seam quiet."""
    n = int(SAMPLE_RATE * duration)
    rng = random.Random()

    filtered = [0.0] * n
    alpha = 0.06  # one-pole low-pass: smaller = softer, less hissy "wind"
    prev = 0.0
    for i in range(n):
        prev += alpha * (rng.uniform(-1, 1) - prev)
        filtered[i] = prev
    peak = max((abs(v) for v in filtered), default=1.0) or 1.0

    swell_freq = 0.12  # Hz - one slow gust roughly every 8 seconds
    fade_n = int(SAMPLE_RATE * 0.4)
    out = [0.0] * n
    for i in range(n):
        t = i / SAMPLE_RATE
        swell = 0.6 + 0.4 * math.sin(2 * math.pi * swell_freq * t)
        edge_fade = min(1.0, i / fade_n, (n - i) / fade_n)
        out[i] = (filtered[i] / peak) * swell * volume * edge_fade
    return out


EFFECT_RECIPES = {
    "bell": _bell_recipe,
    "breeze": _breeze_recipe,
}


def _sounds_dir():
    return os.path.join(core_config.path("worklog"), "sounds")


def _effect_path(name):
    return os.path.join(_sounds_dir(), f"{name}.wav")


def _write_wav(path, samples):
    with wave.open(path, "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        frames = b"".join(struct.pack("<h", max(-32767, min(32767, int(v * 32767)))) for v in samples)
        f.writeframes(frames)


def _ensure_effect_file(name):
    path = _effect_path(name)
    if not os.path.isfile(path):
        os.makedirs(_sounds_dir(), exist_ok=True)
        _write_wav(path, EFFECT_RECIPES[name]())
    return path


class SoundPlayer:
    """One QSoundEffect per effect name, created lazily and cached.
    `enabled` is a plain toggle a caller can flip (e.g. a mute button)
    without tearing anything down."""

    def __init__(self):
        self.enabled = True
        self._effects = {}

    def _get(self, name):
        if name not in self._effects:
            path = _ensure_effect_file(name)
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(path))
            effect.setVolume(0.55)
            self._effects[name] = effect
        return self._effects[name]

    def play_once(self, name):
        if not self.enabled or name not in EFFECT_RECIPES:
            return
        try:
            effect = self._get(name)
            effect.setLoopCount(1)
            effect.play()
        except Exception:
            pass

    def start_loop(self, name):
        """No-op if that effect is already looping - QSoundEffect.play()
        restarts from the beginning, so calling this every tick would
        make the ambience stutter instead of playing continuously."""
        if not self.enabled or name not in EFFECT_RECIPES:
            return
        try:
            effect = self._get(name)
            if effect.isPlaying():
                return
            effect.setLoopCount(-2)  # QSoundEffect.Loop.Infinite
            effect.play()
        except Exception:
            pass

    def stop_loop(self, name):
        if name not in self._effects:
            return
        try:
            self._effects[name].stop()
        except Exception:
            pass

    def stop_all(self):
        for effect in self._effects.values():
            try:
                effect.stop()
            except Exception:
                pass
