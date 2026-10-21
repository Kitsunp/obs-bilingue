/* SPDX-License-Identifier: GPL-2.0-or-later
 * Real libobs playback host. Does not touch the user's OBS process/config. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <obs.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

static char obs_root[32768];
static bool find_obs_root(void)
{
    WCHAR path[32768];
    DWORD count = GetModuleFileNameW(GetModuleHandleW(L"obs.dll"), path, 32768);
    if (!count || count >= 32768) return false;
    for (int i = 0; i < 3; i++) {
        WCHAR *end = wcsrchr(path, L'\\');
        if (!end) return false;
        *end = 0;
        if (i == 0) SetDllDirectoryW(path);
    }
    return WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, path, -1,
                               obs_root, sizeof(obs_root), NULL, NULL) > 0;
}

static bool obs_path(char *buffer, size_t size, const char *relative)
{
    int length = snprintf(buffer, size, "%s/%s", obs_root, relative);
    return length >= 0 && (size_t)length < size;
}

struct frame_capture { const char *path; uint64_t start; bool written; };
struct renderer_check { const char *prefix; bool found; bool matches; };

static void check_renderer(obs_source_t *parent, obs_source_t *child, void *data)
{
    (void)parent;
    struct renderer_check *check = data;
    obs_data_t *settings = obs_source_get_settings(child);
    const char *url = obs_data_get_string(settings, "url");
    if (url && *url) {
        check->found = true;
        check->matches = strncmp(url, check->prefix, strlen(check->prefix)) == 0;
    }
    obs_data_release(settings);
}

static LONG WINAPI report_fault(EXCEPTION_POINTERS *exception)
{
    HMODULE module = NULL;
    char path[MAX_PATH] = {0};
    const void *address = exception->ExceptionRecord->ExceptionAddress;
    GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                      (LPCSTR)address, &module);
    GetModuleFileNameA(module, path, sizeof(path));
    fprintf(stderr, "Native fault: code=%lx module=%s offset=%llu\n",
            exception->ExceptionRecord->ExceptionCode, path,
            (unsigned long long)((uintptr_t)address - (uintptr_t)module));
    return EXCEPTION_EXECUTE_HANDLER;
}
static void capture_frame(void *data, struct video_data *frame)
{
    struct frame_capture *capture = data;
    if (capture->written || GetTickCount64() - capture->start < 8000) return;
    capture->written = true;
    FILE *file = fopen(capture->path, "wb");
    if (!file) return;
    fprintf(file, "P6\n1280 720\n255\n");
    for (uint32_t y = 0; y < 720; y++)
        for (uint32_t x = 0; x < 1280; x++)
            fwrite(frame->data[0] + y * frame->linesize[0] + x * 4, 1, 3, file);
    fclose(file);
}

static bool load_module(const char *path, const char *data)
{
    obs_module_t *module = NULL;
    int result = obs_open_module(&module, path, data);
    if (result != MODULE_SUCCESS) {
        fprintf(stderr, "Module open failed (%d): %s\n", result, path);
        return false;
    }
    return obs_init_module(module);
}

static bool offers(obs_property_t *list, const char *code)
{
    for (size_t i = 0; i < obs_property_list_item_count(list); i++)
        if (!strcmp(obs_property_list_item_string(list, i), code)) return true;
    return false;
}

static bool verify_language_ui(obs_source_t *source)
{
    obs_properties_t *props = obs_source_properties(source);
    obs_property_t *first = obs_properties_get(props, "rule_language_0");
    obs_property_t *second = obs_properties_get(props, "rule_language_1");
    bool ok = first && second && !offers(first, "es") && !offers(second, "en");
    obs_data_t *settings = obs_source_get_settings(source);
    obs_data_set_string(settings, "rule_language_0", "ja");
    obs_property_modified(first, settings);
    ok = ok && offers(second, "en") && !offers(second, "ja");
    obs_data_set_string(settings, "rule_language_0", "en");
    obs_property_modified(first, settings);
    obs_source_update(source, settings);
    obs_data_release(settings);
    /* Simulate the separate editable OBS dialog copy. Never rebuild props to
     * hide a missing immediate refresh, and don't update the source per click. */
    settings = obs_source_get_settings(source);
    obs_data_t *view = obs_data_create_from_json(obs_data_get_json(settings));
    obs_data_release(settings);
    obs_property_t *add = obs_properties_get(props, "add_language");
    while (obs_property_list_item_count(add) > 1) {
        char code[8];
        snprintf(code, sizeof(code), "%s", obs_property_list_item_string(add, 1));
        long long count = obs_data_get_int(view, "rule_count");
        obs_data_set_string(view, "add_language", code);
        obs_property_modified(add, view);
        char key[32];
        snprintf(key, sizeof(key), "rule_language_%lld", count);
        ok = ok && obs_data_get_int(view, "rule_count") == count + 1 &&
             obs_property_visible(obs_properties_get(props, key)) && !offers(add, code);
    }
    ok = ok && obs_data_get_int(view, "rule_count") == 28 && !obs_property_enabled(add);
    obs_data_set_int(view, "rule_color_5", 0x123456);
    obs_data_set_bool(view, "remove_rule_4", true);
    obs_property_modified(obs_properties_get(props, "remove_rule_4"), view);
    ok = ok && obs_data_get_int(view, "rule_count") == 27 &&
         obs_data_get_int(view, "rule_color_4") == 0x123456 &&
         !obs_property_visible(obs_properties_get(props, "rule_language_27")) &&
         obs_property_enabled(add);
    /* Save once, then reopen and verify persisted state. */
    obs_source_update(source, view);
    obs_data_release(view);
    obs_properties_destroy(props);
    props = obs_source_properties(source);
    settings = obs_source_get_settings(source);
    ok = ok && obs_data_get_int(settings, "rule_count") == 27 &&
         obs_data_get_int(settings, "rule_color_4") == 0x123456 &&
         obs_property_visible(obs_properties_get(props, "rule_language_26")) &&
         !obs_property_visible(obs_properties_get(props, "rule_language_27"));
    obs_data_release(settings);
    obs_properties_destroy(props);
    return ok;
}

int main(int argc, char **argv)
{
    if (!find_obs_root()) return 2;
    SetUnhandledExceptionFilter(report_fault);
    if (argc != 4 && argc != 5) {
        fprintf(stderr, "obs-test-host.exe VIDEO SECONDS PLUGIN_DLL [START_SECONDS]\n");
        return 2;
    }
    /* Keep CEF configuration separate from the user's OBS browser profile. */
    const char *config_dir = getenv("BILINGUE_TEST_CONFIG");
    if (!config_dir || !*config_dir) {
        fprintf(stderr, "BILINGUE_TEST_CONFIG must name an isolated test directory\n");
        return 2;
    }
    if (!obs_startup("en-US", config_dir, NULL)) return 3;
    char data_path[32768], graphics_path[32768], module_path[32768], module_data[32768];
    if (!obs_path(data_path, sizeof(data_path), "data/libobs/") ||
        !obs_path(graphics_path, sizeof(graphics_path), "bin/64bit/libobs-d3d11.dll")) return 3;
    obs_add_data_path(data_path);
    struct obs_audio_info ai = {48000, SPEAKERS_STEREO};
    if (!obs_reset_audio(&ai)) return 4;
    struct obs_video_info vi = {0};
    vi.graphics_module = graphics_path;
    vi.fps_num = 30; vi.fps_den = 1;
    vi.base_width = 1280; vi.base_height = 720;
    vi.output_width = 1280; vi.output_height = 720;
    vi.output_format = VIDEO_FORMAT_NV12;
    vi.colorspace = VIDEO_CS_709;
    vi.range = VIDEO_RANGE_PARTIAL;
    vi.scale_type = OBS_SCALE_BILINEAR;
    vi.gpu_conversion = true;
    int video_result = obs_reset_video(&vi);
    if (video_result != OBS_VIDEO_SUCCESS) {
        fprintf(stderr, "Video initialization: %d\n", video_result);
        obs_shutdown(); return 5;
    }
    if (!obs_path(module_path, sizeof(module_path), "obs-plugins/64bit/obs-ffmpeg.dll") ||
        !obs_path(module_data, sizeof(module_data), "data/obs-plugins/obs-ffmpeg") ||
        !load_module(module_path, module_data)) return 6;
    char plugin_data[32768];
    snprintf(plugin_data, sizeof(plugin_data), "%s", argv[3]);
    char *separator = strrchr(plugin_data, '\\');
    if (!separator) separator = strrchr(plugin_data, '/');
    if (!separator) return 7;
    snprintf(separator + 1, sizeof(plugin_data) - (size_t)(separator + 1 - plugin_data), "data");
    char isolated_data[32768];
    if (GetEnvironmentVariableA("BILINGUE_TEST_PLUGIN_DATA", isolated_data, sizeof(isolated_data)))
        snprintf(plugin_data, sizeof(plugin_data), "%s", isolated_data);
    if (!load_module(argv[3], plugin_data)) return 7;
    char source_test_env[8];
    bool source_test = GetEnvironmentVariableA("BILINGUE_SOURCE_TEST", source_test_env, sizeof(source_test_env)) != 0;
    if (source_test && (!obs_path(module_path, sizeof(module_path), "obs-plugins/64bit/obs-browser.dll") ||
        !obs_path(module_data, sizeof(module_data), "data/obs-plugins/obs-browser") ||
        !load_module(module_path, module_data))) return 10;
    char defer_env[8];
    bool defer_media = GetEnvironmentVariableA("BILINGUE_TEST_DEFER_MEDIA", defer_env, sizeof(defer_env)) != 0;
    obs_data_t *settings = obs_data_create();
    obs_data_set_bool(settings, "is_local_file", true);
    obs_data_set_string(settings, "local_file", argv[1]);
    obs_data_set_bool(settings, "looping", false);
    obs_data_set_bool(settings, "restart_on_activate", true);
    obs_data_set_bool(settings, "close_when_inactive", defer_media);
    obs_data_set_bool(settings, "hw_decode", false);
    obs_data_set_int(settings, "speed_percent", 100);
    obs_source_t *media = obs_source_create("ffmpeg_source", "Bilingue video test", settings, NULL);
    obs_data_release(settings);
    if (!media) return 8;
    obs_scene_t *scene = obs_scene_create("Bilingue test scene");
    obs_scene_add(scene, media);
    if (!defer_media) obs_set_output_source(0, obs_scene_get_source(scene));
    if (argc == 5 && !defer_media) {
        obs_source_media_play_pause(media, true);
        Sleep(300);
        int64_t position = (int64_t)(strtod(argv[4], NULL) * 1000);
        obs_source_media_set_time(media, position);
        uint64_t deadline = GetTickCount64() + 5000;
        while (obs_source_media_get_time(media) < position && GetTickCount64() < deadline) Sleep(10);
    }
    obs_data_t *caption_settings = obs_data_create();
    char test_port[16];
    if (GetEnvironmentVariableA("BILINGUE_TEST_AUDIO_PORT", test_port, sizeof(test_port))) {
        long port = strtol(test_port, NULL, 10);
        if (port < 1024 || port > 65535) return 11;
        obs_data_set_int(caption_settings, "audio_port", port);
    }
    obs_data_set_string(caption_settings, "audio_source_uuid", obs_source_get_uuid(media));
    obs_data_set_int(caption_settings, "width", 1280);
    obs_data_set_int(caption_settings, "height", 360);
    uint64_t creation_start = GetTickCount64();
    obs_source_t *filter = obs_source_create(source_test ? "obs_bilingue_source" : "obs_bilingue_filter",
                                            "Bilingue test subtitles", caption_settings, NULL);
    uint64_t creation_ms = GetTickCount64() - creation_start;
    obs_data_release(caption_settings);
    if (!filter) return 8;
    char style_test[8];
    if (GetEnvironmentVariableA("BILINGUE_STYLE_TEST", style_test, sizeof(style_test))) {
        obs_data_t *test = obs_source_get_settings(filter);
        obs_data_t *font = obs_data_create();
        obs_data_set_string(font, "face", "Consolas");
        obs_data_set_int(font, "size", 28);
        obs_data_set_int(font, "flags", 1);
        obs_data_set_obj(test, "font", font);
        obs_data_release(font);
        obs_data_set_int(test, "background_color", 0x302010);
        obs_data_set_int(test, "background_opacity", 55);
        obs_data_set_int(test, "duration_seconds", 3);
        obs_data_set_int(test, "max_rows", 2);
        obs_data_set_string(test, "color_rules", "en=#00FF00\nes=#FF00FF");
        obs_data_set_bool(test, "interactive_colors", false);
        obs_source_update(filter, test);
        obs_data_release(test);
    }
    obs_properties_t *props = obs_source_properties(filter);
    bool colors_ok = props && obs_properties_get(props, source_test ? "rule_language_0" : "color_rules") &&
                     obs_properties_get(props, "default_color") && obs_properties_get(props, "font") &&
                     obs_properties_get(props, "background_color") &&
                     obs_properties_get(props, "background_opacity") &&
                     obs_properties_get(props, "duration_seconds") && obs_properties_get(props, "stack") &&
                     obs_properties_get(props, "max_rows");
    if (props) {
        obs_data_t *style_settings = obs_source_get_settings(filter);
        obs_properties_apply_settings(props, style_settings);
        colors_ok = colors_ok && obs_properties_get(props, "translation_use_spanish_color") &&
                    obs_properties_get(props, "translation_use_original_font") &&
                    obs_properties_get(props, "translation_font") &&
                    !obs_property_enabled(obs_properties_get(props, "translation_color")) &&
                    obs_property_enabled(obs_properties_get(props, "translation_font"));
        obs_data_set_bool(style_settings, "translation_use_spanish_color", false);
        obs_data_set_bool(style_settings, "translation_use_original_font", true);
        obs_properties_apply_settings(props, style_settings);
        colors_ok = colors_ok && obs_property_enabled(obs_properties_get(props, "translation_color")) &&
                    !obs_property_enabled(obs_properties_get(props, "translation_font"));
        obs_data_set_bool(style_settings, "translation_use_spanish_color", true);
        obs_data_set_bool(style_settings, "translation_use_original_font", false);
        obs_data_release(style_settings);
    }
    if (source_test) colors_ok = colors_ok && obs_properties_get(props, "audio_source_uuid") &&
                               obs_properties_get(props, "translation_enabled") &&
                               obs_source_get_width(filter) == 1280 && obs_source_get_height(filter) == 360;
    if (props) obs_properties_destroy(props);
    if (!colors_ok) return 9;
    if (source_test && !verify_language_ui(filter)) return 11;
    char visibility_env[8];
    bool visibility_test = GetEnvironmentVariableA("BILINGUE_VISIBILITY_TEST", visibility_env, sizeof(visibility_env)) != 0;
    obs_sceneitem_t *caption_item = NULL;
    bool caption_visible = !visibility_test;
    if (source_test && !visibility_test) caption_item = obs_scene_add(scene, filter);
    else if (!source_test) obs_source_filter_add(media, filter);
    /* Resume only after the complete capture source is attached. Seek again so
     * browser warmup cannot change the region used by paired experiments. */
    bool manual_show = defer_media && source_test && !visibility_test;
    if (defer_media) {
        if (manual_show) obs_source_inc_showing(filter);
        Sleep(200);
        obs_set_output_source(0, obs_scene_get_source(scene));
    } else if (argc == 5) {
        Sleep(200);
        obs_source_media_set_time(media, (int64_t)(strtod(argv[4], NULL) * 1000));
        obs_source_media_play_pause(media, false);
    }
    uint64_t start = GetTickCount64();
    char translate_test_env[8];
    bool translate_test = GetEnvironmentVariableA("BILINGUE_TRANSLATE_TEST", translate_test_env, sizeof(translate_test_env)) != 0;
    bool translation_enabled = false;
    unsigned seconds = (unsigned)strtoul(argv[2], NULL, 10);
    char tail_env[16];
    unsigned tail_seconds = 0;
    if (GetEnvironmentVariableA("BILINGUE_TEST_TAIL_SECONDS", tail_env, sizeof(tail_env))) {
        tail_seconds = (unsigned)strtoul(tail_env, NULL, 10);
        if (tail_seconds > 5) return 11;
    }
    bool playback_paused = false;
    setvbuf(stdout, NULL, _IONBF, 0);
    printf("{\"native_color_properties\":true}\n");
    printf("{\"native_source\":%s}\n", source_test ? "true" : "false");
    printf("{\"source_creation_ms\":%llu,\"language_ui_verified\":%s}\n",
           (unsigned long long)creation_ms, source_test ? "true" : "false");
    printf("{\"start_media_ms\":%lld}\n", (long long)obs_source_media_get_time(media));
    char expected_http[16], expected_prefix[128];
    bool renderer_checked = false;
    bool check_renderer_port = source_test &&
        GetEnvironmentVariableA("BILINGUE_TEST_HTTP_PORT", expected_http, sizeof(expected_http)) != 0;
    if (check_renderer_port) {
        long port = strtol(expected_http, NULL, 10);
        if (port < 1024 || port > 65535) return 11;
        snprintf(expected_prefix, sizeof(expected_prefix), "http://127.0.0.1:%ld/overlay/original", port);
    }
    struct frame_capture capture = {getenv("BILINGUE_CAPTURE_PATH"), start, false};
    if (capture.path) {
        struct video_scale_info conversion = {0};
        conversion.format = VIDEO_FORMAT_RGBA;
        conversion.width = 1280; conversion.height = 720;
        obs_add_raw_video_callback(&conversion, capture_frame, &capture);
    }
    while (GetTickCount64() - start < ((uint64_t)seconds + tail_seconds) * 1000) {
        uint64_t elapsed = GetTickCount64() - start;
        if (check_renderer_port && !renderer_checked && elapsed >= 1000) {
            struct renderer_check check = {expected_prefix, false, false};
            obs_source_enum_active_sources(filter, check_renderer, &check);
            printf("{\"renderer_http_port_matches_engine\":%s}\n",
                   check.found && check.matches ? "true" : "false");
            renderer_checked = true;
        }
        if (tail_seconds && !playback_paused && elapsed >= (uint64_t)seconds * 1000) {
            obs_source_media_play_pause(media, true);
            playback_paused = true;
            printf("{\"playback_paused_ms\":%llu,\"media_ms\":%lld}\n",
                   (unsigned long long)elapsed, (long long)obs_source_media_get_time(media));
        }
        if (visibility_test && source_test) {
            bool wanted_visible = (elapsed >= 5000 && elapsed < 14000) || (elapsed >= 22000 && elapsed < 34000);
            if (wanted_visible != caption_visible) {
                if (!caption_item) caption_item = obs_scene_add(scene, filter);
                else obs_sceneitem_set_visible(caption_item, wanted_visible);
                caption_visible = wanted_visible;
                printf("{\"visible\":%s,\"at_ms\":%llu}\n", caption_visible ? "true" : "false", (unsigned long long)elapsed);
            }
        }
        bool wanted_translation = translate_test && elapsed >= 5000 && elapsed < 20000;
        if (wanted_translation != translation_enabled) {
            obs_data_t *options = obs_source_get_settings(filter);
            obs_data_set_bool(options, "translation_enabled", wanted_translation);
            obs_source_update(filter, options);
            obs_data_release(options);
            translation_enabled = wanted_translation;
            printf("{\"translation_enabled\":%s}\n", translation_enabled ? "true" : "false");
        }
        printf("{\"elapsed_ms\":%llu,\"media_ms\":%lld}\n",
               (unsigned long long)(GetTickCount64() - start), (long long)obs_source_media_get_time(media));
        Sleep(1000);
    }
    if (capture.path) obs_remove_raw_video_callback(capture_frame, &capture);
    printf("{\"cleanup\":\"scene\"}\n");
    obs_set_output_source(0, NULL);
    obs_source_remove(obs_scene_get_source(scene));
    if (source_test) obs_source_remove(filter);
    obs_source_remove(media);
    obs_scene_release(scene);
    if (manual_show) obs_source_dec_showing(filter);
    obs_source_release(filter);
    obs_source_release(media);
    obs_wait_for_destroy_queue();
    /* Browser destruction posts CEF tasks; finish while libobs graphics still exist. */
    if (source_test) Sleep(1000);
    printf("{\"cleanup\":\"shutdown\"}\n");
    obs_shutdown();
    printf("{\"cleanup\":\"complete\"}\n");
    return 0;
}
