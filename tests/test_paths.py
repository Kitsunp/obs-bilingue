import json

import pytest

from tools.obs_test_paths import engine_base_url, find_obs_bin


def test_explicit_obs_bin_supports_nonstandard_location(tmp_path, monkeypatch):
    folder = tmp_path / "portable OBS" / "bin" / "64bit"
    folder.mkdir(parents=True)
    (folder / "obs.dll").touch()
    monkeypatch.setenv("BILINGUE_OBS_BIN", str(folder))
    assert find_obs_bin() == folder.resolve()


def test_invalid_explicit_obs_bin_does_not_silently_use_another_install(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINGUE_OBS_BIN", str(tmp_path))
    with pytest.raises(ValueError, match="BILINGUE_OBS_BIN"):
        find_obs_bin()


def test_tool_endpoint_comes_from_local_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"host": "127.0.0.1", "http_port": 28163}))
    assert engine_base_url(tmp_path) == "http://127.0.0.1:28163"
    path.write_text(json.dumps({"host": "0.0.0.0", "http_port": 28163}))
    with pytest.raises(ValueError):
        engine_base_url(tmp_path)
