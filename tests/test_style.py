import pytest

from engine.core import CaptionState
from engine.style import validate_style


def test_style_changes_are_validated():
    style = validate_style({"font_face": "Arial", "font_size": 64, "stack": False, "duration_seconds": 3})
    assert style["font_size"] == 64
    assert not style["stack"]
    with pytest.raises(ValueError):
        validate_style({"font_size": 10000})
    with pytest.raises(ValueError):
        validate_style({"background_color": "url(https://external.invalid)"})


def test_visible_rows_are_fifo_and_expire():
    state = CaptionState(8)
    state.style["max_rows"] = 3
    for index in range(20):
        sid = state.begin()
        state.partial(sid, f"line {index}")
        state.translated(sid, f"line {index}", {"es": f"linea {index}"})
        assert len(state.rows) <= 3
    assert [row["source"] for row in state.snapshot()["rows"]] == ["line 17", "line 18", "line 19"]
    for row in state.rows:
        row["updated"] -= 20
    assert state.snapshot()["rows"] == []


def test_non_stack_replaces_instead_of_accumulating():
    state = CaptionState(8)
    state.style["stack"] = False
    for _ in range(100):
        sid = state.begin()
        state.partial(sid, "hello")
    assert len(state.rows) == 1


def test_partial_revisions_update_same_row():
    state = CaptionState(8)
    sid = state.begin()
    for n in range(100):
        state.partial(sid, f"hello {n}")
    assert len(state.rows) == 1
    assert state.rows[0]["source"] == "hello 99"


def test_translation_style_can_share_color_and_font_or_keep_its_own():
    style = validate_style({"font_face": "Arial", "font_size": 60,
                            "translation_font_face": "Consolas", "translation_font_size": 26})
    assert style["font_size"] == 60 and style["translation_font_size"] == 26
    state = CaptionState(8)
    state.style = style
    state.color_rules["es"] = "#123456"
    assert state.snapshot()["translation_display_color"] == "#123456"
    state.style.update(translation_use_spanish_color=False, translation_color="#ABCDEF",
                       translation_use_original_font=True)
    assert state.snapshot()["translation_display_color"] == "#ABCDEF"
    assert state.snapshot()["style"]["translation_use_original_font"]
    state.style["translation_use_spanish_color"] = True
    state.color_rules.pop("es")
    assert state.snapshot()["translation_display_color"] == state.default_color


@pytest.mark.parametrize("options", [
    {"translation_font_size": True}, {"translation_font_size": 201},
    {"translation_font_face": ""}, {"translation_font_flags": 16},
    {"translation_use_spanish_color": 1}, {"translation_use_original_font": "true"},
    {"translation_color": None}, {"translation_color": "red; background:url(bad)"},
    {"max_lines_per_language": 0}, {"max_lines_per_language": 7},
    {"max_lines_per_language": True}, {"translation_show_language_labels": "true"},
])
def test_invalid_translation_styles_are_rejected(options):
    with pytest.raises(ValueError):
        validate_style(options)
