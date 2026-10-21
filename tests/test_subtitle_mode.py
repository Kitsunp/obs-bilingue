import time

from fastapi.testclient import TestClient

from engine.core import CaptionState, TranslationMailbox
from engine.server import create_app, read_config
from engine.translation import Translator


def test_original_overlay_is_default_and_spanish_translation_is_opt_in():
    state = CaptionState(8)
    sid = state.begin()
    state.source_language = "en"
    state.partial(sid, "Hello, this stays in English")
    snapshot = state.snapshot()
    assert not snapshot["translation_enabled"]
    assert snapshot["rows"][0]["source"] == "Hello, this stays in English"
    assert snapshot["rows"][0]["color"] == "#7CC7FF"
    state.set_translation(True)
    state.translated(sid, state.source, {"es": "Hola, esto sigue en ingles"})
    assert state.snapshot()["rows"][0]["es"]
    state.set_translation(False)
    assert state.snapshot()["rows"][0]["es"] == ""
    assert state.snapshot()["rows"][0]["source"] == "Hello, this stays in English"


def test_disabled_translation_starts_no_model_process(tmp_path):
    state = CaptionState(8)
    translator = Translator(tmp_path, read_config(), state, TranslationMailbox())
    translator.start()
    try:
        time.sleep(0.05)
        assert translator.process is None
        assert translator.thread.is_alive()
    finally:
        translator.close()


def test_language_only_revision_recolors_existing_caption():
    state = CaptionState(8)
    sid = state.begin()
    state.partial(sid, "hello")
    revision = state.revision
    state.source_language = "en"
    state.partial(sid, "hello")
    assert state.revision > revision
    assert state.snapshot()["rows"][0]["color"] == "#7CC7FF"


def test_original_overlay_route_exists_without_starting_models():
    client = TestClient(create_app(read_config()))
    page = client.get("/overlay/original")
    assert page.status_code == 200
    assert "const lang='original'" in page.text
    assert "translation_enabled" in page.text
