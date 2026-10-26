/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include <obs-module.h>
struct caption_input;
void caption_input_initialize(void);
void caption_input_shutdown(void);
struct caption_input *caption_input_create(void *transport, obs_source_t *source);
void caption_input_tick(struct caption_input *input);
void caption_input_destroy(struct caption_input *input);
const char *caption_input_help(obs_source_t *source);
