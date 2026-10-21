"""Split verified payload dependencies into independently downloadable components."""
import importlib.metadata
import json
import re
import zipfile
from pathlib import Path

try:
    from .installer_checks import digest, write_checks
except ImportError:  # Direct invocation from tools/.
    from installer_checks import digest, write_checks

VERSION = "0.4.1"


def prepare(payload, destination):
    app = payload / "data/app"
    manifest = json.loads((app / "bundle-manifest.json").read_text())
    # Installer bookkeeping differs between pip/uv even for an identical wheel.
    # It is not needed to import a package and must not force a download.
    bookkeeping = {"RECORD", "INSTALLER", "REQUESTED", "uv_cache.json", "direct_url.json"}
    files = {name: value for name, value in manifest["files"].items()
             if not (".dist-info/" in name and Path(name).name in bookkeeping)}
    packages = app / "python/Lib/site-packages"
    ownership = {}
    for distribution in importlib.metadata.distributions(path=[str(packages)]):
        name = re.sub(r"[^a-z0-9.-]", "-", distribution.metadata["Name"].lower())
        group = "py-" + name + "-" + distribution.version
        for entry in distribution.files or []:
            path = (packages / entry).resolve()
            if path.is_relative_to(packages.resolve()):
                ownership[path.relative_to(app.resolve()).as_posix()] = group
    groups = {}
    for relative, expected in files.items():
        if relative == "python/python312._pth":
            continue  # App-specific isolation config is tiny and embedded in Setup.
        if relative.startswith("python/"):
            group = ownership.get(relative, "python-base")
        elif relative.startswith("runtime/"):
            # Large CUDA libraries are separate downloads, never a monolithic runtime.
            group = ("native-" + expected[:20] if (app / relative).stat().st_size > 1024 * 1024
                     else "native-" + relative.split("/")[1] + "-base")
        else:
            continue
        component = "translation" if relative.startswith("runtime/llama/") else "core"
        # Identical native libraries shared by both engines have one download.
        key = (group, component)
        spec = groups.setdefault(key, {"id": group + "-" + component, "component": component, "files": {}})
        spec["files"][relative] = {"sha256": expected, "size": (app / relative).stat().st_size}
    destination.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for spec in groups.values():
        # Versioned assets are verified with the checksum embedded in the bootstrap.
        archive = destination / (spec["id"] + ".zip")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
            for relative in sorted(spec["files"]):
                output.write(app / relative, relative)
        spec["archive"] = archive.name
        spec["sha256"] = digest(archive)
        spec["size"] = archive.stat().st_size
        artifacts[spec["id"]] = spec
    metadata = {"version": VERSION, "groups": list(artifacts.values())}
    for name in ("bundle-manifest.json", "bundle-core-manifest.json"):
        path = app / name
        current = json.loads(path.read_text())
        current["files"] = {relative: expected for relative, expected in current["files"].items()
                            if relative in files}
        path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    (payload / "dependencies.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    write_checks(payload, metadata)
    print(json.dumps({"components": len(artifacts),
                      "download_bytes": sum(x["size"] for x in artifacts.values())}))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    prepare(args.payload, args.destination)
