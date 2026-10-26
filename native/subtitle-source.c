/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "caption-transport.h"
#include <string.h>
#include <stdio.h>
#include <windows.h>
#include "language-rules.h"
#include "program-audio.h"

struct subtitle_source {
    obs_source_t *source, *browser, *preview;
    obs_weak_source_t *audio_target;
    void *transport;
    void *preview_window;
    uint32_t width, height;
    volatile LONG visible;
    bool audio_dirty;
    char audio_uuid[64];
    unsigned long renderer_generation;
    bool program_capture;
    size_t program_mix;
};

static void capture_program(void *data, size_t mix, struct audio_data *audio)
{
    UNUSED_PARAMETER(mix);
    struct subtitle_source *s = data;
    caption_capture(s->transport, audio->data, audio->frames, false);
}

static void capture_audio(void *data, obs_source_t *source, const struct audio_data *audio, bool muted)
{
    UNUSED_PARAMETER(source);
    struct subtitle_source *s = data;
    caption_capture(s->transport, audio->data, audio->frames, muted);
}

static void detach_audio(struct subtitle_source *s)
{
    if (s->program_capture) {
        obs_remove_raw_audio_callback(s->program_mix, capture_program, s);
        s->program_capture = false;
    }
    if (!s->audio_target) return;
    obs_source_t *target = obs_weak_source_get_source(s->audio_target);
    if (target) {
        obs_source_remove_audio_capture_callback(target, capture_audio, s);
        obs_source_release(target);
    }
    obs_weak_source_release(s->audio_target);
    s->audio_target = NULL;
}

static void sync_audio(struct subtitle_source *s)
{
    if (!InterlockedCompareExchange(&s->visible, 0, 0)) { detach_audio(s); return; }
    const char *uuid = s->audio_uuid;
    if (strcmp(uuid, CAPTION_PROGRAM_AUDIO) == 0) {
        obs_data_t *settings = obs_source_get_settings(s->source);
        size_t mix = caption_program_mix(settings);
        obs_data_release(settings);
        if (!s->program_capture || mix != s->program_mix) {
            detach_audio(s);
            s->program_mix = mix;
            obs_add_raw_audio_callback(mix, NULL, capture_program, s);
            s->program_capture = true;
        }
        s->audio_dirty = false;
        return;
    }
    if (s->program_capture) detach_audio(s);
    obs_source_t *target = *uuid ? obs_get_source_by_uuid(uuid) : NULL;
    if (s->audio_dirty) blog(LOG_DEBUG, "[Bilingue] Audio selection: configured=%d found=%d", *uuid != 0, target != NULL);
    obs_source_t *previous = s->audio_target ? obs_weak_source_get_source(s->audio_target) : NULL;
    if (target != previous) {
        detach_audio(s);
        if (target && target != s->source && obs_source_get_type(target) == OBS_SOURCE_TYPE_INPUT &&
            (obs_source_get_output_flags(target) & OBS_SOURCE_AUDIO)) {
            s->audio_target = obs_source_get_weak_source(target);
            obs_source_add_audio_capture_callback(target, capture_audio, s);
        }
    }
    if (previous) obs_source_release(previous);
    if (target) obs_source_release(target);
    s->audio_dirty = false;
}

static void update_source(void *data, obs_data_t *settings)
{
    struct subtitle_source *s = data;
    caption_rules_init(settings);
    caption_transport_update(s->transport, settings);
    caption_preview_update(s->preview, s->transport);
    snprintf(s->audio_uuid, sizeof(s->audio_uuid), "%s", obs_data_get_string(settings, "audio_source_uuid"));
    s->audio_dirty = true;
    long long width = obs_data_get_int(settings, "width");
    long long height = obs_data_get_int(settings, "height");
    s->width = width >= 320 && width <= 7680 ? (uint32_t)width : 1920;
    s->height = height >= 80 && height <= 4320 ? (uint32_t)height : 450;
    obs_data_t *browser_settings = obs_data_create();
    char url[128];
    snprintf(url, sizeof(url), "http://127.0.0.1:%u/overlay/original?connection=%lu",
             caption_http_port(), caption_connection_generation(s->transport));
    obs_data_set_string(browser_settings, "url", url);
    obs_data_set_int(browser_settings, "width", s->width);
    obs_data_set_int(browser_settings, "height", s->height);
    obs_data_set_int(browser_settings, "fps", 30);
    obs_data_set_bool(browser_settings, "shutdown", true);
    obs_data_set_bool(browser_settings, "restart_when_active", false);
    if (s->browser) {
        obs_source_update(s->browser, browser_settings);
    } else {
        s->browser = obs_source_create_private("browser_source", "Bilingue subtitle renderer", browser_settings);
        if (s->browser && !obs_source_add_active_child(s->source, s->browser)) {
            obs_source_release(s->browser);
            s->browser = NULL;
        }
    }
    obs_data_release(browser_settings);
}

static void *create_source(obs_data_t *settings, obs_source_t *source)
{
    struct subtitle_source *s = bzalloc(sizeof(*s));
    s->source = source;
    s->transport = caption_transport_create_inactive(settings, source);
    if (!s->transport) { bfree(s); return NULL; }
    if (!*obs_data_get_string(settings, "audio_source_uuid")) {
        obs_source_t *desktop = obs_get_output_source(1);
        if (desktop && (obs_source_get_output_flags(desktop) & OBS_SOURCE_AUDIO))
            obs_data_set_string(settings, "audio_source_uuid", obs_source_get_uuid(desktop));
        if (desktop) obs_source_release(desktop);
    }
    update_source(s, settings);
    if (!s->browser) blog(LOG_WARNING, "[Bilingue] Browser renderer unavailable; enable the OBS browser module");
    return s;
}

static void destroy_source(void *data)
{
    struct subtitle_source *s = data;
    blog(LOG_DEBUG, "[Bilingue] Releasing subtitle source");
    caption_transport_enable(s->transport, false);
    detach_audio(s);
    caption_transport_destroy(s->transport);
    if (s->browser) {
        obs_source_remove_active_child(s->source, s->browser);
        obs_source_release(s->browser);
    }
    caption_preview_close(s->preview, &s->preview_window);
    if (s->preview) obs_source_release(s->preview);
    bfree(s);
    blog(LOG_DEBUG, "[Bilingue] Subtitle source released");
}

static bool enumerate_audio(void *data, obs_source_t *source)
{
    if (obs_source_get_type(source) == OBS_SOURCE_TYPE_INPUT &&
        (obs_source_get_output_flags(source) & OBS_SOURCE_AUDIO))
        obs_property_list_add_string(data, obs_source_get_name(source), obs_source_get_uuid(source));
    return true;
}

static bool preview_clicked(obs_properties_t *props, obs_property_t *property, void *data)
{
    UNUSED_PARAMETER(props); UNUSED_PARAMETER(property);
    struct subtitle_source *s = data;
    if (s) caption_preview_open(&s->preview, &s->preview_window, s->transport);
    return false;
}

static obs_properties_t *source_properties(void *data)
{
    struct subtitle_source *s = data;
    obs_properties_t *props = obs_properties_create();
    obs_property_t *list = obs_properties_add_list(props, "audio_source_uuid", "Audio que se va a subtitular",
                                                  OBS_COMBO_TYPE_LIST, OBS_COMBO_FORMAT_STRING);
    obs_property_list_add_string(list, "Selecciona una fuente de audio o multimedia", "");
    obs_property_list_add_string(list, "Mezcla del directo de OBS (escenas, microfono y escritorio)", CAPTION_PROGRAM_AUDIO);
    obs_enum_sources(enumerate_audio, list);
    obs_properties_add_int(props, "obs_mix_track", "Pista de mezcla OBS (0 = automatica; 1-6 = fija)", 0, 6, 1);
    caption_add_properties(props);
    obs_properties_remove_by_name(props, "audio_port");
    obs_properties_remove_by_name(props, "overlays");
    obs_properties_remove_by_name(props, "show_original");
    obs_properties_remove_by_name(props, "color_rules");
    obs_data_t *settings = s ? obs_source_get_settings(s->source) : obs_data_create();
    if (!s) caption_defaults(settings);
    caption_rules_properties(props, settings, s ? s->source : NULL);
    obs_data_release(settings);
    obs_properties_add_button2(props, "preview_styles", "Vista previa de colores y estilo", preview_clicked, s);
    obs_properties_add_int(props, "width", "Ancho del area de subtitulos", 320, 7680, 10);
    obs_properties_add_int(props, "height", "Alto del area de subtitulos", 80, 4320, 10);
    return props;
}

static void source_defaults(obs_data_t *settings)
{
    caption_defaults(settings);
    obs_data_set_default_string(settings, "audio_source_uuid", CAPTION_PROGRAM_AUDIO);
    obs_data_set_default_int(settings, "obs_mix_track", 0);
    obs_data_set_default_int(settings, "width", 1920);
    obs_data_set_default_int(settings, "height", 450);
}

static void render_source(void *data, gs_effect_t *effect)
{
    UNUSED_PARAMETER(effect);
    struct subtitle_source *s = data;
    if (s->browser) obs_source_video_render(s->browser);
}

static void show_source(void *data)
{
    struct subtitle_source *s = data;
    InterlockedExchange(&s->visible, 1);
    caption_transport_enable(s->transport, true);
}

static void hide_source(void *data)
{
    struct subtitle_source *s = data;
    InterlockedExchange(&s->visible, 0);
    caption_transport_enable(s->transport, false);
}

static void tick_source(void *data, float seconds)
{
    UNUSED_PARAMETER(seconds);
    struct subtitle_source *s = data;
    bool visible = InterlockedCompareExchange(&s->visible, 0, 0) != 0;
    caption_preview_tick(s->preview, &s->preview_window);
    if (!visible || s->audio_dirty || !s->audio_target || s->program_capture) sync_audio(s);
    unsigned long generation = caption_connection_generation(s->transport);
    if (visible && s->browser && generation != s->renderer_generation) {
        s->renderer_generation = generation;
        char url[128];
        snprintf(url, sizeof(url), "http://127.0.0.1:%u/overlay/original?connection=%lu", caption_http_port(), generation);
        obs_data_t *settings = obs_data_create();
        obs_data_set_string(settings, "url", url);
        obs_source_update(s->browser, settings);
        obs_data_release(settings);
    }
}

static void enum_children(void *data, obs_source_enum_proc_t callback, void *param)
{
    struct subtitle_source *s = data;
    if (s->browser) callback(s->source, s->browser, param);
}

static uint32_t source_width(void *data) { return ((struct subtitle_source *)data)->width; }
static uint32_t source_height(void *data) { return ((struct subtitle_source *)data)->height; }
static const char *source_name(void *unused)
{
    UNUSED_PARAMETER(unused);
    return "Bilingue - Subtitulos de voz en directo";
}

void caption_register_source(void)
{
    struct obs_source_info info = {0};
    info.id = "obs_bilingue_source";
    info.type = OBS_SOURCE_TYPE_INPUT;
    info.output_flags = OBS_SOURCE_VIDEO | OBS_SOURCE_CUSTOM_DRAW;
    info.get_name = source_name;
    info.create = create_source;
    info.destroy = destroy_source;
    info.update = update_source;
    info.load = update_source;
    info.get_defaults = source_defaults;
    info.get_properties = source_properties;
    info.get_width = source_width;
    info.get_height = source_height;
    info.video_render = render_source;
    info.video_tick = tick_source;
    info.show = show_source;
    info.hide = hide_source;
    info.enum_active_sources = enum_children;
    info.icon_type = OBS_ICON_TYPE_TEXT;
    obs_register_source(&info);
}
