import time
from types import SimpleNamespace

import pytest

from engine.asr import Recognizer
from engine.core import CaptionState
from engine.language import LanguageDetector, parse_colors


def test_automatic_english_spanish_and_unknown():
    detector = LanguageDetector()
    assert detector.identify("This is an example of automatic language detection in a live stream.") == "en"
    assert (
        detector.identify("Este es un ejemplo de deteccion automatica del idioma en una transmision.") == "es"
    )
    assert detector.identify("OK") == "und"


def test_native_tags_override_text_classifier():
    detector = LanguageDetector()
    assert detector.identify("hello", "<es-ES>") == "es"
    assert detector.identify("hello", "<es-ES><en-US>") == "mixed"


def test_language_switch_does_not_pin_entire_session():
    detector = LanguageDetector()
    spanish = "Vamos a conversar durante un momento para explicar el funcionamiento de esta herramienta. "
    assert detector.identify(spanish) == "es"
    assert (
        detector.identify(spanish + "Now we are switching to English without stopping the live stream.")
        == "en"
    )
    assert (
        detector.identify(
            "This was English. Ahora volvemos a hablar completamente en español sin detener nada."
        )
        == "es"
    )


def test_uncertain_recent_words_do_not_reuse_previous_language():
    detector = LanguageDetector()
    detector.classifier = SimpleNamespace(
        classify=lambda text: ("es", 0.55) if len(text) < 100 else ("en", 0.999)
    )
    text = "We were discussing this topic in English for quite some time. " * 3 + "vamos a ver qué pasa"
    assert detector.identify(text) == "und"


def test_corrected_partial_language_does_not_stay_mixed():
    recognizer = Recognizer.__new__(Recognizer)
    recognizer.state = CaptionState(9)
    segment = recognizer.state.begin()
    recognizer.language_detector = SimpleNamespace(
        identify=lambda text, raw: "fr" if text == "premier" else "es"
    )
    recognizer.speech_started = time.monotonic()
    recognizer.first_text = False
    recognizer.on_text(segment, "premier", False)
    recognizer.on_text(segment, "Primero vamos a explicar cómo funciona este programa", False)
    assert recognizer.state.snapshot()["source_language"] == "es"
    assert recognizer.state.snapshot()["subtitle_color"] == "#FFD166"


def test_short_unambiguous_english_and_non_latin_scripts():
    detector = LanguageDetector()
    assert detector.identify("This is a test") == "en"
    assert detector.identify("こんにちは世界、今日は良い天気です") == "ja"
    assert detector.identify("안녕하세요 오늘은 날씨가 좋습니다") == "ko"


def test_unsupported_classifier_language_uses_default_instead_of_false_colour():
    detector = LanguageDetector()
    detector.classifier = SimpleNamespace(classify=lambda text: ("eo", 0.999))
    assert detector.identify("Hola esto es una prueba") == "und"


def test_arbitrary_color_rules_and_default():
    colors, default = parse_colors("en=#7cc7ff\nes=#ffd166\nja=#abcdef", "#ffffff")
    assert colors["ja"] == "#ABCDEF"
    assert default == "#FFFFFF"
    state = CaptionState(9)
    state.color_rules, state.default_color = colors, default
    state.source_language = "ja"
    assert state.snapshot()["subtitle_color"] == "#ABCDEF"
    state.source_language = "und"
    assert state.snapshot()["subtitle_color"] == "#FFFFFF"


@pytest.mark.parametrize("rules", ["en=red", "en=#ffffff;body{display:none}", "toolong=#123456"])
def test_color_css_injection_rejected(rules):
    with pytest.raises(ValueError):
        parse_colors(rules, "#FFFFFF")
