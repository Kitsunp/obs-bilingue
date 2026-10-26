/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include <obs-module.h>
#include <windows.h>
obs_source_t *caption_choose_source(obs_source_t *owner, const char *preferred, HWND foreground);
bool caption_source_in_program(obs_source_t *owner, const char *uuid);
