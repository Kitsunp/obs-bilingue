"""Generate destination checksums for safe reuse of installed plugin files."""
import configparser
import hashlib
import json
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_checks(payload):
    app = payload / "data/app"
    checks = configparser.ConfigParser(interpolation=None)
    checks.optionxform = str
    for mode, manifest in (("core", "bundle-core-manifest.json"), ("full", "bundle-manifest.json")):
        files = json.loads((app / manifest).read_text())["files"]
        entries = {str(Path("data/app") / name).replace("/", "\\"): value for name, value in files.items()}
        entries["data\\app\\bundle-manifest.json"] = digest(app / manifest)
        entries.update({"obs-bilingue.dll": digest(payload / "obs-bilingue.dll"),
                        "bin\\64bit\\obs-bilingue.dll": digest(payload / "obs-bilingue.dll"),
                        "data\\preview.html": digest(payload / "data/preview.html")})
        checks[f"files-{mode}"] = entries
    with (payload / "checks.ini").open("w", encoding="utf-8") as stream:
        checks.write(stream)
    lines = []

    def entry(source, destination, relative, expected, component, condition=""):
        if ".." in Path(relative).parts or Path(relative).is_absolute():
            raise ValueError("Unsafe generated installer destination")
        relative = relative.replace("/", "\\")
        quote = relative.replace("'", "''")
        predicate = f"NeedTargetFile('{quote}', '{expected}')"
        if condition:
            predicate = condition + " and " + predicate
        lines.append(f'Source: "{{#Payload}}\\{source}"; DestDir: "{{app}}\\{destination}"; '
                     f'Flags: ignoreversion; Components: {component}; Check: {predicate}')

    for relative, source in (("obs-bilingue.dll", "obs-bilingue.dll"),
                             ("bin/64bit/obs-bilingue.dll", "obs-bilingue.dll"),
                             ("data/preview.html", "data/preview.html")):
        destination = str(Path(relative).parent).replace("/", "\\")
        entry(source.replace("/", "\\"), destination, relative, digest(payload / source), "core")
    for name, expected in json.loads((app / "bundle-manifest.json").read_text())["files"].items():
        if name.startswith("models/"):
            continue
        relative = "data/app/" + name
        destination = str(Path(relative).parent).replace("/", "\\")
        component = "translation" if name.startswith("runtime/llama/") else "core"
        entry(relative.replace("/", "\\"), destination, relative, expected, component)
    for mode, manifest in (("core", "bundle-core-manifest.json"), ("full", "bundle-manifest.json")):
        relative = "data\\app\\bundle-manifest.json"
        expected = digest(app / manifest)
        component = "core" if mode == "core" else "translation"
        condition = "not WizardIsComponentSelected('translation')" if mode == "core" else ""
        predicate = f"NeedTargetFile('{relative}', '{expected}')"
        if condition:
            predicate = condition + " and " + predicate
        lines.append(f'Source: "{{#Payload}}\\data\\app\\{manifest}"; DestDir: "{{app}}\\data\\app"; '
                     f'DestName: "bundle-manifest.json"; Flags: ignoreversion; Components: {component}; '
                     f'Check: {predicate}')
    (payload / "files.iss").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=Path)
    write_checks(parser.parse_args().payload)
