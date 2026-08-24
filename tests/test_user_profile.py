"""Regression tests for /profile (load_user_profile/save_user_profile, webagent.py:1667-1712)."""
import webagent


def test_load_user_profile_defaults_when_no_file_present(isolated_data_dir):
    profile = webagent.load_user_profile()
    assert profile["name"] == "User"
    assert profile["persona"] == "neutral"
    assert profile["preferences"] == []


def test_save_and_load_user_profile_round_trip(isolated_data_dir):
    profile = webagent.load_user_profile()
    profile["name"] = "Skylar"
    profile["interests"] = ["astronomy", "stoicism"]
    profile["notes"] = "Prefers concise answers."

    webagent.save_user_profile(profile)
    reloaded = webagent.load_user_profile()

    assert reloaded["name"] == "Skylar"
    assert reloaded["interests"] == ["astronomy", "stoicism"]
    assert reloaded["notes"] == "Prefers concise answers."
