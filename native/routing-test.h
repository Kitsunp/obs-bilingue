/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include <obs-module.h>
struct routing_test;
struct routing_test *routing_test_create(const char *mode, obs_source_t *media);
void routing_test_settings(struct routing_test *test, obs_data_t *settings);
bool routing_test_attach(struct routing_test *test, obs_source_t *caption);
bool routing_test_tick(struct routing_test *test, uint64_t elapsed);
void routing_test_destroy(struct routing_test *test);
