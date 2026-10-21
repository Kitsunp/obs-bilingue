"""Archive reviewed tracked source only; never walk a development workspace."""

import argparse
import subprocess
import tomllib
import zipfile
from pathlib import Path

from audit_public import scan

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIRS = {".git", ".venv", ".build", "dist", "build", "models", "runtime",
                "verification", ".installer-test", ".test-runtime", "__pycache__"}


def validate_source_path(relative):
    if relative.is_absolute() or ".." in relative.parts or set(relative.parts) & PRIVATE_DIRS:
        raise ValueError("Local-only path must not be tracked for publication")
    if relative.name.startswith(".env") or relative.name in {"runtime.json", "pyvenv.cfg"}:
        raise ValueError("Private configuration must not be published")
    if relative.suffix.lower() in {".key", ".pem", ".pdb", ".log", ".wav", ".mp4", ".mp3", ".m4a"}:
        raise ValueError("Private or generated artifact must not be published")


def main():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / f"obs-bilingue-{version}-source.zip")
    args = parser.parse_args()
    actual_root = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], cwd=ROOT, text=True).strip()
    if Path(actual_root).resolve() != ROOT:
        raise ValueError("Source must have its own reviewed Git repository")
    if scan(ROOT):
        raise ValueError("Publication audit failed; inspect tools/audit_public.py output")
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in filter(None, files):
            relative = Path(name)
            validate_source_path(relative)
            file = ROOT / relative
            if file.is_symlink() or not file.is_file() or file.stat().st_size > 20 * 2**20:
                raise ValueError("Unexpected source file or large binary")
            archive.write(file, f"obs-bilingue-{version}/" + relative.as_posix())
    with zipfile.ZipFile(args.output) as archive:
        if archive.testzip() is not None:
            raise ValueError("Source archive failed integrity check")
    print(args.output.name)


if __name__ == "__main__":
    main()
