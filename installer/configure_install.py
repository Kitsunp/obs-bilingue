"""Verify an offline payload and generate this machine's local installation paths."""
import argparse
import hashlib
import json
from pathlib import Path


def configure(plugin_root):
    plugin_root = plugin_root.resolve()
    app = plugin_root / "data" / "app"
    manifest = json.loads((app / "bundle-manifest.json").read_text(encoding="utf-8"))
    for relative, digest in manifest["files"].items():
        file = (app / relative).resolve()
        if not file.is_relative_to(app) or not file.is_file():
            raise ValueError("Invalid or missing payload file")
        with file.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError(f"Payload checksum mismatch: {relative}")
    config_path = app / "config.json"
    defaults = json.loads((app / "config.default.json").read_text(encoding="utf-8"))
    if config_path.exists():
        defaults.update(json.loads(config_path.read_text(encoding="utf-8")))
    config_path.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
    # Validate the resulting configuration before making it discoverable by OBS.
    from engine.server import read_config
    read_config(app)
    metadata = {"root": str(app), "python": str(app / "python" / "pythonw.exe")}
    if not Path(metadata["python"]).is_file():
        raise FileNotFoundError("Bundled Python is missing")
    destination = plugin_root / "data" / "runtime.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    temporary.replace(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-root", type=Path, required=True)
    configure(parser.parse_args().plugin_root)
