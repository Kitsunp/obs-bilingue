from engine.core import CaptionState


def test_begin_does_not_expose_previous_translation_as_current():
    state = CaptionState(9)
    old = state.begin()
    state.partial(old, "An earlier sentence.")
    state.translated(old, "An earlier sentence.", {"es": "Una frase anterior."})
    state.begin()
    snapshot = state.snapshot()
    assert snapshot["es"] == snapshot["translation_source"] == ""
    assert snapshot["rows"][0]["es"] == "Una frase anterior."


def test_duplicate_final_does_not_resurrect_expired_caption():
    state = CaptionState(9)
    segment = state.begin()
    text = "A complete earlier sentence."
    state.partial(segment, text)
    state.translated(segment, text, {"es": "Una frase anterior completa."})
    state.updated -= 20
    for row in state.rows:
        row["updated"] -= 20
    state.expire()
    state.partial(segment, text, True)
    assert state.snapshot()["rows"] == []
    assert not state.translated(segment, text, {"es": "Una frase anterior completa."})


def test_repeated_interim_does_not_extend_display_lifetime():
    state = CaptionState(9)
    segment = state.begin()
    state.partial(segment, "The same words.")
    state.updated -= 2
    state.rows[0]["updated"] -= 2
    previous = state.rows[0]["updated"]
    for _ in range(1000):
        state.partial(segment, "The same words.")
    assert state.rows[0]["updated"] == previous


def test_expired_request_cannot_fill_recreated_row_of_same_asr_segment():
    state = CaptionState(9)
    segment = state.begin()
    text = "A previous partial"
    state.partial(segment, text)
    old_token = state.translation_token(segment)
    state.updated -= 20
    state.rows[0]["updated"] -= 20
    state.expire()
    current = text + " with new words."
    state.partial(segment, current)
    new_token = state.translation_token(segment)
    assert new_token != old_token
    assert not state.translation_is_current(segment, text, old_token)
    assert not state.translated(segment, text, {"es": "Contenido anterior"}, old_token)
    assert state.snapshot()["source"] == "with new words."
    assert state.translated(segment, "with new words.", {"es": "Contenido actual"}, new_token)
    assert state.snapshot()["rows"][0]["es"] == "Contenido actual"


def test_extending_expired_hypothesis_keeps_only_new_text_and_its_language():
    state = CaptionState(9)
    segment = state.begin()
    old = "The earlier sentence."
    state.partial(segment, old)
    state.updated -= 20
    state.rows[0]["updated"] -= 20
    state.expire()
    full = old + " Ahora seguimos."
    spans = [{"text": old + " ", "language": "en"}, {"text": "Ahora seguimos.", "language": "es"}]
    assert state.partial(segment, full, spans=spans) == "Ahora seguimos."
    snapshot = state.snapshot()
    assert snapshot["rows"][0]["spans"] == [
        {"text": "Ahora seguimos.", "language": "es", "color": "#FFD166"}]
    assert not state.translation_required(segment)
    assert state.partial(segment, full + " Con más palabras.") == "Ahora seguimos. Con más palabras."


def test_legitimate_repetition_in_new_asr_segment_is_preserved():
    state = CaptionState(9)
    text = "Yes, yes, yes."
    state.partial(state.begin(), text, True)
    assert state.partial(state.begin(), text, True) == text
    assert [row["source"] for row in state.snapshot()["rows"]] == [text, text]


def test_fast_expiration_and_late_results_remain_bounded():
    state = CaptionState(9)
    for index in range(10000):
        segment = state.begin()
        text = f"Synthetic sentence {index}."
        state.partial(segment, text)
        token = state.translation_token(segment)
        state.updated -= 20
        for row in state.rows:
            row["updated"] -= 20
        state.expire()
        state.partial(segment, text, True)
        assert not state.translated(segment, text, {"es": "Respuesta caducada"}, token)
        assert not state.rows and not state.snapshot()["es"]
