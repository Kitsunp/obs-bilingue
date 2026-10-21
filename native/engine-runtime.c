/* SPDX-License-Identifier: GPL-2.0-or-later */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <wchar.h>
#include <string.h>
#include "caption-transport.h"

/* Compatibility defaults when local installation metadata is unavailable. */
static unsigned http_port = 17863, audio_port = 17864;
unsigned caption_http_port(void) { return http_port; }
unsigned caption_audio_port(void) { return audio_port; }

void caption_load_engine_config(void)
{
    char *runtime_path = obs_module_file("runtime.json");
    if (!runtime_path) return;
    FILE *file = fopen(runtime_path, "rb");
    bfree(runtime_path);
    if (!file) return;
    char json[16385] = {0};
    size_t count = fread(json, 1, sizeof(json) - 1, file);
    bool oversized = fgetc(file) != EOF;
    fclose(file);
    if (!count || oversized) return;
    obs_data_t *runtime = obs_data_create_from_json(json);
    if (!runtime) return;
    WCHAR config_path[32768], root[32768];
    bool valid = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS,
        obs_data_get_string(runtime, "root"), -1, root, 32768) > 0;
    obs_data_release(runtime);
    if (!valid || !*root) return;
    int length = swprintf(config_path, 32768, L"%ls\\config.json", root);
    if (length < 0 || length >= 32768) return;
    file = _wfopen(config_path, L"rb");
    if (!file) return;
    memset(json, 0, sizeof(json));
    count = fread(json, 1, sizeof(json) - 1, file);
    oversized = fgetc(file) != EOF;
    fclose(file);
    if (!count || oversized) return;
    obs_data_t *config = obs_data_create_from_json(json);
    if (!config) return;
    long long configured_http = obs_data_get_int(config, "http_port");
    long long configured_audio = obs_data_get_int(config, "audio_port");
    if (configured_http >= 1024 && configured_http <= 65535) http_port = (unsigned)configured_http;
    if (configured_audio >= 1024 && configured_audio <= 65535) audio_port = (unsigned)configured_audio;
    obs_data_release(config);
}

/* Called only by the network worker, never by OBS's UI or audio callback. */
void caption_start_engine(void)
{
    char *path = obs_module_file("runtime.json");
    if (!path) return;
    FILE *file = fopen(path, "rb");
    bfree(path);
    if (!file) return;
    char json[4097] = {0};
    size_t count = fread(json, 1, sizeof(json) - 1, file);
    bool oversized = fgetc(file) != EOF;
    fclose(file);
    if (!count || oversized) return;
    obs_data_t *runtime = obs_data_create_from_json(json);
    if (!runtime) return;
    WCHAR python[32768], root[32768], command[32768];
    bool valid = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, obs_data_get_string(runtime, "python"),
                                     -1, python, 32768) > 0 &&
                 MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, obs_data_get_string(runtime, "root"),
                                     -1, root, 32768) > 0;
    obs_data_release(runtime);
    if (!valid || GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES) return;
    int length = swprintf(command, 32768, L"\"%ls\" -B -m engine.launch", python);
    if (length < 0 || length >= 32768) return;
    STARTUPINFOW startup = {0};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESHOWWINDOW;
    startup.wShowWindow = SW_HIDE;
    PROCESS_INFORMATION process = {0};
    if (CreateProcessW(python, command, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, root, &startup, &process)) {
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
    } else {
        blog(LOG_WARNING, "[Bilingue] Engine launch failed: Windows error %lu", GetLastError());
    }
}
