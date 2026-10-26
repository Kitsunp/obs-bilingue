/* SPDX-License-Identifier: GPL-2.0-or-later */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>
#include <math.h>
#include "caption-transport.h"
#include "scene-audio.h"

/* This private, silent source runs after OBS renders the active program tree,
 * before libobs discards its audio buffers. It is never added to an output or
 * scene. No active-child edge back to the selected scene is created. */
#define SCENE_INPUT_LIMIT 256
#define SCENE_DEPTH_LIMIT 32
struct scene_input { obs_source_t *source; float gain; };
struct scene_selection {
    struct scene_input inputs[SCENE_INPUT_LIMIT];
    size_t count;
    bool overflow;
};
struct scene_audio {
    SRWLOCK lock;
    void *transport;
    obs_weak_source_t *scene;
    size_t mix;
    uint64_t last_timestamp;
    struct scene_selection selections[3];
    PVOID volatile current_selection;
    PVOID volatile reading_selection;
    float samples[MAX_AUDIO_CHANNELS][AUDIO_OUTPUT_FRAMES];
};
struct scene_walk {
    struct scene_selection *selection;
    obs_source_t *ancestors[SCENE_DEPTH_LIMIT];
    size_t depth;
    float gain;
};

static bool collect_input(obs_scene_t *scene, obs_sceneitem_t *item, void *data)
{
    UNUSED_PARAMETER(scene);
    struct scene_walk *walk = data;
    if (!obs_sceneitem_visible(item)) return true;
    obs_source_t *source = obs_sceneitem_get_source(item);
    obs_scene_t *nested = obs_group_or_scene_from_source(source);
    if (nested) {
        if (walk->depth == SCENE_DEPTH_LIMIT) { walk->selection->overflow = true; return false; }
        for (size_t i = 0; i < walk->depth; i++) if (walk->ancestors[i] == source) return true;
        struct scene_walk child = *walk;
        child.ancestors[child.depth++] = source;
        child.gain *= obs_source_muted(source) ? 0.0f : obs_source_get_volume(source);
        obs_scene_enum_items(nested, collect_input, &child);
    } else if ((obs_source_get_output_flags(source) & OBS_SOURCE_AUDIO) &&
               !(obs_source_get_output_flags(source) & OBS_SOURCE_COMPOSITE)) {
        struct scene_selection *selection = walk->selection;
        /* A shared input is captioned once, even if several scene paths use it.
         * Its rendered buffer already contains input filters, mute and volume. */
        for (size_t i = 0; i < selection->count; i++) {
            if (selection->inputs[i].source == source) {
                if (walk->gain > selection->inputs[i].gain) selection->inputs[i].gain = walk->gain;
                return true;
            }
        }
        if (selection->count == SCENE_INPUT_LIMIT) { selection->overflow = true; return false; }
        obs_source_t *reference = obs_source_get_ref(source);
        if (reference) selection->inputs[selection->count++] = (struct scene_input){reference, walk->gain};
    }
    return !walk->selection->overflow;
}

static void release_selection(struct scene_selection *selection)
{
    for (size_t i = 0; i < selection->count; i++) obs_source_release(selection->inputs[i].source);
}

void caption_scene_audio_refresh(obs_source_t *tap)
{
    struct scene_audio *state = obs_obj_get_data(tap);
    struct scene_selection next = {0};
    struct scene_walk walk = {.selection = &next, .depth = 1, .gain = 1.0f};
    obs_source_t *root = obs_weak_source_get_source(state->scene);
    walk.ancestors[0] = root;
    obs_scene_t *scene = root ? obs_group_or_scene_from_source(root) : NULL;
    if (scene) obs_scene_enum_items(scene, collect_input, &walk);
    if (root) obs_source_release(root);
    /* Publish a prepared bank without ever locking/waiting in the audio path.
     * The audio thread announces the bank it reads and rechecks publication.
     * Three fixed banks leave one writable bank even during a concurrent swap. */
    struct scene_selection *current = InterlockedCompareExchangePointer(&state->current_selection, NULL, NULL);
    struct scene_selection *reading = InterlockedCompareExchangePointer(&state->reading_selection, NULL, NULL);
    struct scene_selection *spare = NULL;
    for (size_t i = 0; i < 3; i++)
        if (&state->selections[i] != current && &state->selections[i] != reading) {
            spare = &state->selections[i]; break;
        }
    bool was_overflow = current->overflow;
    release_selection(spare);
    *spare = next;
    InterlockedExchangePointer(&state->current_selection, spare);
    for (size_t i = 0; i < 3; i++) {
        struct scene_selection *retired = &state->selections[i];
        if (retired != spare && retired != InterlockedCompareExchangePointer(&state->reading_selection, NULL, NULL)) {
            release_selection(retired);
            retired->count = 0;
        }
    }
    if (next.overflow && !was_overflow)
        blog(LOG_WARNING, "[Bilingue] Scene capture paused: input/depth safety limit exceeded");
}

static void clock_audio(void *data, size_t mix, struct audio_data *audio)
{
    UNUSED_PARAMETER(data); UNUSED_PARAMETER(mix); UNUSED_PARAMETER(audio);
    /* Keep the chosen OBS mixer rendered even while offline. Never read the
     * complete program mix here: it contains audio outside the selected scene. */
}

static bool render_audio(void *data, uint64_t *timestamp, struct obs_source_audio_mix *output,
                         uint32_t mixers, size_t channels, size_t rate)
{
    UNUSED_PARAMETER(timestamp); UNUSED_PARAMETER(output);
    struct scene_audio *state = data;
    if (!TryAcquireSRWLockShared(&state->lock)) return false;
    if (!state->transport) { ReleaseSRWLockShared(&state->lock); return false; }
    struct scene_selection *selection;
    do {
        selection = InterlockedCompareExchangePointer(&state->current_selection, NULL, NULL);
        InterlockedExchangePointer(&state->reading_selection, selection);
    } while (selection != InterlockedCompareExchangePointer(&state->current_selection, NULL, NULL));
    memset(state->samples, 0, sizeof(state->samples));
    obs_source_t *root = obs_weak_source_get_source(state->scene);
    uint64_t scene_ts = root ? obs_source_get_audio_timestamp(root) : 0;
    bool active = root && obs_source_active(root) && !obs_source_removed(root) &&
                  !obs_source_audio_pending(root) && !selection->overflow &&
                  (mixers & (1u << state->mix)) && scene_ts;
    /* OBS can render a buffered block more than once during startup/rebuffering. */
    if (active && scene_ts == state->last_timestamp) {
        obs_source_release(root);
        InterlockedExchangePointer(&state->reading_selection, NULL);
        ReleaseSRWLockShared(&state->lock);
        return false;
    }
    state->last_timestamp = active ? scene_ts : 0;
    float scene_gain = root && !obs_source_muted(root) ? obs_source_get_volume(root) : 0.0f;
    if (active && scene_gain != 0.0f) {
        for (size_t i = 0; i < selection->count; i++) {
            struct scene_input *input = &selection->inputs[i];
            if (obs_source_audio_pending(input->source)) continue;
            uint64_t input_ts = obs_source_get_audio_timestamp(input->source);
            if (!input_ts) continue;
            uint64_t delta = input_ts > scene_ts ? input_ts - scene_ts : scene_ts - input_ts;
            /* Bound before multiplication so corrupt/discontinuous timestamps
             * cannot overflow or index outside this audio block. */
            if (delta >= ((uint64_t)AUDIO_OUTPUT_FRAMES * 1000000000ULL + rate - 1) / rate) continue;
            size_t offset = (size_t)(delta * rate / 1000000000ULL);
            size_t src = input_ts < scene_ts ? offset : 0;
            size_t dst = input_ts > scene_ts ? offset : 0;
            size_t count = AUDIO_OUTPUT_FRAMES - offset;
            struct obs_source_audio_mix audio;
            obs_source_get_audio_mix(input->source, &audio);
            float gain = scene_gain * input->gain;
            for (size_t ch = 0; ch < channels && ch < MAX_AUDIO_CHANNELS; ch++) {
                float *plane = audio.output[state->mix].data[ch];
                if (!plane) continue;
                for (size_t frame = 0; frame < count; frame++)
                    state->samples[ch][dst + frame] += plane[src + frame] * gain;
            }
        }
    }
    uint8_t *planes[MAX_AV_PLANES] = {0};
    for (size_t ch = 0; ch < channels && ch < MAX_AUDIO_CHANNELS; ch++) {
        for (size_t frame = 0; frame < AUDIO_OUTPUT_FRAMES; frame++) {
            float value = state->samples[ch][frame];
            state->samples[ch][frame] = isfinite(value) ? fmaxf(-1.0f, fminf(1.0f, value)) : 0.0f;
        }
        planes[ch] = (uint8_t *)state->samples[ch];
    }
    caption_capture(state->transport, planes, AUDIO_OUTPUT_FRAMES, false);
    if (root) obs_source_release(root);
    InterlockedExchangePointer(&state->reading_selection, NULL);
    ReleaseSRWLockShared(&state->lock);
    return false; /* This tap must never contribute audio to the live output. */
}

static const char *tap_name(void *unused) { UNUSED_PARAMETER(unused); return "Bilingue private scene audio tap"; }
static void *create_tap(obs_data_t *settings, obs_source_t *source)
{
    UNUSED_PARAMETER(settings); UNUSED_PARAMETER(source);
    struct scene_audio *state = bzalloc(sizeof(*state));
    InitializeSRWLock(&state->lock);
    state->current_selection = &state->selections[0];
    return state;
}
static void destroy_tap(void *data)
{
    struct scene_audio *state = data;
    for (size_t i = 0; i < 3; i++) release_selection(&state->selections[i]);
    if (state->scene) obs_weak_source_release(state->scene);
    bfree(state);
}

void caption_register_scene_audio(void)
{
    struct obs_source_info info = {0};
    info.id = "obs_bilingue_scene_audio_tap";
    info.type = OBS_SOURCE_TYPE_INPUT;
    info.output_flags = OBS_SOURCE_AUDIO | OBS_SOURCE_DO_NOT_DUPLICATE | OBS_SOURCE_CAP_DISABLED;
    info.get_name = tap_name; info.create = create_tap; info.destroy = destroy_tap;
    info.audio_render = render_audio;
    obs_register_source(&info);
}

obs_source_t *caption_scene_audio_create(void *transport, obs_source_t *scene, size_t mix)
{
    obs_source_t *tap = obs_source_create_private("obs_bilingue_scene_audio_tap", "Bilingue scene audio tap", NULL);
    if (!tap) return NULL;
    struct scene_audio *state = obs_obj_get_data(tap);
    if (!state) { obs_source_release(tap); return NULL; }
    state->scene = obs_source_get_weak_source(scene);
    state->mix = mix;
    caption_scene_audio_refresh(tap);
    obs_add_raw_audio_callback(mix, NULL, clock_audio, tap);
    AcquireSRWLockExclusive(&state->lock);
    state->transport = transport;
    ReleaseSRWLockExclusive(&state->lock);
    return tap;
}

void caption_scene_audio_destroy(obs_source_t *tap)
{
    struct scene_audio *state = obs_obj_get_data(tap);
    /* Wait for an in-flight render before the owner destroys its transport. */
    AcquireSRWLockExclusive(&state->lock);
    state->transport = NULL;
    ReleaseSRWLockExclusive(&state->lock);
    obs_remove_raw_audio_callback(state->mix, clock_audio, tap);
    obs_source_release(tap);
}
