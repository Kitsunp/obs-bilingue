/* SPDX-License-Identifier: GPL-2.0-or-later */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>
#include <stdio.h>
#include "program-audio.h"
#include "routing-controls.h"
#include "source-choice.h"

enum routing_action { ROUTE_NONE, ROUTE_TOGGLE, ROUTE_MICROPHONE, ROUTE_SOURCE };
struct caption_controls {
    obs_source_t *source; /* Borrowed: the caption source owns these controls. */
    obs_hotkey_id keys[3];
    volatile LONG enabled, pending;
    volatile LONG down[3];
    bool automatic;
    float check_seconds;
    char latched[64];
};

static void hotkey_pressed(void *data, obs_hotkey_id id, obs_hotkey_t *hotkey, bool pressed)
{
    UNUSED_PARAMETER(hotkey);
    struct caption_controls *controls = data;
    for (size_t i = 0; i < 3; i++) if (controls->keys[i] == id) {
        LONG previous = InterlockedExchange(&controls->down[i], pressed);
        if (!pressed || previous || !InterlockedCompareExchange(&controls->enabled, 0, 0)) break;
        /* Do not update OBS sources, scenes or capture callbacks on this thread. */
        InterlockedExchange(&controls->pending, (LONG)i + ROUTE_TOGGLE);
        break;
    }
}

static void default_microphone(obs_data_t *settings)
{
    if (*obs_data_get_string(settings, "hotkey_microphone_uuid")) return;
    char candidate[64] = {0};
    bool ambiguous = false;
    for (uint32_t i = 1; i < MAX_CHANNELS; i++) {
        obs_source_t *source = obs_get_output_source(i);
        if (!source) continue;
        /* This Windows-only build can reuse an unambiguous global input-capture
         * source. Never guess from a device name, select desktop capture or mute it. */
        if (!strcmp(obs_source_get_id(source), "wasapi_input_capture")) {
            const char *uuid = obs_source_get_uuid(source);
            if (!*candidate) snprintf(candidate, sizeof(candidate), "%s", uuid);
            else if (strcmp(candidate, uuid)) ambiguous = true;
        }
        obs_source_release(source);
    }
    if (*candidate && !ambiguous) obs_data_set_string(settings, "hotkey_microphone_uuid", candidate);
}

struct caption_controls *caption_controls_create(obs_source_t *source, obs_data_t *settings)
{
    struct caption_controls *controls = bzalloc(sizeof(*controls));
    controls->source = source;
    default_microphone(settings);
    const char *names[] = {"obs_bilingue.toggle_source_mic", "obs_bilingue.listen_mic", "obs_bilingue.listen_source"};
    const char *descriptions[] = {"Bilingue: alternar microfono / fuente elegida",
                                 "Bilingue: subtitular microfono", "Bilingue: subtitular fuente elegida"};
    for (size_t i = 0; i < 3; i++)
        controls->keys[i] = obs_hotkey_register_source(source, names[i], descriptions[i], hotkey_pressed, controls);
    return controls;
}

void caption_controls_enable(struct caption_controls *controls, bool enabled)
{
    InterlockedExchange(&controls->enabled, enabled);
    if (!enabled) InterlockedExchange(&controls->pending, ROUTE_NONE);
}

void caption_controls_tick(struct caption_controls *controls, float seconds)
{
    LONG action = InterlockedExchange(&controls->pending, ROUTE_NONE);
    if (!InterlockedCompareExchange(&controls->enabled, 0, 0)) return;
    controls->check_seconds -= seconds;
    if (!action && (!controls->automatic || controls->check_seconds > 0.0f)) return;
    controls->check_seconds = 0.2f;
    obs_data_t *settings = obs_source_get_settings(controls->source);
    default_microphone(settings); /* Global inputs may load after the caption source. */
    const char *current = obs_data_get_string(settings, "audio_source_uuid");
    const char *microphone = obs_data_get_string(settings, "hotkey_microphone_uuid");
    if (!action) {
        if (strcmp(current, controls->latched)) controls->automatic = false;
        else if (!caption_source_in_program(controls->source, controls->latched)) action = ROUTE_MICROPHONE;
        if (!action) { obs_data_release(settings); return; }
    }
    bool want_mic = action == ROUTE_MICROPHONE || (action == ROUTE_TOGGLE && strcmp(current, microphone));
    const char *saved = obs_data_get_string(settings, "hotkey_return_source_uuid");
    obs_source_t *detected = want_mic ? NULL : caption_choose_source(controls->source,
                               strcmp(current, microphone) ? current : saved, GetForegroundWindow());
    const char *next = want_mic ? microphone : (detected ? obs_source_get_uuid(detected) : "");
    bool valid = true;
    if (want_mic) {
        obs_source_t *input = *microphone ? obs_get_source_by_uuid(microphone) : NULL;
        valid = input && input != controls->source && !obs_source_removed(input) &&
                obs_source_get_type(input) == OBS_SOURCE_TYPE_INPUT &&
                (obs_source_get_output_flags(input) & OBS_SOURCE_AUDIO);
        if (input) obs_source_release(input);
        if (!valid) blog(LOG_WARNING, "[Bilingue] Select an available microphone input for caption hotkeys");
    } else {
        valid = detected != NULL;
        if (!valid) blog(LOG_WARNING, "[Bilingue] No unambiguous visible audio/video source in program; select one first");
    }
    if (valid) {
        controls->automatic = !want_mic;
        if (want_mic && strcmp(current, microphone))
            obs_data_set_string(settings, "hotkey_return_source_uuid", current);
        if (!want_mic) snprintf(controls->latched, sizeof(controls->latched), "%s", next);
        if (strcmp(current, next)) {
            obs_data_set_string(settings, "audio_source_uuid", next);
            obs_source_update(controls->source, settings);
        }
    }
    if (detected) obs_source_release(detected);
    obs_data_release(settings);
}

void caption_controls_destroy(struct caption_controls *controls)
{
    caption_controls_enable(controls, false);
    for (size_t i = 0; i < 3; i++) if (controls->keys[i] != OBS_INVALID_HOTKEY_ID)
        obs_hotkey_unregister(controls->keys[i]);
    bfree(controls);
}
