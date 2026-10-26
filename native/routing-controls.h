/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include <obs-module.h>

struct caption_controls;
struct caption_controls *caption_controls_create(obs_source_t *source, obs_data_t *settings);
void caption_controls_enable(struct caption_controls *controls, bool enabled);
void caption_controls_tick(struct caption_controls *controls, float seconds);
void caption_controls_destroy(struct caption_controls *controls);
