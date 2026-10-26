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

For the native-only 0.4.2 audio update, see [AUDIO_UPDATE.md](AUDIO_UPDATE.md).
The full dependency/bootstrap installer below remains the 0.4.1 base; apply the
native update afterward. Its component assets are not republished for this patch.

On Windows x64 with Git and uv available:

```powershell
tools/bootstrap_build.ps1
```

The script fetches pinned Zig 0.15.2, an exact OBS header commit and signed Inno
Setup 6.7.3. Downloads are checked before execution. It prepares Python 3.12.14,
the fully pinned Python packages and the resources in `installer/resources.json`,
then compiles the small bootstrap into `dist/`. `tools/bootstrap_components.py`
splits Python into interpreter/package archives and native libraries into separate
components in `dist/components/`. Upload **all** these assets beside the EXE to the
same versioned GitHub release (flat asset names). Missing component archives and
original model weights are downloaded during installation, with pinned SHA256.
Runtime use is local. The bootstrap build rejects an EXE of 20 MiB or larger.

`tools/bootstrap_build.ps1 -WithoutInstaller` only builds the native plugin and
test host. `native/build.ps1` also accepts explicit Zig and OBS header locations.
Build paths are remapped in native compilation. Development tools are never installed
by the end-user installer. Use a fresh `.build/payload` directory for a new payload.

Each payload has a SHA256 manifest; installation verifies it before generating the
machine-specific runtime metadata. The compact component has its own manifest and
does not require translation files. The bytecode cache is not distributed or written
by the managed launch path. Fully pinned downloads and package hashes make inputs
auditable; this is not a claim of bit-identical EXE builds across hosts.

`tools/installer_checks.py` generates explicit per-destination hash checks for the
Inno file entries. These avoid copying correct files on repair or reinstallation.
Installation tests must inspect the manifest, file timestamps and log as well as
the exit code: a post-install verification failure returns custom exit code 90.
Preflight inspects the driver and running processes without installing system
dependencies. Compatibility >= CUDA 13 means the driver API, not the Toolkit version.

`installer/reuse_dependencies.ps1` reads PEP 514 registrations and explicit local
PATH/CUDA_PATH locations; it never executes discovered Python interpreters. Exact
matching binaries/packages are copied into private staging. The Inno download page
fetches only incomplete groups, extracts into temporary staging and uses explicit
external file entries so uninstallation remains scoped to this product. A single
missing package file may require downloading its package archive; correct installed
files are still not rewritten. A repair test should count HTTP requests and compare
file timestamps, not infer reuse from a zero exit code.

## Publisher signing

Unsigned builds are explicitly documented as such. With an established trusted
signing identity, pass `-SigningCommand` to `bootstrap_build.ps1`. This configures
Inno's `captionpublisher` signing tool for the installer **and uninstaller**. Its
command must include Inno's `$f` file placeholder and use SHA256 plus an RFC3161
timestamp. Keep credentials outside the repository/command; use a certificate
store or a signing service. Requested signing must pass `tools/verify_signature.ps1`:
embedded Authenticode `Valid`, the exact expected publisher, code-signing EKU,
timestamp and reviewed signer metadata. The default expected publisher
is SignPath Foundation, subject to acceptance; it is not a claim of an existing
certificate. A different approved organizational identity can be specified with
`-SigningPublisher`. Generate checksums **after** signing. No self-signed root is
installed and no Windows security settings are changed. This hook does not supply
a certificate and has not been validated with a publisher identity for this release.
See the [code signing policy and pending free-provider application](SIGNING.md).
Use `-RequireSigning` for a signing build: without an approved `-SigningCommand`
the build stops before downloading tools or producing an unsigned installer. Normal
unsigned development builds remain supported and must be labelled as unsigned.
See [Inno signing](https://jrsoftware.org/ishelp/topic_setup_signtool.htm) and
[Microsoft SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).

GitHub Actions tests source changes and can build the installer via manual dispatch.
The CPU CI runner does not establish GPU compatibility or recognition quality.
GPU/source tests must use the installed payload and actual libobs capture. The
existing streaming benchmark accepts a local media path; no test media is published.
