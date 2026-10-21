/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include <obs-module.h>
#define CAPTION_MAX_RULES 64
void caption_rules_init(obs_data_t *settings);
void caption_rules_format(obs_data_t *settings, char *buffer, size_t size);
void caption_rules_properties(obs_properties_t *props, obs_data_t *settings, obs_source_t *source);
const char *caption_language_name(const char *code);
