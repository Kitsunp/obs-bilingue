/* SPDX-License-Identifier: GPL-2.0-or-later */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>
#include <util/windows/window-helpers.h>
#include "source-choice.h"

#define CHOICE_LIMIT 256
struct source_choices {
    obs_source_t *owner, *items[CHOICE_LIMIT];
    size_t count, depth;
    bool overflow;
};

static bool candidate(obs_source_t *source)
{
    uint32_t flags = obs_source_get_output_flags(source);
    const char *id = obs_source_get_id(source);
    if (obs_source_removed(source) || !(flags & OBS_SOURCE_AUDIO)) return false;
    if (!(flags & OBS_SOURCE_VIDEO) && strcmp(id, "wasapi_process_output_capture")) return false;
    if (!strcmp(id, "browser_source")) {
        obs_data_t *settings = obs_source_get_settings(source);
        bool audio = obs_data_get_bool(settings, "reroute_audio");
        obs_data_release(settings);
        if (!audio) return false;
    }
    return true;
}

static bool collect_source(obs_scene_t *scene, obs_sceneitem_t *item, void *data)
{
    UNUSED_PARAMETER(scene);
    struct source_choices *choices = data;
    if (!obs_sceneitem_visible(item)) return true;
    obs_source_t *source = obs_sceneitem_get_source(item);
    if (source == choices->owner) return true;
    obs_scene_t *nested = obs_group_or_scene_from_source(source);
    if (nested) {
        if (choices->depth >= 32) { choices->overflow = true; return false; }
        choices->depth++;
        obs_scene_enum_items(nested, collect_source, choices);
        choices->depth--;
    } else if (candidate(source)) {
        for (size_t i = 0; i < choices->count; i++) if (choices->items[i] == source) return true;
        if (choices->count == CHOICE_LIMIT) { choices->overflow = true; return false; }
        obs_source_t *reference = obs_source_get_ref(source);
        if (reference) choices->items[choices->count++] = reference;
    }
    return !choices->overflow;
}

static void program_choices(struct source_choices *choices)
{
    HMODULE frontend = GetModuleHandleW(L"obs-frontend-api.dll");
    obs_source_t *source = NULL;
    if (frontend) {
        typedef obs_source_t *(*get_scene_fn)(void);
        FARPROC address = GetProcAddress(frontend, "obs_frontend_get_current_scene");
        get_scene_fn get_scene = NULL;
        memcpy(&get_scene, &address, sizeof(get_scene));
        if (get_scene) source = get_scene();
    } else {
        source = obs_get_output_source(0);
        for (size_t i = 0; source && i < 16 && obs_source_get_type(source) == OBS_SOURCE_TYPE_TRANSITION; i++) {
            obs_source_t *next = obs_transition_get_active_source(source);
            obs_source_release(source);
            source = next;
        }
    }
    obs_scene_t *scene = source ? obs_group_or_scene_from_source(source) : NULL;
    if (scene && !obs_source_removed(source)) obs_scene_enum_items(scene, collect_source, choices);
    if (source) obs_source_release(source);
}

static bool matches_window(obs_source_t *source, const char *title, const char *window_class, const char *exe)
{
    if (!exe || !*exe || !window_class) return false;
    calldata_t data = {0};
    bool hooked = proc_handler_call(obs_source_get_proc_handler(source), "get_hooked", &data) &&
                  calldata_bool(&data, "hooked");
    const char *source_exe = calldata_string(&data, "executable");
    const char *source_class = calldata_string(&data, "class");
    const char *source_title = calldata_string(&data, "title");
    bool match = hooked && source_exe && source_class && source_title &&
                 !strcmp(source_exe, exe) && !strcmp(source_class, window_class) &&
                 !strcmp(source_title, title ? title : "");
    calldata_free(&data);
    return match;
}

obs_source_t *caption_choose_source(obs_source_t *owner, const char *preferred, HWND foreground)
{
    struct source_choices choices = {.owner = owner};
    program_choices(&choices);
    struct dstr title = {0}, window_class = {0}, exe = {0};
    if (foreground) {
        foreground = GetAncestor(foreground, GA_ROOT);
        ms_get_window_title(&title, foreground);
        ms_get_window_class(&window_class, foreground);
        ms_get_window_exe(&exe, foreground);
    }
    size_t matches = 0;
    obs_source_t *matched = NULL, *saved = NULL, *saved_match = NULL;
    for (size_t i = 0; i < choices.count; i++) {
        obs_source_t *source = choices.items[i];
        bool is_saved = preferred && !strcmp(obs_source_get_uuid(source), preferred);
        if (is_saved) saved = source;
        if (matches_window(source, title.array, window_class.array, exe.array)) {
            matched = source; matches++;
            if (is_saved) saved_match = source;
        }
    }
    obs_source_t *selected = choices.overflow ? NULL : (matches == 1 ? matched :
                            (matches > 1 ? saved_match : (saved ? saved :
                            (choices.count == 1 ? choices.items[0] : NULL))));
    if (selected) selected = obs_source_get_ref(selected);
    for (size_t i = 0; i < choices.count; i++) obs_source_release(choices.items[i]);
    dstr_free(&title); dstr_free(&window_class); dstr_free(&exe);
    return selected;
}

bool caption_source_in_program(obs_source_t *owner, const char *uuid)
{
    struct source_choices choices = {.owner = owner};
    program_choices(&choices);
    bool found = false;
    for (size_t i = 0; i < choices.count; i++) {
        if (!strcmp(obs_source_get_uuid(choices.items[i]), uuid)) found = true;
        obs_source_release(choices.items[i]);
    }
    return found && !choices.overflow;
}
