/* SPDX-License-Identifier: GPL-2.0-or-later */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "caption-transport.h"

static char *encode_url(const char *text, bool path)
{
    size_t length = strlen(text);
    char *encoded = bmalloc(length * 3 + 1), *out = encoded;
    static const char hex[] = "0123456789ABCDEF";
    for (size_t i = 0; i < length; i++) {
        unsigned char c = (unsigned char)text[i];
        if (path && c == '\\') c = '/';
        bool safe = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                    (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~' ||
                    (path && (c == '/' || c == ':'));
        if (safe) *out++ = (char)c;
        else { *out++ = '%'; *out++ = hex[c >> 4]; *out++ = hex[c & 15]; }
    }
    *out = 0;
    return encoded;
}

void caption_preview_update(obs_source_t *preview, void *transport)
{
    if (!preview) return;
    char *file = obs_module_file("preview.html");
    if (!file) return;
    char json[8193];
    caption_transport_config(transport, json, sizeof(json));
    char *path = encode_url(file, true), *fragment = encode_url(json, false);
    size_t size = strlen(path) + strlen(fragment) + 16;
    char *url = bmalloc(size);
    snprintf(url, size, "file:///%s#%s", path, fragment);
    obs_data_t *settings = obs_data_create();
    obs_data_set_string(settings, "url", url);
    obs_data_set_int(settings, "width", 960);
    obs_data_set_int(settings, "height", 600);
    obs_data_set_int(settings, "fps", 15);
    obs_data_set_bool(settings, "shutdown", true);
    obs_source_update(preview, settings);
    obs_data_release(settings);
    bfree(file); bfree(path); bfree(fragment); bfree(url);
}

static BOOL CALLBACK find_preview(HWND window, LPARAM data)
{
    DWORD pid = 0;
    GetWindowThreadProcessId(window, &pid);
    if (pid != GetCurrentProcessId() || !IsWindowVisible(window)) return TRUE;
    wchar_t title[512];
    GetWindowTextW(window, title, 512);
    if (!wcsstr(title, L"Vista previa de subtítulos (solo ejemplo)")) return TRUE;
    *(HWND *)data = window;
    return FALSE;
}

void caption_preview_tick(obs_source_t *preview, void **window)
{
    if (*window && (!IsWindow((HWND)*window) || !IsWindowVisible((HWND)*window))) {
        obs_source_dec_showing(preview);
        *window = NULL;
    }
}

void caption_preview_close(obs_source_t *preview, void **window)
{
    if (*window) {
        PostMessageW((HWND)*window, WM_CLOSE, 0, 0);
        obs_source_dec_showing(preview);
        *window = NULL;
    }
}

void caption_preview_open(obs_source_t **preview, void **window, void *transport)
{
    HMODULE frontend = GetModuleHandleW(L"obs-frontend-api.dll");
    if (!frontend) return;
    typedef void *(*open_interaction_fn)(obs_source_t *);
    FARPROC procedure = GetProcAddress(frontend, "obs_frontend_open_source_interaction");
    open_interaction_fn open_interaction;
    memcpy(&open_interaction, &procedure, sizeof(open_interaction));
    if (!open_interaction) return;
    if (!*preview) {
        obs_data_t *settings = obs_data_create();
        obs_data_set_string(settings, "url", "about:blank");
        obs_data_set_bool(settings, "shutdown", true);
        *preview = obs_source_create_private("browser_source", "Vista previa de subtítulos (solo ejemplo)", settings);
        obs_data_release(settings);
    }
    if (*preview) {
        caption_preview_tick(*preview, window);
        bool showing = *window != NULL;
        if (!showing) obs_source_inc_showing(*preview);
        caption_preview_update(*preview, transport);
        open_interaction(*preview);
        if (!showing) {
            HWND interaction = NULL;
            EnumWindows(find_preview, (LPARAM)&interaction);
            *window = interaction;
            if (!interaction) obs_source_dec_showing(*preview);
        }
    }
}
