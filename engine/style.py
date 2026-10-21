"""Validated OBS display settings. No arbitrary HTML/CSS accepted."""

import re

DEFAULT_STYLE = {
    "font_face": "Segoe UI",
    "font_size": 40,
    "font_flags": 0,
    "translation_use_spanish_color": True,
    "translation_color": "#FFD166",
    "translation_use_original_font": False,
    "translation_font_face": "Segoe UI",
    "translation_font_size": 30,
    "translation_font_flags": 0,
    "translation_show_language_labels": True,
    "background_color": "#10151B",
    "background_opacity": 78,
    "duration_seconds": 8,
    "stack": True,
    "max_rows": 3,
    "max_lines_per_language": 2,
    "show_original": True,
}


def validate_style(options):
    style = dict(DEFAULT_STYLE)
    style.update({key: options[key] for key in style if key in options})
    for name in ("font_face", "translation_font_face"):
        face = style[name]
        if not isinstance(face, str) or not 1 <= len(face) <= 80 or any(ord(x) < 32 for x in face):
            raise ValueError(f"Nombre de fuente invalido: {name}")
    for name, low, high in (
        ("font_size", 8, 200),
        ("font_flags", 0, 15),
        ("translation_font_size", 8, 200),
        ("translation_font_flags", 0, 15),
        ("background_opacity", 0, 100),
        ("duration_seconds", 1, 60),
        ("max_rows", 1, 8),
        ("max_lines_per_language", 1, 6),
    ):
        if type(style[name]) is not int or not low <= style[name] <= high:
            raise ValueError(f"Valor de estilo invalido: {name}")
    for name in ("stack", "show_original", "translation_use_spanish_color", "translation_use_original_font",
                 "translation_show_language_labels"):
        if type(style[name]) is not bool:
            raise ValueError(f"Valor booleano invalido: {name}")
    for name in ("background_color", "translation_color"):
        if not isinstance(style[name], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", style[name]):
            raise ValueError(f"Color invalido: {name}")
    return style
