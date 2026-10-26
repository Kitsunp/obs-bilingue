/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <string.h>
#include <stdlib.h>
#include <util/windows/window-helpers.h>
#include "source-audio-test.h"

struct process_test { obs_source_t *source, *media; uint64_t callbacks, forwarded; };
static void forward_audio(void *data, obs_source_t *source, const struct audio_data *audio, bool muted)
{
    UNUSED_PARAMETER(source);
    struct process_test *state = data;
    state->callbacks++;
    if (muted || obs_source_get_audio_mixers(state->source) ||
        obs_source_get_monitoring_type(state->source) != OBS_MONITORING_TYPE_NONE) return;
    struct obs_audio_info info;
    if (!obs_get_audio_info(&info)) return;
    struct obs_source_audio packet = {0};
    packet.frames = audio->frames;
    packet.timestamp = audio->timestamp;
    packet.format = AUDIO_FORMAT_FLOAT_PLANAR;
    packet.samples_per_sec = info.samples_per_sec;
    packet.speakers = info.speakers;
    for (size_t i = 0; i < MAX_AV_PLANES; i++) packet.data[i] = audio->data[i];
    obs_source_output_audio(state->source, &packet);
    state->forwarded++;
}
static const char *test_name(void *data) { UNUSED_PARAMETER(data); return "Synthetic window audio test"; }
static void *create_process(obs_data_t *settings, obs_source_t *source)
{
    if (!obs_obj_is_private(source) || !*obs_data_get_string(settings, "window")) return NULL;
    const char *audio = getenv("BILINGUE_TEST_APP_AUDIO");
    if (!audio) return NULL;
    struct process_test *state = bzalloc(sizeof(*state));
    state->source = source;
    obs_data_t *media = obs_data_create();
    obs_data_set_bool(media, "is_local_file", true);
    obs_data_set_string(media, "local_file", audio);
    obs_data_set_bool(media, "looping", true);
    obs_data_set_bool(media, "close_when_inactive", false);
    state->media = obs_source_create_private("ffmpeg_source", "Private synthetic app audio", media);
    obs_data_release(media);
    if (!state->media) { bfree(state); return NULL; }
    obs_source_set_audio_mixers(state->media, 0);
    obs_source_add_audio_capture_callback(state->media, forward_audio, state);
    obs_source_inc_active(state->media);
    return state;
}
static void destroy_process(void *data)
{
    struct process_test *state = data;
    obs_source_remove_audio_capture_callback(state->media, forward_audio, state);
    obs_source_dec_active(state->media);
    blog(LOG_INFO, "[fixture] process callbacks=%llu forwarded=%llu", (unsigned long long)state->callbacks,
         (unsigned long long)state->forwarded);
    obs_source_release(state->media);
    bfree(state);
}
static void get_hooked(void *data, calldata_t *output)
{
    obs_source_t *source = data;
    obs_data_t *settings = obs_source_get_settings(source);
    bool hooked = obs_data_get_bool(settings, "fixture_hooked");
    calldata_set_bool(output, "hooked", hooked);
    char *window_class = NULL, *title = NULL, *exe = NULL;
    ms_build_window_strings(obs_data_get_string(settings, "fixture_window"), &window_class, &title, &exe);
    calldata_set_string(output, "title", title ? title : "Fixture video");
    calldata_set_string(output, "class", window_class ? window_class : "FixtureClass");
    calldata_set_string(output, "executable", exe ? exe : "fixture.exe");
    bfree(window_class); bfree(title); bfree(exe);
    obs_data_release(settings);
}
static void *create_window(obs_data_t *settings, obs_source_t *source)
{
    UNUSED_PARAMETER(settings);
    proc_handler_add(obs_source_get_proc_handler(source),
        "void get_hooked(out bool hooked, out string title, out string class, out string executable)",
        get_hooked, source);
    return source;
}
static void destroy_window(void *data) { UNUSED_PARAMETER(data); }
static void render_window(void *data, gs_effect_t *effect) { UNUSED_PARAMETER(data); UNUSED_PARAMETER(effect); }
static uint32_t window_size(void *data) { UNUSED_PARAMETER(data); return 64; }

void source_audio_test_register(bool mock_process)
{
    struct obs_source_info window = {0};
    window.id = "window_capture"; window.type = OBS_SOURCE_TYPE_INPUT;
    window.output_flags = OBS_SOURCE_VIDEO | OBS_SOURCE_AUDIO | OBS_SOURCE_CUSTOM_DRAW;
    window.get_name = test_name; window.create = create_window; window.destroy = destroy_window;
    window.get_width = window_size; window.get_height = window_size; window.video_render = render_window;
    obs_register_source(&window);
    if (mock_process) {
        struct obs_source_info process = {0};
        process.id = "wasapi_process_output_capture"; process.type = OBS_SOURCE_TYPE_INPUT;
        process.output_flags = OBS_SOURCE_AUDIO;
        process.get_name = test_name; process.create = create_process; process.destroy = destroy_process;
        obs_register_source(&process);
    }
}

obs_source_t *source_audio_test_window(const char *window)
{
    obs_data_t *settings = obs_data_create();
    obs_data_set_bool(settings, "capture_audio", false);
    obs_data_set_bool(settings, "fixture_hooked", true);
    if (window) obs_data_set_string(settings, "fixture_window", window);
    obs_source_t *source = obs_source_create("window_capture", "Synthetic captured window", settings, NULL);
    obs_data_release(settings);
    return source;
}
