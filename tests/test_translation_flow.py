import time
from pathlib import Path

import httpx

from engine.core import CaptionState, TranslationJob, TranslationMailbox
from engine.server import read_config
from engine.translation import Translator


def test_visible_previous_row_accepts_its_translation_without_changing_current_row():
    state = CaptionState(9)
    state.style.update(stack=True, max_rows=3)
    old = state.begin()
    state.partial(old, "Bonjour tout le monde.", True)
    current = state.begin()
    state.partial(current, "次の文章です。")
    assert state.translation_is_current(old, "Bonjour tout le monde.")
    assert state.translated(old, "Bonjour tout le monde.", {"es": "Hola a todos."})
    snapshot = state.snapshot()
    assert snapshot["rows"][0]["es"] == "Hola a todos."
    assert snapshot["rows"][-1]["es"] == snapshot["es"] == ""


def test_revised_source_rejects_translation_of_retracted_words():
    state = CaptionState(9)
    segment = state.begin()
    state.partial(segment, "I like it")
    state.partial(segment, "I do not like it")
    assert not state.translation_is_current(segment, "I like it")
    assert not state.translated(segment, "I like it", {"es": "Me gusta"})


def test_spanish_only_skips_translation_but_mixed_and_uncertain_text_do_not():
    state = CaptionState(9)
    segment = state.begin()
    state.partial(segment, "Buenos días.", spans=[{"text": "Buenos días.", "language": "es"}])
    translator = Translator(Path.cwd(), read_config(), state, TranslationMailbox())
    try:
        assert not translator.eligible(TranslationJob(segment, "Buenos días.", True, time.monotonic(), "es"))
        state.partial(segment, "Buenos días. Bonjour.", spans=[
            {"text": "Buenos días. ", "language": "es"}, {"text": "Bonjour.", "language": "fr"}])
        assert state.translation_required(segment)
        state.partial(segment, "Bonjour.", spans=[{"text": "Bonjour.", "language": "und"}])
        assert translator.eligible(TranslationJob(segment, "Bonjour.", True, time.monotonic(), "es"))
    finally:
        translator.close()


def test_final_survives_onset_of_next_partial_and_queue_stays_bounded():
    mailbox = TranslationMailbox()
    final = TranslationJob(1, "final", True, time.monotonic())
    mailbox.put(final)
    for index in range(10000):
        mailbox.put(TranslationJob(2, str(index), False, time.monotonic()))
    assert mailbox.get() == final
    assert mailbox.get().text == "9999"
    assert mailbox.get(timeout=0) is None


def test_target_translation_prompt_is_multilingual_and_uses_detected_text():
    state = CaptionState(9)
    translator = Translator(Path.cwd(), read_config(), state, TranslationMailbox())
    translator.client.close()
    requests = []

    def handle(request):
        import json
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                                                     "message": {"content": "Hola a todos."}}]})

    translator.client = httpx.Client(transport=httpx.MockTransport(handle), base_url="http://local")
    try:
        assert translator.translate("Bonjour tout le monde.", "es", "") == "Hola a todos."
        prompt = requests[0]["messages"][0]["content"]
        assert "Spanish" in prompt and "Bonjour tout le monde." in prompt
        assert "mix English and Spanish" not in prompt
    finally:
        translator.close()
