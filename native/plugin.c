/* SPDX-License-Identifier: GPL-2.0-or-later */
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shellapi.h>
#include <obs-module.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include "caption-transport.h"
#include "language-rules.h"

OBS_DECLARE_MODULE()
OBS_MODULE_AUTHOR("OBS Bilingue")

/* Single producer (OBS audio callback), single consumer (network thread).
 * Fixed allocation. Never allocate, connect or wait in filter_audio. */
#define SLOTS 8
#define MAX_FRAMES 2048
struct packet {
    uint32_t rate, count, sequence, flags;
    float samples[MAX_FRAMES];
};
struct filter {
    obs_source_t *source;
    HANDLE thread;
    volatile LONG stop, enabled, read_index, write_index, port, generation;
    uint32_t sequence, rate;
    size_t channels;
    SRWLOCK config_lock;
    volatile LONG config_revision;
    char config_json[8193];
    struct packet queue[SLOTS];
};

static bool send_all(SOCKET sock, const void *buffer, size_t size)
{
    const char *cursor = buffer;
    while (size) {
        int sent = send(sock, cursor, (int)size, 0);
        if (sent <= 0) return false;
        cursor += sent;
        size -= (size_t)sent;
    }
    return true;
}

static DWORD WINAPI network_thread(void *opaque)
{
    struct filter *f = opaque;
    SOCKET sock = INVALID_SOCKET;
    LONG connected_port = 0;
    LONG config_sent = -1;
    uint64_t retry_at = 0, launch_at = 0, heartbeat_at = 0;
    while (!InterlockedCompareExchange(&f->stop, 0, 0)) {
        if (!InterlockedCompareExchange(&f->enabled, 0, 0)) {
            if (sock != INVALID_SOCKET) { closesocket(sock); sock = INVALID_SOCKET; }
            InterlockedExchange(&f->read_index, InterlockedCompareExchange(&f->write_index, 0, 0));
            Sleep(20);
            continue;
        }
        LONG port = InterlockedCompareExchange(&f->port, 0, 0);
        if (sock != INVALID_SOCKET && port != connected_port) {
            closesocket(sock);
            sock = INVALID_SOCKET;
        }
        if (sock == INVALID_SOCKET) {
            /* Discard audio while offline instead of replaying stale speech. */
            InterlockedExchange(&f->read_index, InterlockedCompareExchange(&f->write_index, 0, 0));
            if (GetTickCount64() < retry_at) { Sleep(10); continue; }
            retry_at = GetTickCount64() + 1000;
            sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
            if (sock == INVALID_SOCKET) continue;
            DWORD timeout = 250;
            BOOL no_delay = TRUE;
            setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, (const char *)&timeout, sizeof(timeout));
            setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, (const char *)&no_delay, sizeof(no_delay));
            struct sockaddr_in address = {0};
            address.sin_family = AF_INET;
            address.sin_port = htons((u_short)port);
            address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            if (connect(sock, (struct sockaddr *)&address, sizeof(address)) == SOCKET_ERROR) {
                closesocket(sock);
                sock = INVALID_SOCKET;
                if (GetTickCount64() >= launch_at) {
                    launch_at = GetTickCount64() + 5000;
                    caption_start_engine();
                }
                continue;
            }
            connected_port = port;
            config_sent = -1;
            InterlockedIncrement(&f->generation);
        }
        LONG revision = InterlockedCompareExchange(&f->config_revision, 0, 0);
        if (revision != config_sent) {
            char json[8193];
            AcquireSRWLockShared(&f->config_lock);
            memcpy(json, f->config_json, sizeof(json));
            ReleaseSRWLockShared(&f->config_lock);
            uint32_t length = (uint32_t)strlen(json);
            uint32_t control[5] = {0x46434c42, 0, length, 0, 0};
            if (!send_all(sock, control, sizeof(control)) || !send_all(sock, json, length)) {
                closesocket(sock); sock = INVALID_SOCKET; continue;
            }
            config_sent = revision;
        }
        LONG r = InterlockedCompareExchange(&f->read_index, 0, 0);
        LONG w = InterlockedCompareExchange(&f->write_index, 0, 0);
        if (r == w) {
            if (GetTickCount64() >= heartbeat_at) {
                uint32_t heartbeat[5] = {0x50434c42, 0, 0, 0, 0};
                if (!send_all(sock, heartbeat, sizeof(heartbeat))) {
                    closesocket(sock); sock = INVALID_SOCKET;
                }
                heartbeat_at = GetTickCount64() + 1000;
            }
            Sleep(5);
            continue;
        }
        struct packet *p = &f->queue[(uint32_t)r % SLOTS];
        uint32_t header[5] = {0x31434c42, p->rate, p->count, p->sequence, p->flags};
        bool ok = send_all(sock, header, sizeof(header)) &&
                  send_all(sock, p->samples, p->count * sizeof(float));
        InterlockedExchange(&f->read_index, (LONG)((uint32_t)r + 1));
        if (!ok) { closesocket(sock); sock = INVALID_SOCKET; }
    }
    if (sock != INVALID_SOCKET) closesocket(sock);
    return 0;
}

void caption_capture(void *opaque, uint8_t *const planes[MAX_AV_PLANES], uint32_t frames, bool muted)
{
    struct filter *f = opaque;
    if (!InterlockedCompareExchange(&f->enabled, 0, 0)) return;
    struct obs_audio_info current_info;
    if (obs_get_audio_info(&current_info)) {
        f->rate = current_info.samples_per_sec;
        f->channels = get_audio_channels(current_info.speakers);
    }
    for (uint32_t offset = 0; offset < frames;) {
        uint32_t sequence = f->sequence++;
        LONG w = InterlockedCompareExchange(&f->write_index, 0, 0);
        LONG r = InterlockedCompareExchange(&f->read_index, 0, 0);
        if ((uint32_t)(w - r) >= SLOTS) return;
        uint32_t count = frames - offset;
        if (count > MAX_FRAMES) count = MAX_FRAMES;
        struct packet *p = &f->queue[(uint32_t)w % SLOTS];
        p->rate = f->rate;
        p->count = count;
        p->sequence = sequence;
        p->flags = muted ? 1 : 0;
        memset(p->samples, 0, count * sizeof(float));
        if (!muted) {
            size_t channels = 0;
            /* Resampled media may exceed one slot; retain every sample in chunks. */
            for (size_t ch = 0; ch < f->channels && ch < MAX_AV_PLANES; ch++) {
                if (!planes[ch]) continue;
                const float *input = (const float *)planes[ch] + offset;
                for (uint32_t i = 0; i < count; i++) p->samples[i] += input[i];
                channels++;
            }
            if (channels > 1) {
                float scale = 1.0f / (float)channels;
                for (uint32_t i = 0; i < count; i++) p->samples[i] *= scale;
            }
        }
        InterlockedExchange(&f->write_index, (LONG)((uint32_t)w + 1));
        offset += count;
    }
}

static struct obs_audio_data *filter_audio(void *opaque, struct obs_audio_data *audio)
{
    struct filter *f = opaque;
    obs_source_t *parent = obs_filter_get_parent(f->source);
    caption_capture(f, audio->data, audio->frames, parent && obs_source_muted(parent));
    return audio;
}

void caption_transport_update(void *opaque, obs_data_t *settings)
{
    struct filter *f = opaque;
    long long port = obs_data_get_int(settings, "audio_port");
    if (port < 1024 || port > 65535) port = caption_audio_port();
    InterlockedExchange(&f->port, (LONG)port);
    const char *rules = obs_data_get_string(settings, "color_rules");
    char interactive_rules[2049];
    if (obs_data_get_bool(settings, "interactive_colors")) {
        caption_rules_format(settings, interactive_rules, sizeof(interactive_rules));
        rules = interactive_rules;
    }
    if (strlen(rules) > 2048) rules = "";
    uint32_t color = (uint32_t)obs_data_get_int(settings, "default_color");
    char hex[8];
    snprintf(hex, sizeof(hex), "#%02X%02X%02X", color & 255, (color >> 8) & 255, (color >> 16) & 255);
    obs_data_t *config = obs_data_create();
    obs_data_set_string(config, "color_rules", rules);
    obs_data_set_string(config, "default_color", hex);
    obs_data_t *font = obs_data_get_obj(settings, "font");
    if (font) {
        obs_data_set_string(config, "font_face", obs_data_get_string(font, "face"));
        obs_data_set_int(config, "font_size", obs_data_get_int(font, "size"));
        obs_data_set_int(config, "font_flags", obs_data_get_int(font, "flags"));
        obs_data_release(font);
    }
    obs_data_t *translation_font = obs_data_get_obj(settings, "translation_font");
    if (translation_font) {
        obs_data_set_string(config, "translation_font_face", obs_data_get_string(translation_font, "face"));
        obs_data_set_int(config, "translation_font_size", obs_data_get_int(translation_font, "size"));
        obs_data_set_int(config, "translation_font_flags", obs_data_get_int(translation_font, "flags"));
        obs_data_release(translation_font);
    }
    uint32_t translation_color = (uint32_t)obs_data_get_int(settings, "translation_color");
    snprintf(hex, sizeof(hex), "#%02X%02X%02X", translation_color & 255,
             (translation_color >> 8) & 255, (translation_color >> 16) & 255);
    obs_data_set_string(config, "translation_color", hex);
    obs_data_set_bool(config, "translation_use_spanish_color", obs_data_get_bool(settings, "translation_use_spanish_color"));
    obs_data_set_bool(config, "translation_use_original_font", obs_data_get_bool(settings, "translation_use_original_font"));
    obs_data_set_bool(config, "translation_show_language_labels", obs_data_get_bool(settings, "translation_show_language_labels"));
    uint32_t background = (uint32_t)obs_data_get_int(settings, "background_color");
    snprintf(hex, sizeof(hex), "#%02X%02X%02X", background & 255,
             (background >> 8) & 255, (background >> 16) & 255);
    obs_data_set_string(config, "background_color", hex);
    obs_data_set_int(config, "background_opacity", obs_data_get_int(settings, "background_opacity"));
    obs_data_set_int(config, "duration_seconds", obs_data_get_int(settings, "duration_seconds"));
    obs_data_set_int(config, "max_rows", obs_data_get_int(settings, "max_rows"));
    obs_data_set_int(config, "max_lines_per_language", obs_data_get_int(settings, "max_lines_per_language"));
    obs_data_set_bool(config, "stack", obs_data_get_bool(settings, "stack"));
    obs_data_set_bool(config, "show_original", obs_data_get_bool(settings, "show_original"));
    obs_data_set_bool(config, "translation_enabled", obs_data_get_bool(settings, "translation_enabled"));
    AcquireSRWLockExclusive(&f->config_lock);
    const char *json = obs_data_get_json(config);
    snprintf(f->config_json, sizeof(f->config_json), "%s", json);
    ReleaseSRWLockExclusive(&f->config_lock);
    obs_data_release(config);
    InterlockedIncrement(&f->config_revision);
}

static void *create_transport(obs_data_t *settings, obs_source_t *source, bool enabled)
{
    struct filter *f = bzalloc(sizeof(*f));
    f->source = source;
    f->enabled = enabled;
    InitializeSRWLock(&f->config_lock);
    struct obs_audio_info info;
    if (!obs_get_audio_info(&info)) { bfree(f); return NULL; }
    f->rate = info.samples_per_sec;
    f->channels = get_audio_channels(info.speakers);
    caption_transport_update(f, settings);
    f->thread = CreateThread(NULL, 0, network_thread, f, 0, NULL);
    if (!f->thread) { bfree(f); return NULL; }
    return f;
}

void *caption_transport_create(obs_data_t *settings, obs_source_t *source)
{ return create_transport(settings, source, true); }

void *caption_transport_create_inactive(obs_data_t *settings, obs_source_t *source)
{ return create_transport(settings, source, false); }

void caption_transport_enable(void *opaque, bool enabled)
{
    struct filter *f = opaque;
    InterlockedExchange(&f->enabled, enabled);
}

unsigned long caption_connection_generation(void *opaque)
{
    struct filter *f = opaque;
    return (unsigned long)InterlockedCompareExchange(&f->generation, 0, 0);
}

void caption_transport_config(void *opaque, char *buffer, size_t size)
{
    struct filter *f = opaque;
    AcquireSRWLockShared(&f->config_lock);
    snprintf(buffer, size, "%s", f->config_json);
    ReleaseSRWLockShared(&f->config_lock);
}

void caption_transport_destroy(void *opaque)
{
    struct filter *f = opaque;
    InterlockedExchange(&f->stop, 1);
    WaitForSingleObject(f->thread, INFINITE);
    CloseHandle(f->thread);
    SecureZeroMemory(f->queue, sizeof(f->queue));
    bfree(f);
}

static bool open_control(obs_properties_t *props, obs_property_t *property, void *data)
{
    UNUSED_PARAMETER(props); UNUSED_PARAMETER(property); UNUSED_PARAMETER(data);
    char url[64];
    snprintf(url, sizeof(url), "http://127.0.0.1:%u/", caption_http_port());
    ShellExecuteA(NULL, "open", url, NULL, NULL, SW_SHOWNORMAL);
    return true;
}

static void add_overlay(obs_scene_t *scene, const char *name, const char *language,
                        uint32_t width, uint32_t height, float y)
{
    if (obs_scene_find_source(scene, name)) return;
    obs_source_t *browser = obs_get_source_by_name(name);
    if (!browser) {
        obs_data_t *settings = obs_data_create();
        char url[128];
    snprintf(url, sizeof(url), "http://127.0.0.1:%u/overlay/%s", caption_http_port(), language);
        obs_data_set_string(settings, "url", url);
        obs_data_set_int(settings, "width", width);
        obs_data_set_int(settings, "height", height);
        obs_data_set_int(settings, "fps", 15);
        obs_data_set_bool(settings, "shutdown", true);
        obs_data_set_bool(settings, "restart_when_active", true);
        browser = obs_source_create("browser_source", name, settings, NULL);
        obs_data_release(settings);
    }
    if (browser) {
        obs_sceneitem_t *item = obs_scene_add(scene, browser);
        struct vec2 position = {0};
        position.y = y;
        if (item) obs_sceneitem_set_pos(item, &position);
        obs_source_release(browser);
    }
}

static bool create_overlays(obs_properties_t *props, obs_property_t *property, void *data)
{
    UNUSED_PARAMETER(props); UNUSED_PARAMETER(property); UNUSED_PARAMETER(data);
    /* Resolve frontend API at runtime: no Qt dependency, no frontend in tests. */
    HMODULE frontend = GetModuleHandleW(L"obs-frontend-api.dll");
    if (!frontend) return false;
    typedef obs_source_t *(*get_scene_fn)(void);
    FARPROC procedure = GetProcAddress(frontend, "obs_frontend_get_current_scene");
    get_scene_fn get_scene;
    memcpy(&get_scene, &procedure, sizeof(get_scene));
    if (!get_scene) return false;
    obs_source_t *source = get_scene();
    if (!source) return false;
    obs_scene_t *scene = obs_scene_from_source(source);
    if (scene) {
        struct obs_video_info video;
        bool have_video = obs_get_video_info(&video);
        uint32_t width = have_video ? video.base_width : 1920;
        uint32_t height = have_video ? video.base_height : 1080;
        uint32_t panel_height = height / 2 < 450 ? height / 2 : 450;
        add_overlay(scene, "Bilingue ES", "es", width, panel_height, (float)(height - panel_height * 2));
        add_overlay(scene, "Bilingue EN", "en", width, panel_height, (float)(height - panel_height));
    }
    obs_source_release(source);
    return true;
}

static bool translation_style_changed(obs_properties_t *p, obs_property_t *property, obs_data_t *settings)
{
    UNUSED_PARAMETER(property);
    obs_property_set_enabled(obs_properties_get(p, "translation_color"),
                             !obs_data_get_bool(settings, "translation_use_spanish_color"));
    obs_property_set_enabled(obs_properties_get(p, "translation_font"),
                             !obs_data_get_bool(settings, "translation_use_original_font"));
    return true;
}

void caption_add_properties(obs_properties_t *p)
{
    obs_properties_add_text(p, "help", "Se activa al mostrar la fuente y se pausa al ocultarla.\n"
        "Subtitulos en el idioma hablado; deteccion automatica y colores por idioma.\n"
        "La traduccion al espanol es opcional.", OBS_TEXT_INFO);
    obs_properties_add_int(p, "audio_port", "Puerto local de audio", 1024, 65535, 1);
    obs_properties_add_color(p, "default_color", "Color predeterminado (idioma desconocido o sin regla)");
    obs_properties_add_font(p, "font", "Fuente, estilo y tamano de letra");
    obs_properties_add_color(p, "background_color", "Color de fondo");
    obs_properties_add_int_slider(p, "background_opacity", "Opacidad del fondo (%)", 0, 100, 1);
    obs_properties_add_int_slider(p, "duration_seconds", "Duracion en pantalla (segundos)", 1, 60, 1);
    obs_properties_add_bool(p, "stack", "Apilar subtitulos (cola: sale primero el mas antiguo)");
    obs_properties_add_int_slider(p, "max_rows", "Maximo de subtitulos apilados", 1, 8, 1);
    obs_properties_add_int_slider(p, "max_lines_per_language", "Maximo de lineas por idioma (muestra el texto reciente)", 1, 6, 1);
    obs_properties_add_bool(p, "show_original", "Mostrar texto original parcial bajo la traduccion");
    obs_properties_add_bool(p, "translation_enabled", "Anadir traduccion al espanol (opcional; carga el modelo en GPU)");
    obs_property_t *shared_color = obs_properties_add_bool(p, "translation_use_spanish_color", "Traduccion: usar el color del idioma espanol");
    obs_property_set_modified_callback(shared_color, translation_style_changed);
    obs_properties_add_color(p, "translation_color", "Traduccion: color independiente");
    obs_property_t *shared_font = obs_properties_add_bool(p, "translation_use_original_font", "Traduccion: usar la misma fuente y tamano del original");
    obs_property_set_modified_callback(shared_font, translation_style_changed);
    obs_properties_add_font(p, "translation_font", "Traduccion: fuente, estilo y tamano independientes");
    obs_properties_add_bool(p, "translation_show_language_labels", "Traduccion: mostrar etiquetas de idioma en ambas lineas");
    obs_properties_add_text(p, "color_rules", "Colores por idioma hablado: codigo=#RRGGBB, una regla por linea",
                            OBS_TEXT_MULTILINE);
    obs_properties_add_button2(p, "control", "Abrir panel de estado", open_control, NULL);
    obs_properties_add_button2(p, "overlays", "Crear subtitulos ES y EN en la escena", create_overlays, NULL);
}

obs_properties_t *caption_properties(void *data)
{
    UNUSED_PARAMETER(data);
    obs_properties_t *p = obs_properties_create();
    caption_add_properties(p);
    return p;
}

static const char *name(void *unused)
{
    UNUSED_PARAMETER(unused);
    return "Bilingue - Traduccion local en directo";
}

void caption_defaults(obs_data_t *settings)
{
    obs_data_set_default_int(settings, "audio_port", caption_audio_port());
    obs_data_set_default_int(settings, "default_color", 0xFFFFFF);
    obs_data_set_default_string(settings, "color_rules", "en=#7CC7FF\nes=#FFD166");
    obs_data_t *font = obs_data_create();
    obs_data_set_string(font, "face", "Segoe UI");
    obs_data_set_int(font, "size", 40);
    obs_data_set_int(font, "flags", 0);
    obs_data_set_default_obj(settings, "font", font);
    obs_data_release(font);
    obs_data_t *translation_font = obs_data_create();
    obs_data_set_string(translation_font, "face", "Segoe UI");
    obs_data_set_int(translation_font, "size", 30);
    obs_data_set_int(translation_font, "flags", 0);
    obs_data_set_default_obj(settings, "translation_font", translation_font);
    obs_data_release(translation_font);
    obs_data_set_default_int(settings, "background_color", 0x1B1510);
    obs_data_set_default_int(settings, "background_opacity", 78);
    obs_data_set_default_int(settings, "duration_seconds", 8);
    obs_data_set_default_int(settings, "max_rows", 3);
    obs_data_set_default_int(settings, "max_lines_per_language", 2);
    obs_data_set_default_bool(settings, "stack", true);
    obs_data_set_default_bool(settings, "show_original", true);
    obs_data_set_default_bool(settings, "translation_enabled", false);
    obs_data_set_default_bool(settings, "translation_use_spanish_color", true);
    obs_data_set_default_bool(settings, "translation_use_original_font", false);
    obs_data_set_default_bool(settings, "translation_show_language_labels", true);
    obs_data_set_default_int(settings, "translation_color", 0x66D1FF);
}

MODULE_EXPORT const char *obs_module_name(void) { return "OBS Bilingue"; }
MODULE_EXPORT const char *obs_module_description(void) { return "Subtitulos multilingues locales con memoria acotada"; }
MODULE_EXPORT bool obs_module_load(void)
{
    caption_load_engine_config();
    WSADATA data;
    if (WSAStartup(MAKEWORD(2, 2), &data)) return false;
    struct obs_source_info info = {0};
    info.id = "obs_bilingue_filter";
    info.type = OBS_SOURCE_TYPE_FILTER;
    info.output_flags = OBS_SOURCE_AUDIO;
    info.get_name = name;
    info.create = caption_transport_create;
    info.destroy = caption_transport_destroy;
    info.update = caption_transport_update;
    info.get_defaults = caption_defaults;
    info.get_properties = caption_properties;
    info.filter_audio = filter_audio;
    obs_register_source(&info);
    caption_register_source();
    blog(LOG_INFO, "[Bilingue] Loaded 0.4.0; local captions; automatic visibility lifecycle");
    return true;
}
MODULE_EXPORT void obs_module_unload(void) { WSACleanup(); }
