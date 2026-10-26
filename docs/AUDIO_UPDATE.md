# Audio capture update 0.4.2

An input audio-capture callback receives raw audio from an individual OBS input.
Scenes compose audio through a different path; registering that callback on a scene
does not deliver the scene's rendered audio. Desktop capture also misses internal
media/browser audio that OBS sends directly to an output without speaker monitoring.

The new program-mix option uses the public `obs_add_raw_audio_callback` API. It reads
post-mix float audio and feeds the existing bounded transport queue. Muted sources
and source volumes are reflected in that mix. There is no audio reinjection, output
reconfiguration, new ASR instance, resampling stage or persistent audio recording.
Individual input capture remains available. The caption source's visibility lifecycle
disables the transport and removes the capture callback when hidden.

The automatic track selection reads the primary audio encoder of an active streaming
output, then of an active recording output, via dynamically resolved frontend getters.
It falls back to mixer 0 (OBS track 1) when neither output exposes an active encoder.
A fixed track 1–6 overrides that choice. The program mix includes global audio and
the active program composition; it does not isolate a selected scene or capture a
silent/inactive input independently of OBS routing. Preview/program can differ in
Studio Mode. Sources set to monitor-only or excluded from the selected track do not
reach its program mix. The streaming-output getters are read-only; the plugin never
starts or stops outputs.

## Update an existing installation

Close OBS yourself, then run `OBS-Bilingue-0.4.2-Windows-x64-Update.exe`. Select the
existing plugin folder if it uses a nonstandard location. This update requires a
plugin DLL and `data/runtime.json`; it is not a first-install bootstrap. The 0.4.1
bootstrap remains the base installation for new users.

Only `obs-bilingue.dll` and `bin/64bit/obs-bilingue.dll` are updated, covering the two
OBS plugin directory layouts. Correct files with matching SHA256 are not rewritten.
No runtime metadata, model, Python environment, configuration or original uninstaller
is replaced. The updater refuses to install while `obs64` is running. It neither
closes OBS nor starts OBS after installation. This release remains unsigned.

After opening OBS, select **Mezcla del directo de OBS (escenas, microfono y escritorio)**
in the caption source properties. Existing explicit source choices are preserved;
new caption sources default to program mix.

## Build and verify

Compile `native/build.ps1` with the pinned compiler and OBS headers documented in
[BUILD.md](BUILD.md), then run:

```powershell
native/build-update.ps1 -Inno <path-to-ISCC.exe>
python tools/verify_scene_audio.py --legacy <path-to-previous-plugin.dll>
```

The integration test starts separate small libobs hosts, using synthetic stereo
audio through real `ffmpeg_source` inputs: one inside a scene and another as a
global source. It loads no ASR model, browser runtime, microphone or desktop capture,
and uses isolated test directories and a temporary loopback receiver. It verifies
the previous failure, program mix peak against an independent reference callback,
mute/volume behavior, individual input capture, a fixed empty track, and visibility
stop/resume. Only synthetic test audio and aggregate diagnostics are saved under
the excluded build directory. This verifies routing, not recognition accuracy or
multi-hour streaming performance. Active-output automatic track selection still
needs a separate end-to-end streaming/recording check; the isolated hosts verify
the offline fallback and fixed-track override.

API references: [OBS raw audio callbacks](https://docs.obsproject.com/reference-core),
[source composition and audio](https://docs.obsproject.com/reference-sources),
[OBS backend design](https://docs.obsproject.com/backend-design).
