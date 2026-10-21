"""Fail publication checks on home paths, credentials or local-only files."""
import argparse
import re
import subprocess
from pathlib import Path

EXCLUDED = {".git", ".build", "dist", "build", ".venv", "__pycache__", ".pytest_cache",
            ".ruff_cache", ".installer-test", ".test-runtime", "models", "runtime"}
HOME_PATH = re.compile(rb"(?:[a-z]:[\\/]+Users[\\/]+[^\\/\s\"']+|/(?:home|Users)/[^/\s\"']+/)", re.I)
SECRET = re.compile(
    rb"(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,}|hf_[A-Za-z0-9]{30,}|"
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")


def scan(root, extra_forbidden=()):
    failures = []
    if (root / ".git").is_dir():
        tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
        failures.extend((name, "tracked local-only artifact") for name in filter(None, tracked)
                        if set(Path(name).parts) & EXCLUDED)
    forbidden = [item.encode().lower() for item in extra_forbidden if item]
    for path in root.rglob("*"):
        if not path.is_file() or set(path.relative_to(root).parts) & EXCLUDED:
            continue
        relative = path.relative_to(root).as_posix()
        if path.name.startswith(".env") or path.name in {"runtime.json", "pyvenv.cfg"}:
            failures.append((relative, "local-only file"))
        # Official large weights are verified by pinned SHA256, not text-scanned.
        if path.suffix in {".gguf", ".nemo", ".safetensors"}:
            continue
        with path.open("rb") as stream:
            previous = b""
            while data := stream.read(1024 * 1024):
                chunk = previous + data
                if (HOME_PATH.search(chunk) or SECRET.search(chunk)
                        or any(x in chunk.lower() for x in forbidden)):
                    failures.append((relative, "private path or credential pattern"))
                    break
                previous = chunk[-4096:]
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, nargs="?", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--forbid", action="append", default=[])
    args = parser.parse_args()
    failed = scan(args.path, args.forbid)
    for path, reason in failed:
        print(f"{path}: {reason}")
    if failed:
        raise SystemExit(1)
    print("Publication scan passed")
