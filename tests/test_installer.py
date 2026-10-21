import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from installer.configure_install import configure
from tools.audit_public import scan


def payload(tmp_path):
    root = tmp_path / "Plugin con espacios 日本語"
    app = root / "data/app"
    (app / "python").mkdir(parents=True)
    (app / "python/pythonw.exe").write_bytes(b"placeholder")
    defaults = Path(__file__).resolve().parents[1] / "config.json"
    (app / "config.default.json").write_bytes(defaults.read_bytes())
    files = {str(p.relative_to(app)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in app.rglob("*") if p.is_file()}
    (app / "bundle-manifest.json").write_text(json.dumps({"files": files}))
    return root, app


def test_installer_generates_paths_for_this_machine_and_preserves_settings(tmp_path):
    root, app = payload(tmp_path)
    configure(root)
    metadata = json.loads((root / "data/runtime.json").read_text(encoding="utf-8"))
    assert Path(metadata["root"]) == app.resolve()
    assert Path(metadata["python"]) == app.resolve() / "python/pythonw.exe"
    config = json.loads((app / "config.json").read_text())
    config["subtitle_ttl_seconds"] = 4
    (app / "config.json").write_text(json.dumps(config))
    configure(root)
    assert json.loads((app / "config.json").read_text())["subtitle_ttl_seconds"] == 4


def test_installer_refuses_tampered_payload_before_registering_paths(tmp_path):
    root, app = payload(tmp_path)
    (app / "python/pythonw.exe").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        configure(root)
    assert not (root / "data/runtime.json").exists()


def test_installer_rejects_manifest_path_escape(tmp_path):
    root, app = payload(tmp_path)
    (app / "bundle-manifest.json").write_text(json.dumps({"files": {"../../../outside": "0"}}))
    with pytest.raises(ValueError, match="Invalid"):
        configure(root)


def test_reconfigure_does_not_rewrite_valid_existing_config_or_runtime(tmp_path):
    root, app = payload(tmp_path)
    configure(root)
    files = [app / "config.json", root / "data/runtime.json"]
    before = [(file.read_bytes(), file.stat().st_mtime_ns) for file in files]
    configure(root)
    assert [(file.read_bytes(), file.stat().st_mtime_ns) for file in files] == before


def test_bad_existing_config_is_not_replaced_with_defaults(tmp_path):
    root, app = payload(tmp_path)
    file = app / "config.json"
    file.write_bytes(b"{invalid-config")
    with pytest.raises(ValueError):
        configure(root)
    assert file.read_bytes() == b"{invalid-config"
    assert not (root / "data/runtime.json").exists()


def test_publication_audit_detects_private_files_without_printing_contents(tmp_path):
    (tmp_path / "runtime.json").write_text('{"root":"local-only"}')
    assert scan(tmp_path) == [("runtime.json", "local-only file")]


def test_publication_audit_does_not_hide_tracked_test_profiles(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    folder = tmp_path / ".test-runtime"
    folder.mkdir()
    (folder / "profile.txt").write_text("test-only")
    subprocess.run(["git", "add", ".test-runtime"], cwd=tmp_path, check=True, capture_output=True)
    assert scan(tmp_path) == [(".test-runtime/profile.txt", "tracked local-only artifact")]
