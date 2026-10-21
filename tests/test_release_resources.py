import json
from pathlib import Path


def test_installer_downloads_the_same_pinned_models_as_the_payload_builder():
    root = Path(__file__).resolve().parents[1]
    resources = json.loads((root / "installer/resources.json").read_text())
    script = (root / "installer/obs-bilingue.iss").read_text(encoding="utf-8")
    for name, spec in resources.items():
        if name.endswith(".gguf"):
            assert spec["url"] in script
            assert spec["sha256"] in script
    assert '#include Payload + "/files.iss"' in script
