"""Resolve local test dependencies without machine-specific paths."""

import json
import os
import shutil
from pathlib import Path

import psutil


def find_obs_bin():
    explicit = os.environ.get("BILINGUE_OBS_BIN")
    if explicit:
        folder = Path(explicit).expanduser().resolve()
        if not (folder / "obs.dll").is_file():
            raise ValueError("BILINGUE_OBS_BIN debe contener obs.dll")
        return folder
    executable = shutil.which("obs64.exe")
    if executable:
        folder = Path(executable).resolve().parent
        if (folder / "obs.dll").is_file():
            return folder
    for process in psutil.process_iter(["name", "exe"]):
        if process.info["name"] == "obs64.exe" and process.info["exe"]:
            folder = Path(process.info["exe"]).resolve().parent
            if (folder / "obs.dll").is_file():
                return folder
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(variable)
        if base:
            folder = Path(base) / "obs-studio" / "bin" / "64bit"
            if (folder / "obs.dll").is_file():
                return folder
    raise ValueError("No se encontro OBS. Configura BILINGUE_OBS_BIN con su carpeta bin/64bit")


def engine_base_url(root):
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    port = config["http_port"]
    if config["host"] != "127.0.0.1" or type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("La prueba requiere un puerto local valido en config.json")
    return f"http://127.0.0.1:{port}"


def test_environment(root):
    env = dict(os.environ)
    profile = root / ".test-runtime" / "obs-host-config"
    profile.mkdir(parents=True, exist_ok=True)
    env["BILINGUE_TEST_CONFIG"] = str(profile)
    env["PATH"] = str(find_obs_bin()) + os.pathsep + env.get("PATH", "")
    return env
