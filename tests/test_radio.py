"""Tests for radio.py's backend (live-station search/bookmarks, the
music/audiobook library, and soundscape synthesis) - no Qt involved, same
split as test_weather_station.py. core.config._root_override is redirected
to a scratch dir by the autouse isolated_data_dir fixture in conftest.py.
"""
import math
import os
import wave

import pytest

import radio


class _FakeResponse:
    def __init__(self, payload, status_ok=True):
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            import requests
            raise requests.RequestException("boom")

    def json(self):
        return self._payload


# ----------------------------------------------------------------------
# Live radio - search + saved-station store
# ----------------------------------------------------------------------
def test_search_radio_stations_keeps_only_stations_with_a_stream_url(monkeypatch):
    payload = [
        {"name": "Station A", "url_resolved": "https://example.com/a", "country": "USA", "state": "", "tags": "", "bitrate": 128},
        {"name": "No Stream", "url_resolved": "", "url": "", "country": "USA"},
    ]
    monkeypatch.setattr(radio.requests, "get", lambda *a, **k: _FakeResponse(payload))
    results = radio.search_radio_stations("lofi")
    assert len(results) == 1
    assert results[0]["stream_url"] == "https://example.com/a"


def test_search_radio_stations_returns_none_on_empty_query():
    assert radio.search_radio_stations("") is None
    assert radio.search_radio_stations("   ") is None


def test_search_radio_stations_returns_none_on_request_failure(monkeypatch):
    monkeypatch.setattr(radio.requests, "get", lambda *a, **k: _FakeResponse([], status_ok=False))
    assert radio.search_radio_stations("weather") is None


def test_radio_station_store_starts_empty_without_creating_a_directory(tmp_path):
    assert radio.list_radio_stations() == []
    assert not (tmp_path / "weather_station").exists()


def test_add_and_list_radio_station():
    record = radio.add_radio_station("Example Station", "https://example.com/stream.mp3")
    assert record["name"] == "Example Station"
    assert radio.list_radio_stations() == [record]


def test_add_radio_station_requires_name_and_url():
    with pytest.raises(ValueError):
        radio.add_radio_station("", "https://example.com/stream.mp3")
    with pytest.raises(ValueError):
        radio.add_radio_station("Example Station", "")


def test_add_radio_station_rejects_a_duplicate_stream_url():
    radio.add_radio_station("Example Station", "https://example.com/stream.mp3")
    with pytest.raises(ValueError):
        radio.add_radio_station("Different Name", "https://example.com/stream.mp3")
    assert len(radio.list_radio_stations()) == 1


def test_remove_radio_station():
    record = radio.add_radio_station("Example Station", "https://example.com/stream.mp3")
    assert radio.remove_radio_station(record["id"]) is True
    assert radio.list_radio_stations() == []
    assert radio.remove_radio_station(record["id"]) is False


# ----------------------------------------------------------------------
# Music & audiobook library
# ----------------------------------------------------------------------
def test_add_library_paths_finds_audio_files_recursively(tmp_path):
    (tmp_path / "album").mkdir()
    (tmp_path / "album" / "track1.mp3").write_bytes(b"fake")
    (tmp_path / "album" / "notes.txt").write_bytes(b"not audio")
    (tmp_path / "album" / "sub").mkdir()
    (tmp_path / "album" / "sub" / "track2.flac").write_bytes(b"fake")

    added = radio.add_library_paths([str(tmp_path / "album")], kind="music")
    assert {r["title"] for r in added} == {"track1", "track2"}
    assert all(r["kind"] == "music" for r in added)
    assert all(r["position_ms"] == 0 for r in added)


def test_add_library_paths_skips_already_added_files(tmp_path):
    file_path = tmp_path / "book.m4b"
    file_path.write_bytes(b"fake")
    first = radio.add_library_paths([str(file_path)], kind="audiobook")
    second = radio.add_library_paths([str(file_path)], kind="audiobook")
    assert len(first) == 1
    assert second == []
    assert len(radio.list_library_items()) == 1


def test_remove_library_item(tmp_path):
    file_path = tmp_path / "song.mp3"
    file_path.write_bytes(b"fake")
    [record] = radio.add_library_paths([str(file_path)])
    assert radio.remove_library_item(record["id"]) is True
    assert radio.list_library_items() == []
    assert radio.remove_library_item(record["id"]) is False


def test_update_library_position_persists_and_is_clamped_nonnegative(tmp_path):
    file_path = tmp_path / "book.mp3"
    file_path.write_bytes(b"fake")
    [record] = radio.add_library_paths([str(file_path)], kind="audiobook")
    assert radio.update_library_position(record["id"], 4200) is True
    assert radio.list_library_items()[0]["position_ms"] == 4200
    radio.update_library_position(record["id"], -50)
    assert radio.list_library_items()[0]["position_ms"] == 0


def test_update_library_position_clears_a_stale_finished_flag(tmp_path):
    # Regression: resuming a finished chapter must not stay marked finished
    # once real playback progress comes in for it.
    file_path = tmp_path / "book.mp3"
    file_path.write_bytes(b"fake")
    [record] = radio.add_library_paths([str(file_path)], kind="audiobook")
    radio.set_library_finished(record["id"], True)
    radio.update_library_position(record["id"], 3000)
    [reloaded] = radio.list_library_items()
    assert reloaded["finished"] is False
    assert reloaded["position_ms"] == 3000


def test_set_library_finished_resets_position_either_direction(tmp_path):
    file_path = tmp_path / "book.mp3"
    file_path.write_bytes(b"fake")
    [record] = radio.add_library_paths([str(file_path)], kind="audiobook")
    radio.update_library_position(record["id"], 9000)

    assert radio.set_library_finished(record["id"], True) is True
    [reloaded] = radio.list_library_items()
    assert reloaded["finished"] is True
    assert reloaded["position_ms"] == 0

    radio.update_library_position(record["id"], 9000)
    assert radio.set_library_finished(record["id"], False) is True
    [reloaded] = radio.list_library_items()
    assert reloaded["finished"] is False
    assert reloaded["position_ms"] == 0

    assert radio.set_library_finished("not-a-real-id", True) is False


# ----------------------------------------------------------------------
# Authors / Series / Books catalog
# ----------------------------------------------------------------------
def test_add_author_requires_name_and_rejects_duplicates():
    with pytest.raises(ValueError):
        radio.add_author("")
    author = radio.add_author("Brandon Sanderson")
    with pytest.raises(ValueError):
        radio.add_author("brandon sanderson")  # case-insensitive dup
    assert radio.list_authors() == [author]


def test_remove_author_blocked_while_books_reference_it():
    author = radio.add_author("Brandon Sanderson")
    radio.add_book("The Way of Kings", author["id"])
    with pytest.raises(ValueError):
        radio.remove_author(author["id"])


def test_add_series_requires_name_and_author():
    author = radio.add_author("Brandon Sanderson")
    with pytest.raises(ValueError):
        radio.add_series("", author["id"])
    with pytest.raises(ValueError):
        radio.add_series("The Stormlight Archive", None)
    series = radio.add_series("The Stormlight Archive", author["id"], synopsis="Epic fantasy.")
    assert radio.list_series() == [series]
    assert series["last_played_book_id"] is None


def test_remove_series_unlinks_its_books_instead_of_deleting_them():
    author = radio.add_author("Brandon Sanderson")
    series = radio.add_series("The Stormlight Archive", author["id"])
    book = radio.add_book("The Way of Kings", author["id"], series_id=series["id"], series_index=1)
    assert radio.remove_series(series["id"]) is True
    [reloaded] = radio.list_books()
    assert reloaded["id"] == book["id"]
    assert reloaded["series_id"] is None
    assert reloaded["series_index"] is None


def test_add_book_requires_title_and_author():
    author = radio.add_author("Brandon Sanderson")
    with pytest.raises(ValueError):
        radio.add_book("", author["id"])
    with pytest.raises(ValueError):
        radio.add_book("The Way of Kings", None)


def test_update_book_validates_title_and_updates_fields():
    author = radio.add_author("Brandon Sanderson")
    book = radio.add_book("The Way of Kings", author["id"])
    with pytest.raises(ValueError):
        radio.update_book(book["id"], title="   ")
    updated = radio.update_book(book["id"], synopsis="A stormlight epic.")
    assert updated["synopsis"] == "A stormlight epic."
    assert updated["title"] == "The Way of Kings"
    with pytest.raises(ValueError):
        radio.update_book("not-a-real-id", title="x")


def test_remove_book_unassigns_its_files_instead_of_deleting_them(tmp_path):
    author = radio.add_author("Brandon Sanderson")
    book = radio.add_book("The Way of Kings", author["id"])
    file_path = tmp_path / "ch1.mp3"
    file_path.write_bytes(b"fake")
    [record] = radio.add_library_paths([str(file_path)], kind="audiobook")
    radio.assign_files_to_book([record["id"]], book["id"])
    assert radio.remove_book(book["id"]) is True
    assert radio.list_books() == []
    [reloaded] = radio.list_library_items()
    assert reloaded["book_id"] is None
    assert reloaded["track_order"] == 0


def _add_chapters(tmp_path, count):
    added = []
    for i in range(count):
        file_path = tmp_path / f"{i:02d} chapter.mp3"
        file_path.write_bytes(b"fake")
        [record] = radio.add_library_paths([str(file_path)], kind="audiobook")
        added.append(record)
    return added


def test_assign_files_to_book_orders_by_the_given_sequence_and_extends_existing_order(tmp_path):
    author = radio.add_author("Brandon Sanderson")
    book = radio.add_book("The Way of Kings", author["id"])
    chapters = _add_chapters(tmp_path, 3)

    radio.assign_files_to_book([chapters[0]["id"], chapters[1]["id"]], book["id"])
    files = radio.list_book_files(book["id"])
    assert [f["id"] for f in files] == [chapters[0]["id"], chapters[1]["id"]]
    assert [f["track_order"] for f in files] == [0, 1]

    # Assigning a third file later continues the ordering rather than resetting it.
    radio.assign_files_to_book([chapters[2]["id"]], book["id"])
    files = radio.list_book_files(book["id"])
    assert [f["id"] for f in files] == [c["id"] for c in chapters]
    assert files[2]["track_order"] == 2


def test_unassign_file_returns_it_to_unsorted(tmp_path):
    author = radio.add_author("Brandon Sanderson")
    book = radio.add_book("The Way of Kings", author["id"])
    [record] = _add_chapters(tmp_path, 1)
    radio.assign_files_to_book([record["id"]], book["id"])
    assert radio.unassign_file(record["id"]) is True
    [reloaded] = radio.list_library_items()
    assert reloaded["book_id"] is None


def test_book_progress_summary_empty_not_started_in_progress_and_missing(tmp_path):
    author = radio.add_author("Brandon Sanderson")
    book = radio.add_book("The Way of Kings", author["id"])
    assert radio.book_progress_summary(book["id"])["status"] == "empty"

    chapters = _add_chapters(tmp_path, 2)
    radio.assign_files_to_book([c["id"] for c in chapters], book["id"])
    assert radio.book_progress_summary(book["id"])["status"] == "not_started"

    radio.set_book_last_played(book["id"], chapters[1]["id"])
    radio.update_library_position(chapters[1]["id"], 5000)
    summary = radio.book_progress_summary(book["id"])
    assert summary["status"] == "in_progress"
    assert summary["current_index"] == 2
    assert summary["total"] == 2
    assert summary["position_ms"] == 5000

    radio.remove_library_item(chapters[1]["id"])
    assert radio.book_progress_summary(book["id"])["status"] == "missing"


def test_book_progress_summary_reports_finished_once_every_chapter_is(tmp_path):
    author = radio.add_author("Brandon Sanderson")
    book = radio.add_book("The Way of Kings", author["id"])
    chapters = _add_chapters(tmp_path, 2)
    radio.assign_files_to_book([c["id"] for c in chapters], book["id"])
    radio.set_book_last_played(book["id"], chapters[1]["id"])
    radio.set_library_finished(chapters[0]["id"], True)
    assert radio.book_progress_summary(book["id"])["status"] == "in_progress"

    radio.set_library_finished(chapters[1]["id"], True)
    summary = radio.book_progress_summary(book["id"])
    assert summary["status"] == "finished"
    assert summary["total"] == 2
    assert summary["position_ms"] == 0


def test_set_book_listened_marks_all_chapters_and_updates_resume_target(tmp_path):
    author = radio.add_author("Brandon Sanderson")
    book = radio.add_book("The Way of Kings", author["id"])
    chapters = _add_chapters(tmp_path, 3)
    radio.assign_files_to_book([c["id"] for c in chapters], book["id"])
    radio.update_library_position(chapters[0]["id"], 1000)

    assert radio.set_book_listened(book["id"], True) is True
    files = radio.list_book_files(book["id"])
    assert all(f["finished"] for f in files)
    assert all(f["position_ms"] == 0 for f in files)
    [reloaded_book] = radio.list_books()
    assert reloaded_book["last_played_file_id"] == chapters[-1]["id"]
    assert radio.book_progress_summary(book["id"])["status"] == "finished"

    # Manually correcting a desync clears every chapter back to unlistened
    # and un-sets the resume target, so Resume starts from chapter one again.
    assert radio.set_book_listened(book["id"], False) is True
    files = radio.list_book_files(book["id"])
    assert not any(f["finished"] for f in files)
    [reloaded_book] = radio.list_books()
    assert reloaded_book["last_played_file_id"] is None
    assert radio.book_progress_summary(book["id"])["status"] == "not_started"


def test_set_series_last_played_persists():
    author = radio.add_author("Brandon Sanderson")
    series = radio.add_series("The Stormlight Archive", author["id"])
    book = radio.add_book("The Way of Kings", author["id"], series_id=series["id"], series_index=1)
    assert radio.set_series_last_played(series["id"], book["id"]) is True
    assert radio.list_series()[0]["last_played_book_id"] == book["id"]


# ----------------------------------------------------------------------
# Book/series chat
# ----------------------------------------------------------------------
def test_load_chat_starts_empty_and_save_chat_round_trips():
    assert radio.load_chat("book", "abc123") == []
    conversation = [{"role": "user", "content": "Who is the protagonist?"}]
    radio.save_chat("book", "abc123", conversation)
    assert radio.load_chat("book", "abc123") == conversation
    # A different scope/id doesn't collide.
    assert radio.load_chat("series", "abc123") == []


def test_ask_about_topic_appends_the_reply_and_returns_it(monkeypatch):
    def fake_chat(model, messages):
        assert messages[0]["role"] == "system"
        assert messages[-1] == {"role": "user", "content": "Tell me about the Knights Radiant."}
        return {"message": {"content": "They're an ancient order of knights."}}

    monkeypatch.setattr(radio, "model_chat", fake_chat)
    conversation = [{"role": "user", "content": "Tell me about the Knights Radiant."}]
    reply, updated = radio.ask_about_topic(conversation, "You are a book assistant.")
    assert reply == "They're an ancient order of knights."
    assert updated[-1] == {"role": "assistant", "content": reply}


def test_build_topic_system_prompt_mentions_series_and_synopsis_when_present():
    prompt = radio._build_topic_system_prompt(
        "book", "The Way of Kings", "Brandon Sanderson", "The Stormlight Archive", "A stormlight epic.",
    )
    assert "The Way of Kings" in prompt
    assert "Brandon Sanderson" in prompt
    assert "The Stormlight Archive" in prompt
    assert "A stormlight epic." in prompt


# ----------------------------------------------------------------------
# Soundscapes
# ----------------------------------------------------------------------
def test_generate_soundscape_wav_raises_on_unknown_id():
    with pytest.raises(KeyError):
        radio.generate_soundscape_wav("not_a_real_soundscape")


def test_generate_soundscape_wav_caches_a_playable_mono_wav_file(monkeypatch):
    # Shrink synthesis so the test doesn't spend real time generating audio.
    monkeypatch.setattr(radio, "_SOUNDSCAPE_SAMPLE_RATE", 4000)
    monkeypatch.setattr(radio, "_SOUNDSCAPE_DURATION_S", 1)
    path = radio.generate_soundscape_wav("white_noise")
    assert os.path.isfile(path)
    with wave.open(path, "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getnframes() == 4000
    # Second call hits the cache instead of regenerating.
    assert radio.generate_soundscape_wav("white_noise") == path


def test_add_custom_soundscape_requires_name_and_path():
    with pytest.raises(ValueError):
        radio.add_custom_soundscape("", "/tmp/loop.mp3")
    with pytest.raises(ValueError):
        radio.add_custom_soundscape("My Loop", "")


def test_add_custom_soundscape_rejects_duplicate_path():
    radio.add_custom_soundscape("My Loop", "/tmp/loop.mp3")
    with pytest.raises(ValueError):
        radio.add_custom_soundscape("Another Name", "/tmp/loop.mp3")


def test_remove_custom_soundscape():
    record = radio.add_custom_soundscape("My Loop", "/tmp/loop.mp3")
    assert radio.remove_custom_soundscape(record["id"]) is True
    assert radio.list_custom_soundscapes() == []


# ----------------------------------------------------------------------
# Spectrum analysis helpers
# ----------------------------------------------------------------------
def test_fft_finds_the_dominant_bin_of_a_pure_tone():
    n = 64
    sample_rate = 64
    freq = 8  # bin index 8 for an n=64, sample_rate=64 tone
    samples = [math.sin(2 * math.pi * freq * i / sample_rate) for i in range(n)]
    magnitudes = [abs(v) for v in radio._fft(samples)[: n // 2]]
    assert magnitudes.index(max(magnitudes)) == freq


def test_bucket_log_returns_requested_bar_count_and_handles_empty_input():
    magnitudes = [float(i) for i in range(256)]
    bars = radio._bucket_log(magnitudes, 16)
    assert len(bars) == 16
    assert radio._bucket_log([], 16) == [0.0] * 16


def test_decode_pcm_mono_int16_averages_channels():
    from PyQt6.QtMultimedia import QAudioFormat
    import struct

    # Two interleaved stereo frames: (16384, -16384) and (0, 0).
    raw = struct.pack("<4h", 16384, -16384, 0, 0)
    mono = radio._decode_pcm_mono(raw, QAudioFormat.SampleFormat.Int16, channels=2)
    assert mono == pytest.approx([0.0, 0.0], abs=1e-6)
