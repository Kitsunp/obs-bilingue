/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "language-rules.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* Language families in the model's transcription-ready/broad-coverage tiers.
 * Regional variants share one colour; this never changes ASR's auto prompt. */
static const struct { const char *code, *name; } languages[] = {
    {"en", "Inglés"}, {"es", "Español"}, {"de", "Alemán"}, {"ar", "Árabe"},
    {"bg", "Búlgaro"}, {"cs", "Checo"}, {"zh", "Chino mandarín"}, {"ko", "Coreano"},
    {"hr", "Croata"}, {"da", "Danés"}, {"sk", "Eslovaco"}, {"et", "Estonio"},
    {"fi", "Finés"}, {"fr", "Francés"}, {"hi", "Hindi"}, {"nl", "Neerlandés"},
    {"hu", "Húngaro"}, {"it", "Italiano"}, {"ja", "Japonés"}, {"nb", "Noruego bokmål"},
    {"pl", "Polaco"}, {"pt", "Portugués"}, {"ro", "Rumano"}, {"ru", "Ruso"},
    {"sv", "Sueco"}, {"tr", "Turco"}, {"uk", "Ucraniano"}, {"vi", "Vietnamita"},
};

const char *caption_language_name(const char *code)
{
    for (size_t i = 0; i < sizeof(languages) / sizeof(languages[0]); i++)
        if (!strcmp(code, languages[i].code)) return languages[i].name;
    return code;
}

static int rule_count(obs_data_t *settings)
{
    long long count = obs_data_get_int(settings, "rule_count");
    return count >= 0 && count <= CAPTION_MAX_RULES ? (int)count : 0;
}

static const char *language_at(obs_data_t *settings, int index)
{
    char key[32];
    snprintf(key, sizeof(key), "rule_language_%d", index);
    return obs_data_get_string(settings, key);
}

static void set_rule(obs_data_t *settings, int index, const char *code, long long color)
{
    char key[32];
    snprintf(key, sizeof(key), "rule_language_%d", index);
    obs_data_set_string(settings, key, code);
    snprintf(key, sizeof(key), "rule_color_%d", index);
    obs_data_set_int(settings, key, color);
}

static long long color_at(obs_data_t *settings, int index)
{
    char key[32];
    snprintf(key, sizeof(key), "rule_color_%d", index);
    return obs_data_get_int(settings, key);
}

static bool used_elsewhere(obs_data_t *settings, const char *code, int except)
{
    for (int i = 0; i < rule_count(settings); i++)
        if (i != except && !strcmp(code, language_at(settings, i))) return true;
    return false;
}

void caption_rules_init(obs_data_t *settings)
{
    if (!obs_data_get_bool(settings, "interactive_colors")) {
        char text[2049];
        snprintf(text, sizeof(text), "%s", obs_data_get_string(settings, "color_rules"));
        char *line = text;
        int count = 0;
        while (line && *line && count < CAPTION_MAX_RULES) {
            char *next = strpbrk(line, "\n;");
            if (next) *next++ = 0;
            while (*line == ' ' || *line == '\t') line++;
            char *equal = strchr(line, '=');
            if (equal) {
                size_t length = strcspn(line, "-= \t");
                unsigned rgb;
                if ((length == 2 || length == 3) && sscanf(equal + 1, " #%6x", &rgb) == 1) {
                    char code[4] = {0};
                    memcpy(code, line, length);
                    set_rule(settings, count++, code,
                             ((rgb & 255) << 16) | (rgb & 0xFF00) | ((rgb >> 16) & 255));
                }
            }
            line = next;
        }
        obs_data_set_int(settings, "rule_count", count);
        obs_data_set_bool(settings, "interactive_colors", true);
    }
    /* Settings imported from files cannot bypass uniqueness. First rule wins. */
    for (int i = 0; i < rule_count(settings); i++)
        for (int j = 0; j < i; j++)
            if (*language_at(settings, i) && !strcmp(language_at(settings, i), language_at(settings, j)))
                set_rule(settings, i, "", color_at(settings, i));
}

void caption_rules_format(obs_data_t *settings, char *buffer, size_t size)
{
    buffer[0] = 0;
    size_t used = 0;
    for (int i = 0; i < rule_count(settings); i++) {
        const char *code = language_at(settings, i);
        size_t length = strlen(code);
        if (length < 2 || length > 3) continue;
        bool valid = true;
        for (size_t j = 0; j < length; j++) valid = valid && code[j] >= 'a' && code[j] <= 'z';
        if (!valid) continue;
        unsigned color = (unsigned)color_at(settings, i);
        int written = snprintf(buffer + used, size - used, "%s=#%02X%02X%02X\n", code,
                               color & 255, (color >> 8) & 255, (color >> 16) & 255);
        if (written < 0 || (size_t)written >= size - used) break;
        used += (size_t)written;
    }
}

static void fill_choices(obs_property_t *list, obs_data_t *settings, int index)
{
    obs_property_list_clear(list);
    obs_property_list_add_string(list, "Sin asignar", "");
    const char *selected = language_at(settings, index);
    bool found = !*selected;
    for (size_t i = 0; i < sizeof(languages) / sizeof(languages[0]); i++) {
        if (!strcmp(selected, languages[i].code)) found = true;
        if (!used_elsewhere(settings, languages[i].code, index))
            obs_property_list_add_string(list, languages[i].name, languages[i].code);
    }
    if (!found) obs_property_list_add_string(list, selected, selected);
}

/* Settings-backed actions keep OBS's editable copy and the visible controls in sync. */
static bool language_changed(obs_properties_t *props, obs_property_t *property, obs_data_t *settings)
{
    caption_rules_init(settings);
    const char *name = obs_property_name(property);
    int count = rule_count(settings), remove = -1;
    if (!strcmp(name, "add_language")) {
        char selected[8];
        snprintf(selected, sizeof(selected), "%s", obs_data_get_string(settings, "add_language"));
        if (*selected && count < CAPTION_MAX_RULES && !used_elsewhere(settings, selected, -1)) {
            set_rule(settings, count++, selected, 0xFFFFFF);
            obs_data_set_int(settings, "rule_count", count);
        }
        obs_data_set_string(settings, "add_language", "");
    } else if (sscanf(name, "remove_rule_%d", &remove) == 1 && obs_data_get_bool(settings, name)) {
        if (remove >= 0 && remove < count) {
            for (int i = remove; i + 1 < count; i++)
                set_rule(settings, i, language_at(settings, i + 1), color_at(settings, i + 1));
            set_rule(settings, --count, "", 0xFFFFFF);
            obs_data_set_int(settings, "rule_count", count);
        }
        obs_data_set_bool(settings, name, false);
    }
    obs_property_t *add = obs_properties_get(props, "add_language");
    obs_property_list_clear(add);
    obs_property_list_add_string(add, "Selecciona un idioma para añadir", "");
    int available = 0;
    for (size_t i = 0; i < sizeof(languages) / sizeof(languages[0]); i++) {
        if (used_elsewhere(settings, languages[i].code, -1)) continue;
        obs_property_list_add_string(add, languages[i].name, languages[i].code);
        available++;
    }
    obs_property_set_enabled(add, count < CAPTION_MAX_RULES && available > 0);
    for (int i = 0; i < CAPTION_MAX_RULES; i++) {
        char key[32], label[96];
        snprintf(key, sizeof(key), "rule_language_%d", i);
        obs_property_t *list = obs_properties_get(props, key);
        obs_property_set_visible(list, i < count);
        if (i < count) fill_choices(list, settings, i);
        snprintf(key, sizeof(key), "rule_color_%d", i);
        obs_property_t *color = obs_properties_get(props, key);
        obs_property_set_visible(color, i < count);
        if (i < count) {
            snprintf(label, sizeof(label), "Color de %s", caption_language_name(language_at(settings, i)));
            obs_property_set_description(color, label);
        }
        snprintf(key, sizeof(key), "remove_rule_%d", i);
        obs_property_set_visible(obs_properties_get(props, key), i < count);
    }
    return true;
}

void caption_rules_properties(obs_properties_t *props, obs_data_t *settings, obs_source_t *source)
{
    UNUSED_PARAMETER(source);
    caption_rules_init(settings);
    obs_properties_add_text(props, "colors_help",
        "Selecciona idiomas sin repetir y elige sus colores. Quitar se aplica al marcarlo. "
        "Estas reglas no limitan los idiomas que se pueden reconocer.", OBS_TEXT_INFO);
    obs_property_t *add = obs_properties_add_list(props, "add_language", "Añadir idioma",
                                                 OBS_COMBO_TYPE_LIST, OBS_COMBO_FORMAT_STRING);
    obs_property_set_modified_callback(add, language_changed);
    for (int i = 0; i < CAPTION_MAX_RULES; i++) {
        char key[32], label[96];
        snprintf(key, sizeof(key), "rule_language_%d", i);
        snprintf(label, sizeof(label), "Idioma %d", i + 1);
        obs_property_t *list = obs_properties_add_list(props, key, label, OBS_COMBO_TYPE_LIST, OBS_COMBO_FORMAT_STRING);
        obs_property_set_modified_callback(list, language_changed);
        snprintf(key, sizeof(key), "rule_color_%d", i);
        obs_properties_add_color(props, key, "Color");
        snprintf(key, sizeof(key), "remove_rule_%d", i);
        obs_property_t *remove = obs_properties_add_bool(props, key, "Quitar este idioma");
        obs_property_set_modified_callback(remove, language_changed);
    }
    language_changed(props, add, settings);
}
