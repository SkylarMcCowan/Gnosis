"""Tests for games/cozy_world.py's pure-Python scene registry/persistence
layer - no Qt involved, same split as test_worklog.py. core.config._root_override
is redirected to a scratch dir by the autouse isolated_data_dir fixture in
conftest.py, so persistence tests never touch the project's real games/ dir.
"""
import pytest

from games import cozy_world as cw


def test_every_scene_has_required_fields():
    for scene in cw.SCENES:
        assert scene["key"]
        assert scene["label"]
        assert scene["kind"] in ("fireplace", "beach", "tent", "cabin")
        assert isinstance(scene["weather_options"], list)


def test_scenes_by_key_matches_scenes_list():
    assert set(cw.SCENES_BY_KEY) == {s["key"] for s in cw.SCENES}
    for scene in cw.SCENES:
        assert cw.SCENES_BY_KEY[scene["key"]] is scene


def test_default_scene_key_is_a_real_scene():
    assert cw.DEFAULT_SCENE_KEY in cw.SCENES_BY_KEY


# ----------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------


def test_load_state_on_missing_file_does_not_create_directory(tmp_path):
    assert cw.load_state() == cw.DEFAULT_STATE
    assert not (tmp_path / "games").exists()


def test_save_then_load_state_round_trips():
    cw.save_state({"last_scene": "beach"})
    assert cw.load_state() == {"last_scene": "beach"}


def test_load_state_falls_back_to_default_for_unknown_scene_key():
    cw.save_state({"last_scene": "not-a-real-scene"})
    assert cw.load_state() == {"last_scene": cw.DEFAULT_SCENE_KEY}


# ----------------------------------------------------------------------
# Audio reactivity - list_input_devices()/describe_audio_error() never
# touch the mic (only pyaudio's device-listing API), so these are safe to
# run without a live capture and without any permission prompt.
# ----------------------------------------------------------------------


def test_list_input_devices_returns_tuples_or_empty():
    devices = cw.list_input_devices()
    assert isinstance(devices, list)
    for entry in devices:
        index, name = entry
        assert isinstance(index, int)
        assert isinstance(name, str) and name


def test_describe_audio_error_adds_privacy_hint_for_permission_errors():
    for message in ("Operation not permitted", "Permission denied", "Not authorized"):
        described = cw.describe_audio_error(RuntimeError(message))
        assert "Privacy" in described
        assert message in described


def test_describe_audio_error_passes_through_unrelated_errors():
    described = cw.describe_audio_error(RuntimeError("device is busy"))
    assert described == "device is busy"
    assert "Privacy" not in described


def test_audio_level_worker_on_stale_device_index_emits_error_not_crash():
    """The realistic version of a stale device (unplugged after the
    dropdown was populated, or otherwise no longer enumerable) - opening
    a wildly out-of-range index directly can segfault PortAudio itself
    (not a catchable Python exception), so the worker must reject it
    before ever calling pyaudio.open()."""
    pytest.importorskip("pyaudio")
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])  # noqa: F841 - must stay referenced or PyQt GCs it mid-test
    worker = cw.AudioLevelWorker(999999)
    errors = []
    worker.error_occurred.connect(errors.append)
    worker.start()

    loop = QEventLoop()
    QTimer.singleShot(1500, loop.quit)
    loop.exec()
    worker.wait(2000)

    assert errors
    assert "no longer available" in errors[0]
