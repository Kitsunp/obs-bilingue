"""Prepare checksummed Windows resources for Inno Setup and automatic model setup."""
import argparse
import hashlib
import json
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from bootstrap_components import VERSION, prepare

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(path, spec):
    if path.is_file() and sha256(path) == spec["sha256"]:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    with urllib.request.urlopen(spec["url"], timeout=120) as response, temporary.open("wb") as stream:
        shutil.copyfileobj(response, stream, length=1024 * 1024)
    if sha256(temporary) != spec["sha256"]:
        temporary.unlink()
        raise ValueError(f"Download checksum failed: {path.name}")
    temporary.replace(path)
    return path


def extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zip_file:
        for entry in zip_file.infolist():
            if not (destination / entry.filename).resolve().is_relative_to(destination.resolve()):
                raise ValueError("Unsafe archive path")
        zip_file.extractall(destination)


def copy_tree(source, target):
    shutil.copytree(source, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pdb", ".git", ".cache"))


def main(args):
    if not (ROOT / "build/obs-bilingue.dll").is_file():
        raise FileNotFoundError("Build the native plugin first")
    payload = ROOT / ".build/payload"
    if payload.exists():
        raise FileExistsError("Payload already exists; use a clean build directory")
    cache = ROOT / ".build/downloads"
    resources = json.loads((ROOT / "installer/resources.json").read_text())
    cache.mkdir(parents=True, exist_ok=True)
    if args.cache:
        for name, spec in resources.items():
            source = args.cache / name
            if source.is_file() and sha256(source) == spec["sha256"]:
                shutil.copyfile(source, cache / name)
    for name, spec in resources.items():
        print(f"Verifying {name}", flush=True)
        download(cache / name, spec)
    app = payload / "data/app"
    app.mkdir(parents=True)
    for folder in ("engine", "web", "assets", "licenses"):
        copy_tree(ROOT / folder, app / folder)
    shutil.copyfile(ROOT / "config.json", app / "config.default.json")
    shutil.copyfile(ROOT / "installer/configure_install.py", app / "configure_install.py")
    shutil.copyfile(ROOT / "LICENSE", app / "LICENSE")
    shutil.copyfile(ROOT / "THIRD_PARTY_NOTICES.md", app / "THIRD_PARTY_NOTICES.md")
    shutil.copyfile(ROOT / "build/obs-bilingue.dll", payload / "obs-bilingue.dll")
    shutil.copyfile(ROOT / "web/preview.html", payload / "data/preview.html")
    python = app / "python"
    python.mkdir()
    for file in args.python_root.iterdir():
        if file.is_file() and (file.suffix.lower() in {".dll", ".exe"} or "license" in file.name.lower()):
            shutil.copyfile(file, python / file.name)
    shutil.copytree(args.python_root / "Lib", python / "Lib", ignore=shutil.ignore_patterns(
        "site-packages", "__pycache__", "*.pyc", "test", "tests", "idlelib", "tkinter",
        "turtledemo", "ensurepip", "venv"))
    copy_tree(args.python_root / "DLLs", python / "DLLs")
    (python / "python312._pth").write_text(".\nLib\nDLLs\nLib/site-packages\n..\nimport site\n")
    subprocess.run(["uv", "pip", "install", "--python", str(args.python_root / "python.exe"),
                    "--target", str(python / "Lib/site-packages"), "--require-hashes",
                    "-r", str(ROOT / "requirements-bundle.lock")], check=True)
    # No launcher scripts or build-host bytecode are needed at run time.
    scripts = python / "Lib/site-packages/bin"
    if scripts.exists():
        if not scripts.resolve().is_relative_to(payload.resolve()):
            raise ValueError("Unsafe generated-script cleanup path")
        shutil.rmtree(scripts)
    native = ROOT / ".build/nemo-extracted"
    extract(cache / "nemo-runtime.zip", native)
    copy_tree(next(native.iterdir()), app / "runtime/nemo")
    llama = app / "runtime/llama"
    extract(cache / "llama.zip", llama)
    extract(cache / "cudart.zip", llama)
    for file in llama.glob("*.exe"):
        if file.name != "llama-server.exe":
            file.unlink()
    asr_model = app / "models/nemo-native"
    asr_model.mkdir(parents=True)
    shutil.copyfile(cache / "nemotron-3.5-asr-streaming-0.6b.q8_0.gguf",
                    asr_model / "nemotron-3.5-asr-streaming-0.6b.q8_0.gguf")
    shutil.copyfile(cache / "Hy-MT2-1.8B-Q4_K_M.gguf", app / "models/Hy-MT2-1.8B-Q4_K_M.gguf")
    files = {file.relative_to(app).as_posix(): sha256(file)
             for file in sorted(app.rglob("*")) if file.is_file()}
    core = {path: digest for path, digest in files.items()
            if not path.startswith("runtime/llama/") and path != "models/Hy-MT2-1.8B-Q4_K_M.gguf"}
    for name, included in (("bundle-manifest.json", files), ("bundle-core-manifest.json", core)):
        (app / name).write_text(json.dumps({"version": VERSION, "files": included}, indent=2))
    prepare(payload, ROOT / "dist/components")
    print(json.dumps({"files": len(files), "bytes": sum(p.stat().st_size for p in app.rglob("*")
                                                         if p.is_file()), "payload": str(payload)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-root", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    main(parser.parse_args())
