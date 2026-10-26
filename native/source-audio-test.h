/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include <obs-module.h>
void source_audio_test_register(bool mock_process);
obs_source_t *source_audio_test_window(const char *window);
