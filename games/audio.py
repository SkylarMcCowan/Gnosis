"""Tiny synthesized sound-effect player - no external audio assets, no
extra dependencies. Effects are short chiptune-style tone sequences built
from plain sine/square waves (stdlib `wave`/`math`/`struct` only), written
once as real .wav files under core_config.path("games","sounds") and
cached there permanently, then played via QSoundEffect (part of
QtMultimedia, which ships bundled with PyQt6-Qt6 - no separate install).
"""
import math
import os
import struct
import wave

from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QSoundEffect

from core import config as core_config

SAMPLE_RATE = 44100


def _envelope(i, n, attack=0.05, release=0.35):
    """A simple attack/sustain/release amplitude curve - without this,
    every tone starts and ends with an abrupt sample jump that clicks/pops
    audibly; fading in and out removes it."""
    t = i / n if n else 1.0
    if t < attack:
        return t / attack
    if t > 1 - release:
        return max(0.0, (1 - t) / release)
    return 1.0


def _tone_samples(frequency, duration, volume=0.4, wave_shape="sine"):
    n = max(1, int(SAMPLE_RATE * duration))
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        if wave_shape == "square":
            raw = 1.0 if math.sin(2 * math.pi * frequency * t) >= 0 else -1.0
        else:
            raw = math.sin(2 * math.pi * frequency * t)
        samples.append(raw * _envelope(i, n) * volume)
    return samples


def _sequence(notes):
    """notes: list of (frequency, duration[, volume[, wave_shape]]) played
    back to back, silence-free (each note carries its own fade so the
    splice between notes doesn't click)."""
    out = []
    for note in notes:
        frequency, duration = note[0], note[1]
        volume = note[2] if len(note) > 2 else 0.4
        wave_shape = note[3] if len(note) > 3 else "sine"
        out.extend(_tone_samples(frequency, duration, volume, wave_shape))
    return out


def _write_wav(path, samples):
    with wave.open(path, "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        frames = b"".join(struct.pack("<h", max(-32767, min(32767, int(v * 32767)))) for v in samples)
        f.writeframes(frames)


# ----------------------------------------------------------------------
# Effect recipes - short, original, chiptune-style; no sampled/recorded
# audio, so no licensing question to worry about.
# ----------------------------------------------------------------------
def _cast_recipe():
    return _sequence([(300, 0.05, 0.3), (200, 0.06, 0.28), (140, 0.08, 0.22)])


def _catch_common_recipe():
    return _sequence([(660, 0.07, 0.3), (880, 0.1, 0.32)])


def _catch_epic_recipe():
    return _sequence([(660, 0.07, 0.32), (880, 0.07, 0.34), (1100, 0.16, 0.4)])


def _catch_legendary_recipe():
    return _sequence([(523, 0.09, 0.38), (659, 0.09, 0.4), (784, 0.09, 0.42), (1047, 0.28, 0.5)])


def _purchase_recipe():
    return _sequence([(440, 0.045, 0.22), (660, 0.06, 0.26)])


def _prestige_recipe():
    return _sequence([(392, 0.11, 0.38), (523, 0.11, 0.4), (659, 0.11, 0.42), (784, 0.11, 0.44), (1047, 0.32, 0.5)])


def _fail_recipe():
    return _sequence([(220, 0.09, 0.3, "square"), (160, 0.16, 0.28, "square")])


def _tetris_move_recipe():
    return _sequence([(180, 0.03, 0.14)])


def _tetris_rotate_recipe():
    return _sequence([(260, 0.04, 0.18)])


def _tetris_lock_recipe():
    return _sequence([(140, 0.05, 0.22, "square")])


def _tetris_line_recipe():
    return _sequence([(523, 0.06, 0.3), (659, 0.06, 0.32), (784, 0.08, 0.34)])


def _tetris_tetris_recipe():
    return _sequence([(523, 0.07, 0.35), (659, 0.07, 0.37), (784, 0.07, 0.4), (1047, 0.22, 0.48)])


def _tetris_level_up_recipe():
    return _sequence([(392, 0.08, 0.3), (523, 0.08, 0.32), (659, 0.16, 0.36)])


def _tetris_game_over_recipe():
    return _sequence([(220, 0.12, 0.3, "square"), (180, 0.12, 0.28, "square"), (140, 0.22, 0.26, "square")])


def _hangman_correct_recipe():
    return _sequence([(660, 0.07, 0.3), (880, 0.09, 0.32)])


def _hangman_wrong_recipe():
    return _sequence([(200, 0.09, 0.28, "square"), (150, 0.12, 0.26, "square")])


def _hangman_win_recipe():
    return _sequence([(523, 0.09, 0.36), (659, 0.09, 0.38), (784, 0.09, 0.4), (1047, 0.3, 0.48)])


def _hangman_lose_recipe():
    return _sequence([(220, 0.14, 0.3, "square"), (160, 0.14, 0.28, "square"), (110, 0.3, 0.26, "square")])


EFFECT_RECIPES = {
    "cast": _cast_recipe,
    "catch_common": _catch_common_recipe,
    "catch_epic": _catch_epic_recipe,
    "catch_legendary": _catch_legendary_recipe,
    "purchase": _purchase_recipe,
    "prestige": _prestige_recipe,
    "fail": _fail_recipe,
    "tetris_move": _tetris_move_recipe,
    "tetris_rotate": _tetris_rotate_recipe,
    "tetris_lock": _tetris_lock_recipe,
    "tetris_line": _tetris_line_recipe,
    "tetris_tetris": _tetris_tetris_recipe,
    "tetris_level_up": _tetris_level_up_recipe,
    "tetris_game_over": _tetris_game_over_recipe,
    "hangman_correct": _hangman_correct_recipe,
    "hangman_wrong": _hangman_wrong_recipe,
    "hangman_win": _hangman_win_recipe,
    "hangman_lose": _hangman_lose_recipe,
}


def _sounds_dir():
    return os.path.join(core_config.path("games"), "sounds")


def _effect_path(name):
    return os.path.join(_sounds_dir(), f"{name}.wav")


def _ensure_effect_file(name):
    path = _effect_path(name)
    if not os.path.isfile(path):
        os.makedirs(_sounds_dir(), exist_ok=True)
        _write_wav(path, EFFECT_RECIPES[name]())
    return path


class SoundPlayer:
    """One QSoundEffect per effect name, created lazily and cached - so
    repeated catches just call .play() on an already-loaded effect rather
    than reconstructing/reloading anything. `enabled` is a plain toggle a
    caller can flip (e.g. from a Settings checkbox) without tearing
    anything down."""

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

    def play(self, name):
        if not self.enabled or name not in EFFECT_RECIPES:
            return
        try:
            self._get(name).play()
        except Exception:
            pass
