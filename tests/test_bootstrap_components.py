import json
import zipfile

from tools.bootstrap_components import prepare
from tools.installer_checks import digest


def test_bootstrap_embeds_application_but_downloads_only_selected_dependency_groups(tmp_path):
    payload = tmp_path / "payload"
    app = payload / "data/app"
    names = ["engine/example.py", "python/python.exe", "python/python312._pth", "runtime/nemo/bin/asr.dll",
             "runtime/llama/llama-server.exe", "models/example.gguf"]
    for name in names:
        file = app / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(name.encode())
    (payload / "obs-bilingue.dll").write_bytes(b"native plugin")
    (payload / "data/preview.html").write_bytes(b"preview")
    files = {name: digest(app / name) for name in names}
    for name in ["bundle-manifest.json", "bundle-core-manifest.json"]:
        (app / name).write_text(json.dumps({"files": files}))
    prepare(payload, tmp_path / "archives")
    dependencies = json.loads((payload / "dependencies.json").read_text())
    assert len(dependencies["groups"]) == 3
    for group in dependencies["groups"]:
        archive = tmp_path / "archives" / group["archive"]
        assert digest(archive) == group["sha256"]
        with zipfile.ZipFile(archive) as content:
            assert set(content.namelist()) == set(group["files"])
    entries = (payload / "files.iss").read_text()
    assert 'Source: "{#Payload}\\data\\app\\engine\\example.py"' in entries
    assert 'Source: "{tmp}\\dependencies\\python-base-core\\python\\python.exe"' in entries
    assert 'Source: "{#Payload}\\data\\app\\python\\python312._pth"' in entries
    assert 'models\\example.gguf' not in entries
    assert "WizardIsComponentSelected('translation')" in (payload / "downloads.iss").read_text()
