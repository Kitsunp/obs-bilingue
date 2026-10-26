import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "installer/native-update-preflight.ps1"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native update policy")


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def powershell(command):
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, text=True, check=True)


@pytest.mark.parametrize("layout", ["obs-bilingue.dll", "bin/64bit/obs-bilingue.dll"])
def test_update_accepts_existing_obs_layout_without_changing_runtime(tmp_path, layout):
    dll = tmp_path / layout
    dll.parent.mkdir(parents=True, exist_ok=True)
    dll.write_bytes(b"previous plugin")
    metadata = tmp_path / "data/runtime.json"
    metadata.parent.mkdir()
    metadata.write_bytes(b"existing runtime metadata")
    original = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (dll, metadata)}
    result = powershell(f". {quote(SCRIPT)}; Test-NativeUpdateRoot {quote(tmp_path)}")
    assert result.stdout.strip() == "True"
    assert original == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in original}


@pytest.mark.parametrize("existing", [None, "obs-bilingue.dll", "data/runtime.json"])
def test_update_rejects_missing_or_incomplete_install(tmp_path, existing):
    if existing:
        file = tmp_path / existing
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
    result = powershell(f". {quote(SCRIPT)}; Test-NativeUpdateRoot {quote(tmp_path)}")
    assert result.stdout.strip() == "False"


def test_running_obs_blocks_before_any_installation_probe():
    result = powershell(f"""
        . {quote(SCRIPT)}
        function Get-Process {{ param($Name, $ErrorAction) return [pscustomobject]@{{Name='obs64'}} }}
        function Test-NativeUpdateRoot {{ throw 'Installation must not be probed with OBS running' }}
        Invoke-NativeUpdatePreflight 'unused'
    """)
    assert result.stdout.strip() == "20"


def test_closed_obs_allows_only_an_existing_install(tmp_path):
    result = powershell(f"""
        . {quote(SCRIPT)}
        function Get-Process {{ param($Name, $ErrorAction) return $null }}
        Invoke-NativeUpdatePreflight {quote(tmp_path)}
        function Test-NativeUpdateRoot {{ return $true }}
        Invoke-NativeUpdatePreflight {quote(tmp_path)}
    """)
    assert result.stdout.split() == ["30", "0"]
