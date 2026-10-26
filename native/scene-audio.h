/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include <obs-module.h>

void caption_register_scene_audio(void);
obs_source_t *caption_scene_audio_create(void *transport, obs_source_t *scene, size_t mix);
void caption_scene_audio_refresh(obs_source_t *tap);
void caption_scene_audio_destroy(obs_source_t *tap);
