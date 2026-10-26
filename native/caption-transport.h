/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include <obs-module.h>

void *caption_transport_create(obs_data_t *settings, obs_source_t *source);
void *caption_transport_create_inactive(obs_data_t *settings, obs_source_t *source);
void caption_transport_enable(void *data, bool enabled);
void caption_transport_discontinuity(void *data);
unsigned long caption_connection_generation(void *data);
void caption_transport_config(void *data, char *buffer, size_t size);
void caption_start_engine(void);
void caption_load_engine_config(void);
unsigned caption_http_port(void);
unsigned caption_audio_port(void);
void caption_preview_update(obs_source_t *preview, void *transport);
void caption_preview_open(obs_source_t **preview, void **window, void *transport);
void caption_preview_tick(obs_source_t *preview, void **window);
void caption_preview_close(obs_source_t *preview, void **window);
void caption_transport_destroy(void *data);
void caption_transport_update(void *data, obs_data_t *settings);
void caption_capture(void *data, uint8_t *const planes[MAX_AV_PLANES], uint32_t frames, bool muted);
obs_properties_t *caption_properties(void *data);
void caption_add_properties(obs_properties_t *properties);
void caption_defaults(obs_data_t *settings);
void caption_register_source(void);
