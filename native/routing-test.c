/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Synthetic libobs fixture. No frontend, devices, profiles or OS key injection. */
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include "program-audio.h"
#include "routing-test.h"
#include "source-audio-test.h"

struct routing_test {
    const char *mode;
    obs_scene_t *a, *b;
    obs_sceneitem_t *caption_a, *caption_b, *preferred_b;
    obs_source_t *caption, *second, *microphone;
    obs_source_t *preferred;
    bool owns_preferred;
    obs_hotkey_id toggle, mic, scene;
    size_t step;
};

static void press_key(obs_hotkey_id key)
{
    obs_hotkey_trigger_routed_callback(key, true);
    obs_hotkey_trigger_routed_callback(key, true); /* A held/repeated press must not toggle twice. */
    obs_hotkey_trigger_routed_callback(key, false);
}

static bool collect_hotkey(void *data, obs_hotkey_id id, obs_hotkey_t *key)
{
    struct routing_test *test = data;
    const char *name = obs_hotkey_get_name(key);
    if (!strcmp(name, "obs_bilingue.toggle_source_mic")) test->toggle = id;
    if (!strcmp(name, "obs_bilingue.listen_mic")) test->mic = id;
    if (!strcmp(name, "obs_bilingue.listen_source")) test->scene = id;
    return true;
}

struct routing_test *routing_test_create(const char *mode, obs_source_t *media)
{
    struct routing_test *test = bzalloc(sizeof(*test));
    test->mode = mode;
    test->toggle = test->mic = test->scene = OBS_INVALID_HOTKEY_ID;
    test->a = obs_scene_create("Routing program A");
    test->b = obs_scene_create("Routing program B");
    test->preferred = media;
    if (!strcmp(mode, "routing-window") || !strcmp(mode, "routing-toggle")) {
        source_audio_test_register(true);
        test->preferred = source_audio_test_window(NULL);
        test->owns_preferred = true;
    }
    obs_scene_add(test->a, test->preferred);
    test->preferred_b = obs_scene_add(test->b, test->preferred);
    obs_data_t *settings = obs_source_get_settings(media);
    obs_data_set_bool(settings, "looping", true);
    test->second = obs_source_create("ffmpeg_source", "Routing scene B audio", settings, NULL);
    const char *microphone_audio = getenv("BILINGUE_TEST_MIC_AUDIO");
    if (microphone_audio) obs_data_set_string(settings, "local_file", microphone_audio);
    test->microphone = obs_source_create("ffmpeg_source", "Routing synthetic microphone", settings, NULL);
    obs_data_release(settings);
    if (!test->second || !test->microphone) { routing_test_destroy(test); return NULL; }
    obs_source_set_volume(test->second, 0.25f);
    obs_source_set_volume(test->microphone, 1.0f);
    obs_scene_add(test->b, test->second);
    obs_set_output_source(3, test->microphone);
    return test;
}

void routing_test_settings(struct routing_test *test, obs_data_t *settings)
{
    obs_data_set_string(settings, "audio_source_uuid", obs_source_get_uuid(
                        !strcmp(test->mode, "routing-ambiguous") ? test->microphone : test->preferred));
    obs_data_set_string(settings, "hotkey_microphone_uuid", !strcmp(test->mode, "routing-missing-mic") ?
                        "unavailable-microphone" : obs_source_get_uuid(test->microphone));
}

bool routing_test_attach(struct routing_test *test, obs_source_t *caption)
{
    test->caption = caption;
    test->caption_a = obs_scene_add(test->a, caption);
    test->caption_b = obs_scene_add(test->b, caption);
    obs_enum_hotkeys(collect_hotkey, test);
    obs_hotkey_enable_callback_rerouting(true);
    obs_set_output_source(0, obs_scene_get_source(test->a));
    return test->toggle != OBS_INVALID_HOTKEY_ID && test->mic != OBS_INVALID_HOTKEY_ID &&
           test->scene != OBS_INVALID_HOTKEY_ID;
}

bool routing_test_tick(struct routing_test *test, uint64_t elapsed)
{
    const uint64_t times[] = {2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000};
    while (test->step < sizeof(times) / sizeof(*times) && elapsed >= times[test->step]) {
        size_t step = test->step++;
        if (!strcmp(test->mode, "routing-hidden")) {
            if (step == 0 || step == 2) {
                obs_sceneitem_set_visible(test->caption_a, step == 2);
                obs_sceneitem_set_visible(test->caption_b, step == 2);
            }
            if (step == 1) press_key(test->mic);
        } else {
            if (step == 0 || step == 4) obs_set_output_source(0, obs_scene_get_source(test->b));
            if (step == 2) obs_set_output_source(0, obs_scene_get_source(test->a));
            if (!strcmp(test->mode, "routing-ambiguous") && step == 1) press_key(test->scene);
            if (!strcmp(test->mode, "routing-left")) {
                if (step == 0 || step == 3) press_key(test->scene);
                if (step == 1) obs_sceneitem_set_visible(test->preferred_b, false);
            }
            bool toggle = !strcmp(test->mode, "routing-toggle");
            if (toggle && (step == 1 || step == 3)) press_key(test->toggle);
            if ((toggle && step == 5) || (!strcmp(test->mode, "routing-missing-mic") && step == 1))
                press_key(test->mic);
            if (toggle && step == 6) press_key(test->scene);
            if (step == 7) obs_hotkey_trigger_routed_callback(test->toggle, false); /* release is inert */
        }
    }
    if (elapsed >= 9500) {
        obs_data_t *settings = obs_source_get_settings(test->caption);
        bool microphone = !strcmp(test->mode, "routing-left") || !strcmp(test->mode, "routing-ambiguous");
        bool follows = !strcmp(obs_data_get_string(settings, "audio_source_uuid"),
                               obs_source_get_uuid(microphone ? test->microphone : test->preferred));
        obs_data_release(settings);
        if (!follows) return false;
    }
    return true;
}

void routing_test_destroy(struct routing_test *test)
{
    obs_set_output_source(3, NULL);
    obs_source_remove(obs_scene_get_source(test->a));
    obs_source_remove(obs_scene_get_source(test->b));
    obs_scene_release(test->a);
    obs_scene_release(test->b);
    if (test->second) { obs_source_remove(test->second); obs_source_release(test->second); }
    if (test->microphone) { obs_source_remove(test->microphone); obs_source_release(test->microphone); }
    if (test->owns_preferred) { obs_source_remove(test->preferred); obs_source_release(test->preferred); }
    bfree(test);
}
