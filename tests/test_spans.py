from engine.core import CaptionState
from engine.server import read_config
from engine.spans import SpanDetector


def test_mixed_language_sentence_preserves_text_and_detects_switch_back():
    detector = SpanDetector(read_config())
    text = ("I am speaking English ahora estoy hablando en español y después regreso "
            "to speaking English again.")
    spans = detector.identify(text)
    assert "".join(part["text"] for part in spans) == text
    assert [part["language"] for part in spans] == ["en", "es", "en"]


def test_new_sentence_and_global_language_do_not_recolour_old_sentence():
    detector = SpanDetector(read_config())
    prefix = "This is an English sentence. "
    before = detector.identify(prefix)
    after = detector.identify(prefix + "Ahora estamos hablando en español para comprobar los colores.")
    assert after[:len(before)] == before
    state = CaptionState(9)
    state.style["stack"] = True
    state.color_rules = {"en": "#112233", "es": "#445566"}
    segment = state.begin()
    state.source_language = "es"
    state.partial(segment, "".join(p["text"] for p in after), spans=after)
    row = state.snapshot()["rows"][-1]
    assert row["spans"][0]["color"] == "#112233"
    assert row["spans"][-1]["color"] == "#445566"


def test_ambiguous_word_remains_unknown_and_cache_is_bounded():
    detector = SpanDetector(read_config())
    assert detector.identify("Hello")[0]["language"] == "und"
    for count in range(40):
        detector.identify(f"This is an English sentence number {count}.")
    assert len(detector.cache) <= 16


def test_long_caption_trimming_keeps_spans_aligned():
    state = CaptionState(9)
    segment = state.begin()
    text = "a" * 300 + "b" * 300
    state.partial(segment, text, spans=[{"text": "a" * 300, "language": "en"},
                                        {"text": "b" * 300, "language": "es"}])
    row = state.snapshot()["rows"][0]
    assert "".join(part["text"] for part in row["spans"]) == row["source"] == text[-500:]


def test_text_can_identify_english_before_acoustic_tag_exists():
    detector = SpanDetector(read_config())
    spans, language = detector.analyze("This is an English sentence.", "und")
    assert language == "en"
    assert {part["language"] for part in spans} == {"en"}


def test_final_acoustic_evidence_resolves_short_ambiguous_text():
    detector = SpanDetector(read_config())
    assert detector.analyze("Hello", "und")[1] == "und"
    assert detector.analyze("Hello", "en", final=True)[1] == "en"
    # Acoustic evidence is not written into the text cache for later utterances.
    assert detector.analyze("Hello", "und")[1] == "und"


def test_acoustic_tag_does_not_overwrite_confident_mixed_spans():
    detector = SpanDetector(read_config())
    text = ("I am speaking English ahora estoy hablando en español y después regreso "
            "to speaking English again.")
    spans, language = detector.analyze(text, "es", final=True)
    assert language == "mixed"
    assert [part["language"] for part in spans] == ["en", "es", "en"]


def test_short_exclamation_is_not_confidently_assigned_to_unrelated_language():
    detector = SpanDetector(read_config())
    assert detector.analyze("Wow.")[1] == "und"


def test_clear_english_and_french_use_margin_instead_of_waiting_for_high_posterior():
    detector = SpanDetector(read_config())
    assert detector.analyze("This is an example.")[1] == "en"
    assert detector.analyze("Bonjour tout le monde.")[1] == "fr"


def test_french_and_japanese_keep_separate_spans_without_language_configuration():
    detector = SpanDetector(read_config())
    text = "Bonjour tout le monde. 今日はとても良い天気ですね。"
    spans, language = detector.analyze(text)
    assert language == "mixed"
    assert [part["language"] for part in spans] == ["fr", "ja"]
    assert "".join(part["text"] for part in spans) == text


def test_near_tied_languages_remain_uncertain_without_audio_evidence():
    detector = SpanDetector(read_config())
    assert detector.analyze("Como estas")[1] == "und"


def test_unrelated_acoustic_tag_cannot_recolour_clear_japanese_or_french():
    detector = SpanDetector(read_config())
    assert detector.analyze("今日はとても良い天気ですね。", "lv", final=True)[1] == "ja"
    assert detector.analyze("Bonjour tout le monde.", "en", final=True)[1] == "fr"
