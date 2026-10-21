import threading
from types import SimpleNamespace

import numpy as np

from engine.asr_native import NativeRecognizer
from engine.core import AudioInbox, CaptionState, TranslationMailbox


def test_continuation_shares_display_group_but_keeps_translation_identity():
    state = CaptionState(9)
    first = state.begin()
    state.partial(first, "An earlier phrase.", True)
    old_epoch = state.translation_token(first)
    second = state.begin(continuation=True)
    state.partial(second, "The continuation.")
    new_epoch = state.translation_token(second)
    assert old_epoch != new_epoch
    assert state.translated(first, "An earlier phrase.", {"es": "Una frase anterior."}, old_epoch)
    rows = state.snapshot()["rows"]
    assert rows[0]["flow_group"] == rows[1]["flow_group"]
    assert rows[0]["id"] != rows[1]["id"]
    assert rows[1]["source"] == state.snapshot()["source"] == "The continuation."
    assert rows[1]["es"] == ""
    assert not state.translated(second, "An earlier phrase.", {"es": "No debe aparecer"}, old_epoch)
    third = state.begin()
    state.partial(third, "A separate utterance.")
    assert state.snapshot()["rows"][-1]["flow_group"] != rows[1]["flow_group"]


def test_expired_continuation_does_not_reuse_group_or_revive_translation():
    state = CaptionState(9)
    first = state.begin()
    state.partial(first, "Expired words.", True)
    old_epoch = state.translation_token(first)
    old_group = state.rows[-1]["flow_group"]
    state.updated -= 20
    state.rows[-1]["updated"] -= 20
    second = state.begin(continuation=True)
    state.partial(second, "Current words.")
    assert state.rows[-1]["flow_group"] != old_group
    assert not state.translated(first, "Expired words.", {"es": "Texto caducado."}, old_epoch)
    assert len(state.snapshot()["rows"]) == 1


def test_native_only_technical_endpoint_continues_display_and_keeps_all_audio():
    recognizer = NativeRecognizer.__new__(NativeRecognizer)
    recognizer.config = {"audio_idle_seconds": .8, "max_utterance_seconds": .04,
                         "asr_error_retry_seconds": .01}
    recognizer.inbox = AudioInbox(.4)
    recognizer.state = CaptionState(9)
    recognizer.mailbox = TranslationMailbox()
    recognizer.stop = threading.Event()
    events = []
    received = []
    forced = []
    hypotheses = [("First part", False), ("First part", False),
                  ("continued speech", False), ("continued speech", True),
                  ("A new utterance", False), ("A new utterance", True)]

    def push(stream, audio):
        received.append(audio.copy())
        text, final = hypotheses[len(received) - 1]
        events.append((text, "en", final, len(received) * .02))
        if len(received) < len(hypotheses):
            recognizer.inbox.put(np.ones(320, dtype=np.float32))
        else:
            recognizer.stop.set()

    def results(stream):
        while events:
            yield events.pop(0)

    def endpoint(stream):
        forced.append(True)
        events.append(("First part", "en", True, .04))
        return 0

    recognizer.runtime = SimpleNamespace(open=lambda: object(), results=results, push=push,
                                         stream_force_endpoint=endpoint, check=lambda status: None,
                                         stream_close=lambda stream: None, close=lambda: None)
    recognizer.span_detector = SimpleNamespace(analyze=lambda text, language, final:
                                               ([{"text": text, "language": language}], language))
    recognizer.inbox.put(np.ones(320, dtype=np.float32))
    recognizer.run()
    rows = recognizer.state.snapshot()["rows"]
    assert len(forced) == 1
    assert [row["source"] for row in rows] == ["First part", "continued speech", "A new utterance"]
    assert rows[0]["flow_group"] == rows[1]["flow_group"] != rows[2]["flow_group"]
    assert len(received) == 6 and sum(part.size for part in received) == 1920
