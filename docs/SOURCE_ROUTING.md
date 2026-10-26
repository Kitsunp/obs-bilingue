# Source audio and microphone shortcuts 0.4.4

Choose the existing OBS source by its normal name in the caption source properties.
Media and audio inputs provide their own PCM. Selecting a scene still captures its
visible audio sources using the isolated scene mixer introduced in 0.4.3.
The selector no longer adds a prefix or suffix to scene names. Legacy saved full
program-mix selections remain supported but are not offered for new selections.

## Window and game capture

A Windows window/game capture can show video with its native `capture_audio`
disabled. In that case the plugin reads its `get_hooked` result and creates a
private `wasapi_process_output_capture` for the hooked application. The private
capture has no output-root connection, every output mixer disabled and monitoring
disabled. It feeds only the caption transport. It does not change the original
source settings, system devices, scene composition or the audience's mix.

OBS process loopback includes the target process tree. Several windows or tabs in
the same application/process can therefore share audio; this is not guaranteed
per-tab isolation. An unavailable hook, unsupported process capture or a hidden
target produces no substitute desktop capture. Changing the hooked window rebuilds
the private input and resets the caption transport epoch. If native source audio is
already enabled, the plugin uses that source directly, without a second capture.

A Browser source must have **Controlar el audio a traves de OBS** enabled in its
native properties to provide its own PCM. The caption properties explain this when
it is disabled. The plugin does not reload the browser or change monitoring during
a stream. Display capture by itself does not identify one application's audio;
choose an application/window audio input for isolation.

## Keyboard and external controls

Choose **Microfono para los atajos** in the caption properties. One unambiguous
existing global Windows microphone input can be selected automatically. Then assign
your preferred key in **OBS > Ajustes > Atajos**:

- **Bilingue: alternar microfono / fuente elegida**;
- **Bilingue: subtitular microfono**;
- **Bilingue: subtitular fuente elegida**.

No key is assigned by default. Devices that emit keyboard shortcuts can use these
OBS bindings; arbitrary HID/controller buttons require their own keyboard mapping.
Bindings are registered on the source and saved through OBS's normal hotkey system.

From a video source, toggle selects the configured microphone. From the microphone,
it resolves only visible eligible sources inside the current OBS program scene:

1. A unique captured-window match for the foreground Windows window.
2. Otherwise the previously selected eligible source, if it is still in program.
3. Otherwise the only eligible visible audio/video source.

If several foreground matches exist, only an explicitly remembered matching source
resolves the ambiguity. With no unambiguous selection, input stays unchanged.
Global desktop inputs and the caption source itself are excluded. Browser sources
without native audio routing are excluded from automatic selection.

The chosen source stays latched across focus and monitor changes. Moving the mouse,
opening chat or focusing OBS does not switch caption input. Toggle returns to the
microphone. If the latched source leaves the program composition, captioning returns
to the configured microphone when available. This also works offline and while
recording. The plugin does not change visual scenes or show windows. Reuse the same
caption source with **Añadir existente** where it should remain visible. Hidden
caption sources ignore shortcuts and release their capture through the existing
visibility lifecycle. A missing microphone never substitutes desktop audio.

## Implementation

`source-choice.c` resolves the current program composition through the frontend API
or channel-0 transition fallback in an embedded host. Traversal is bounded to 256
unique candidates and 32 nesting levels, with ambiguity/overflow failing closed.
Foreground metadata is read only on a source-selection key action, not continuously.
Automatic membership checks run at most five times per second while latched.

`routing-controls.c` registers standard source hotkeys. Callbacks store only a bounded
atomic request; repeated key-down and key-up do not toggle repeatedly. Input changes
are applied on the source video tick using the existing teardown and transport
discontinuity path, clearing the previous caption epoch and queued translations.
All registrations are removed before their owner is released.

`source-audio.c` owns the direct PCM subscription or private process-loopback source.
It removes callbacks before releasing references and balances activation/COM usage.
There is no new model, system dependency, background polling process or persistent
audio recording. Model weights and the engine are unchanged by this patch.

## Verification and installation

```powershell
python tools/verify_routing_controls.py
python tools/verify_scene_isolation.py --legacy <path-to-0.4.2-plugin.dll>
```

The separate libobs host uses synthetic media, microphone and outside audio. It
invokes the registered hotkey callbacks through libobs's callback router without OS
key injection. A synthetic window with native audio disabled verifies the private
process-capture adapter contract and checks that the output mix is unchanged. It
does not prove real WASAPI driver/window behavior or physical-key delivery. These
remain integration checks in a normal OBS session. No tests control the live OBS
application, use its profile, play sound through real devices or interrupt outputs.

The native-only updater preserves runtime/model/configuration files and refuses
installation while OBS is running. Install the 0.4.1 base first on a new machine,
then apply this update. The package remains unsigned.

API references: [OBS source API](https://docs.obsproject.com/reference-sources),
[OBS frontend API](https://docs.obsproject.com/reference-frontend-api),
[OBS Windows capture helper](https://github.com/obsproject/obs-studio/blob/ba2f32bdf791005443988a4955e963663e16b1ed/plugins/win-capture/audio-helpers.c),
[OBS process loopback](https://github.com/obsproject/obs-studio/blob/ba2f32bdf791005443988a4955e963663e16b1ed/plugins/win-wasapi/win-wasapi.cpp).
