# Scene audio isolation 0.4.3

Select **Escena: name (solo sus fuentes)** under **Audio que se va a subtitular**.
The plugin captions the audio inputs visible in that scene, including nested scenes
and groups, without adding global desktop or microphone sources outside its tree.
Existing source choices are preserved on update. Program-mix and individual-input
capture remain separate choices.

Example: a scene contains a Media Source video while Discord reaches the stream
through global Desktop Audio. Scene capture receives the video's OBS audio input;
it does not receive the separate global Desktop Audio input. Both still reach the
stream according to normal OBS routing. No output, source mute, volume, monitoring
device or track assignment is changed by scene capture.

An OBS scene is not an application-audio separator. A Window/Display Capture input
provides an image; capture the player's application audio separately and include
that audio source in the scene. Media Source audio and Browser Source audio controlled
through OBS can be used directly. If Desktop Audio itself is inside the selected
scene, every application already combined into that input remains combined. The
plugin does not infer audio membership from video pixels or application names.

## Behavior

- Only a scene active in the program composition is read. Selecting a scene does
  not activate it, start playback or make preview-only audio audible. An inactive,
  removed or unavailable scene stays silent; there is no fallback to desktop audio.
- Visible audio inputs and nested scene/group membership are refreshed on the video
  thread at approximately 100 ms intervals. Hidden items are omitted. Audio already
  buffered or text already displayed follows the existing caption lifecycle.
- The chosen OBS track is read from each input's rendered float buffers, after its
  audio filters and input mute/volume processing. Parent scene/group mute and gain
  are applied to the scoped sum. Fixed tracks 1–6 and the 0.4.2 automatic track rule
  remain available. Inputs routed away from the selected track stay silent.
- The same input appearing in multiple visible paths is included once, using the
  largest parent-path gain, rather than doubling speech. A source also used outside
  the scene is still captured once inside the selected scope.
- Changing the selected input/scene or mixer marks a transport discontinuity. The
  existing engine clears previous caption rows, pending translation and its audio
  epoch before decoding the new input. This reuses the loaded model weights.
- This is a scope mix, not a replica of every output transition envelope: visibility
  refreshes can lag by one refresh interval and custom composite/transition inputs
  are not expanded. Native scenes and groups are expanded. Frame-accurate show/hide
  fades and Studio Mode preview composition require separate validation.

## Implementation

OBS scenes render/composite audio independently of individual input capture
callbacks. Reading only the final program mix cannot remove an unrelated global
input. Also, a native scene's rendered audio may omit inputs shared in another
active path because OBS handles shared sources separately during final mixing.

`native/scene-audio.c` therefore creates a private silent OBS audio source with a
custom `audio_render` callback. OBS renders the active program tree first, then
this registered audio source. It reads only the selected visible input buffers
before libobs discards them, aligns them to the scene's audio timestamp and passes
their scoped sum to the existing bounded caption transport. It always returns
false from `audio_render`, so it contributes no audio to any output. A no-op raw
audio callback keeps the selected mixer rendered while offline; its full-program
PCM is never used as caption input in this mode.

The selected scene is held weakly to avoid a reference cycle when the caption source
is itself inside that scene. Input references live in three fixed snapshot banks.
The video thread publishes a prepared bank atomically; the audio thread announces
and rechecks the bank it reads, allowing retired references to be reclaimed outside
the audio path. There is no membership enumeration, allocation, networking, model
inference or waiting for a membership update in the audio render callback. A separate
lifecycle lock prevents an in-flight render from accessing a destroyed transport.

Memory is bounded to the banks, a fixed planar audio block, OBS's own source buffers
and the existing transport queue. The safety limits are 256 unique inputs and 32
scene/group levels. Exceeding either pauses scoped capture and logs the condition;
it never falls back to a broader scope or sends a partial selection. No model,
language detector, translation engine or system runtime is changed.

## Build, install and verification

Build `native/build.ps1`, then `native/build-update.ps1 -Inno <path-to-ISCC.exe>`.
The resulting `OBS-Bilingue-0.4.3-Windows-x64-Update.exe` updates only the native DLL
in both supported OBS directory layouts. It requires an existing installation,
preserves runtime metadata/models/configuration/uninstaller and refuses to run while
OBS is open. Close OBS yourself before applying the update. This build is unsigned.
For a new installation, install the 0.4.1 base before applying this native update.

```powershell
python tools/verify_scene_isolation.py --legacy <path-to-0.4.2-plugin.dll> --stress-seconds 130
python tools/verify_scene_audio.py --legacy <path-to-0.4.2-plugin.dll>
```

The isolated libobs host uses real ffmpeg audio inputs and a small video surface,
with no ASR model, browser runtime, hardware capture, user profile or live OBS control.
It reproduces the old missing scene audio and checks exclusion of simultaneous global
audio, nested scenes, group gains, multiple inputs, shared sources, item visibility,
membership edits, source selection changes, inactive/muted/removed scenes, fixed-track
silence and caption visibility. The optional stress case switches scene selection
every 300 ms while both clips continue playing. Aggregate PCM metrics establish
capture/routing behavior, not transcription accuracy or multi-hour streaming stability.

Reference contracts: [OBS audio backend](https://docs.obsproject.com/backend-design),
[Source API](https://docs.obsproject.com/reference-sources),
[Scene API](https://docs.obsproject.com/reference-scenes). The timing/order checks
use the pinned OBS 32.2.2 source revision documented in `tools/bootstrap_build.ps1`.
