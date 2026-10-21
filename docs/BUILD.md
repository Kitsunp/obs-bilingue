# Build and verification

The source repository intentionally omits private recordings, local metrics,
experimental model adaptations, development history, build output and credentials.
Releases contain the original pinned model artifacts, never experimental checkpoints.

## Tests

Use Python 3.12 and uv:

```powershell
uv venv --python 3.12.14
uv pip install --python .venv/Scripts/python.exe --require-hashes -r requirements-bundle.lock
uv pip install --python .venv/Scripts/python.exe pytest==9.1.1 ruff==0.17.0
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check engine tests tools installer
.venv/Scripts/python.exe tools/audit_public.py
```

## Native DLL and installer

On Windows x64 with Git and uv available:

```powershell
tools/bootstrap_build.ps1
```

The script fetches pinned Zig 0.15.2, an exact OBS header commit and signed Inno
Setup 6.7.3. Downloads are checked before execution. It prepares Python 3.12.14,
the fully pinned Python packages and the resources in `installer/resources.json`,
then compiles the installer into `dist/`. Python and runtimes are embedded; original
model weights are downloaded automatically during installation, with their pinned
SHA256. This keeps the EXE below GitHub's per-asset size limit. Runtime use is local.

`tools/bootstrap_build.ps1 -WithoutInstaller` only builds the native plugin and
test host. `native/build.ps1` also accepts explicit Zig and OBS header locations.
Build paths are remapped in native compilation. Development tools are never installed
by the end-user installer. Use a fresh `.build/payload` directory for a new payload.

Each payload has a SHA256 manifest; installation verifies it before generating the
machine-specific runtime metadata. The compact component has its own manifest and
does not require translation files. The bytecode cache is not distributed or written
by the managed launch path. Fully pinned downloads and package hashes make inputs
auditable; this is not a claim of bit-identical EXE builds across hosts.

GitHub Actions tests source changes and can build the installer via manual dispatch.
The CPU CI runner does not establish GPU compatibility or recognition quality.
GPU/source tests must use the installed payload and actual libobs capture. The
existing streaming benchmark accepts a local media path; no test media is published.
