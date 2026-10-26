/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <string.h>
#include <util/windows/window-helpers.h>
#include <objbase.h>
#include "caption-transport.h"
#include "source-audio.h"

struct caption_input {
    void *transport;
    obs_weak_source_t *target;
    obs_source_t *listening, *proxy;
    char window[8192];
};
static CO_MTA_USAGE_COOKIE caption_mta;

void caption_input_initialize(void)
{
    if (FAILED(CoIncrementMTAUsage(&caption_mta))) caption_mta = NULL;
}

void caption_input_shutdown(void)
{
    if (caption_mta) { CoDecrementMTAUsage(caption_mta); caption_mta = NULL; }
}

static bool window_source(obs_source_t *source)
{
    const char *id = obs_source_get_id(source);
    return !strcmp(id, "window_capture") || !strcmp(id, "game_capture");
}

static void input_audio(void *data, obs_source_t *source, const struct audio_data *audio, bool muted)
{
    UNUSED_PARAMETER(source);
    struct caption_input *input = data;
    obs_source_t *target = obs_weak_source_get_source(input->target);
    bool silent = !target || obs_source_removed(target) || obs_source_muted(target) ||
                  (input->proxy && !obs_source_showing(target));
    caption_capture(input->transport, audio->data, audio->frames, muted || silent);
    if (target) obs_source_release(target);
}

static void disconnect_input(struct caption_input *input)
{
    if (input->listening) {
        obs_source_remove_audio_capture_callback(input->listening, input_audio, input);
        obs_source_release(input->listening);
        input->listening = NULL;
    }
    if (input->proxy) {
        obs_source_dec_active(input->proxy);
        obs_source_release(input->proxy);
        input->proxy = NULL;
    }
    input->window[0] = 0;
}

static bool append_field(char **cursor, size_t *remaining, const char *value)
{
    if (!value) value = "";
    for (; *value; value++) {
        const char *escaped = *value == '#' ? "#22" : (*value == ':' ? "#3A" : NULL);
        size_t length = escaped ? 3 : 1;
        if (*remaining <= length) return false;
        memcpy(*cursor, escaped ? escaped : value, length);
        *cursor += length;
        *remaining -= length;
    }
    **cursor = 0;
    return true;
}

static bool captured_window(obs_source_t *source, char *buffer, size_t size)
{
    if (!obs_source_showing(source) || obs_source_removed(source)) return false;
    calldata_t data = {0};
    bool ok = proc_handler_call(obs_source_get_proc_handler(source), "get_hooked", &data) &&
              calldata_bool(&data, "hooked");
    const char *exe = calldata_string(&data, "executable");
    if (!exe || !*exe) ok = false;
    if (ok) {
        const char *names[] = {"title", "class", "executable"};
        char *cursor = buffer;
        size_t remaining = size;
        for (size_t i = 0; i < 3 && ok; i++) {
            ok = append_field(&cursor, &remaining, calldata_string(&data, names[i]));
            if (i < 2 && ok) {
                if (remaining < 2) ok = false;
                else { *cursor++ = ':'; remaining--; *cursor = 0; }
            }
        }
    }
    calldata_free(&data);
    return ok;
}

void caption_input_tick(struct caption_input *input)
{
    obs_source_t *target = obs_weak_source_get_source(input->target);
    if (!target || obs_source_removed(target)) {
        disconnect_input(input);
        if (target) obs_source_release(target);
        return;
    }
    obs_data_t *settings = obs_source_get_settings(target);
    bool private_window = window_source(target) && !obs_data_get_bool(settings, "capture_audio");
    obs_data_release(settings);
    if (!private_window) {
        if (input->proxy || input->listening != target) {
            disconnect_input(input);
            caption_transport_discontinuity(input->transport);
            input->listening = obs_source_get_ref(target);
            obs_source_add_audio_capture_callback(target, input_audio, input);
        }
    } else {
        char window[sizeof(input->window)] = {0};
        bool resolved = captured_window(target, window, sizeof(window));
        const char *type = obs_get_latest_input_type_id("wasapi_process_output_capture");
        if (!resolved || !type || !caption_mta) {
            disconnect_input(input); /* Never substitute a desktop/global capture. */
        } else if (!input->proxy || strcmp(input->window, window)) {
            disconnect_input(input);
            caption_transport_discontinuity(input->transport);
            obs_data_t *options = obs_data_create();
            obs_data_set_string(options, "window", window);
            obs_data_set_int(options, "priority", WINDOW_PRIORITY_TITLE);
            input->proxy = obs_source_create_private(type, "Bilingue isolated application audio", options);
            obs_data_release(options);
            if (input->proxy && obs_obj_get_data(input->proxy)) {
                /* A private source is not an output root. Also disable every
                 * mixer and monitoring explicitly: caption-only, never audible. */
                obs_source_set_audio_mixers(input->proxy, 0);
                obs_source_set_monitoring_type(input->proxy, OBS_MONITORING_TYPE_NONE);
                memcpy(input->window, window, sizeof(window));
                input->listening = obs_source_get_ref(input->proxy);
                obs_source_add_audio_capture_callback(input->proxy, input_audio, input);
                obs_source_inc_active(input->proxy);
            } else if (input->proxy) {
                obs_source_release(input->proxy);
                input->proxy = NULL;
            }
        }
    }
    obs_source_release(target);
}

struct caption_input *caption_input_create(void *transport, obs_source_t *source)
{
    struct caption_input *input = bzalloc(sizeof(*input));
    input->transport = transport;
    input->target = obs_source_get_weak_source(source);
    caption_input_tick(input);
    return input;
}

void caption_input_destroy(struct caption_input *input)
{
    disconnect_input(input);
    obs_weak_source_release(input->target);
    bfree(input);
}

const char *caption_input_help(obs_source_t *source)
{
    if (!source) return NULL;
    if (window_source(source))
        return "Subtitula la aplicacion de esta ventana, sin agregar sonido al directo. "
               "Varias ventanas del mismo proceso pueden compartir audio.";
    if (!strcmp(obs_source_get_id(source), "browser_source")) {
        obs_data_t *settings = obs_source_get_settings(source);
        bool enabled = obs_data_get_bool(settings, "reroute_audio");
        obs_data_release(settings);
        if (!enabled) return "Esta fuente Navegador no entrega audio a OBS. En sus propiedades activa "
                             "Controlar el audio a traves de OBS para obtener solo su audio. "
                             "No se usara el escritorio como sustituto.";
    }
    return NULL;
}
