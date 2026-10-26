/* SPDX-License-Identifier: GPL-2.0-or-later */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>
#include "program-audio.h"

size_t caption_program_mix(obs_data_t *settings)
{
    long long selected = obs_data_get_int(settings, "obs_mix_track");
    if (selected >= 1 && selected <= MAX_AUDIO_MIXES) return (size_t)selected - 1;
    /* Read the primary output's track. Never start, stop or reconfigure it. */
    HMODULE frontend = GetModuleHandleW(L"obs-frontend-api.dll");
    if (frontend) {
        const char *functions[] = {"obs_frontend_get_streaming_output", "obs_frontend_get_recording_output"};
        for (size_t i = 0; i < 2; i++) {
            typedef obs_output_t *(*get_output_fn)(void);
            FARPROC address = GetProcAddress(frontend, functions[i]);
            get_output_fn get_output = NULL;
            memcpy(&get_output, &address, sizeof(get_output));
            obs_output_t *output = get_output ? get_output() : NULL;
            if (!output) continue;
            obs_encoder_t *encoder = obs_output_active(output) ? obs_output_get_audio_encoder(output, 0) : NULL;
            size_t mix = encoder ? obs_encoder_get_mixer_index(encoder) : MAX_AUDIO_MIXES;
            obs_output_release(output);
            if (mix < MAX_AUDIO_MIXES) return mix;
        }
    }
    return 0;
}
