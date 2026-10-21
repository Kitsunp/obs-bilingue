import configparser
import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.installer_checks import digest, write_checks


def test_expected_destination_hashes_cover_both_manifests_and_obs_layouts(tmp_path):
    app = tmp_path / "data/app"
    app.mkdir(parents=True)
    (tmp_path / "obs-bilingue.dll").write_bytes(b"test-dll")
    (tmp_path / "data/preview.html").write_bytes(b"preview")
    core = {"engine/example.py": "a" * 64}
    full = {**core, "runtime/llama/example.dll": "b" * 64,
            "models/Hy-MT2-1.8B-Q4_K_M.gguf": "c" * 64}
    for name, files in (("bundle-core-manifest.json", core), ("bundle-manifest.json", full)):
        (app / name).write_text(json.dumps({"files": files}))
    write_checks(tmp_path)
    checks = configparser.ConfigParser(interpolation=None)
    checks.read(tmp_path / "checks.ini", encoding="utf-8")
    for mode, manifest in (("core", "bundle-core-manifest.json"), ("full", "bundle-manifest.json")):
        section = checks[f"files-{mode}"]
        assert section["obs-bilingue.dll"] == section["bin\\64bit\\obs-bilingue.dll"]
        assert section["data\\app\\bundle-manifest.json"] == digest(app / manifest)
    assert "data\\app\\runtime\\llama\\example.dll" not in checks["files-core"]
    generated = (tmp_path / "files.iss").read_text(encoding="utf-8")
    assert "data\\app\\models\\" not in generated
    assert "NeedTargetFile('data\\app\\engine\\example.py', '" + "a" * 64 + "')" in generated


@pytest.mark.skipif(os.name != "nt", reason="Windows installer policy")
def test_cuda_driver_api_policy_allows_newer_drivers_and_rejects_older():
    script = Path(__file__).resolve().parents[1] / "installer/preflight.ps1"
    command = f". '{script}'; Test-CudaVersion 12090; Test-CudaVersion 13000; Test-CudaVersion 14000"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, check=True)
    assert result.stdout.split() == ["False", "True", "True"]
