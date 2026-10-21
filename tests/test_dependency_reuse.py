import configparser
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows dependency discovery")
def test_read_only_reuse_rejects_incompatible_files_and_preserves_correct_targets(tmp_path):
    source = tmp_path / "existing python"
    stage = tmp_path / "stage"
    root = tmp_path / "plugin"
    existing = root / "data/app/python/keep.dll"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"correct")
    source.mkdir()
    (source / "match.dll").write_bytes(b"correct")
    (source / "wrong.dll").write_bytes(b"different ABI")
    before = {file: (file.read_bytes(), file.stat().st_mtime_ns) for file in [existing, *source.iterdir()]}
    expected = hashlib.sha256(b"correct").hexdigest()
    inventory = {"groups": [
        {"id": "reuse", "component": "core", "files": {
            "python/match.dll": {"sha256": expected}, "python/keep.dll": {"sha256": expected}}},
        {"id": "missing", "component": "core", "files": {"python/wrong.dll": {"sha256": expected}}},
        {"id": "optional", "component": "translation",
         "files": {"runtime/llama/no.dll": {"sha256": expected}}},
    ]}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(inventory))
    script = Path(__file__).resolve().parents[1] / "installer/reuse_dependencies.ps1"
    report = tmp_path / "reuse.ini"
    def quote(path):
        return "'" + str(path).replace("'", "''") + "'"
    command = (f". {quote(script)} -Manifest {quote(manifest)} -PluginRoot {quote(root)} "
               f"-StagingRoot {quote(stage)} -Report {quote(report)}; "
               f"function Get-PythonRoots {{ {quote(source)} }}; "
               "function Get-NativeRoots { }; Invoke-Reuse")
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                   check=True, capture_output=True, text=True)
    result = configparser.ConfigParser()
    result.read(report)
    assert dict(result["groups"]) == {"reuse": "0", "missing": "1"}
    assert dict(result["summary"]) == {"kept": "1", "reused": "1"}
    assert (stage / "reuse/python/match.dll").read_bytes() == b"correct"
    assert not (stage / "missing/python/wrong.dll").exists()
    assert not (stage / "reuse/python/keep.dll").exists()
    assert {file: (file.read_bytes(), file.stat().st_mtime_ns) for file in before} == before
