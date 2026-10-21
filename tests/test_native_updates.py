import threading
from types import SimpleNamespace

import numpy as np

from engine.asr_native import NativeRecognizer
from engine.core import AudioInbox, CaptionState, TranslationMailbox


def exercise(deduplicate):
    recognizer = NativeRecognizer.__new__(NativeRecognizer)
    recognizer.config = {"native_deduplicate_interims": deduplicate, "audio_idle_seconds": .8,
                         "max_utterance_seconds": 8, "asr_error_retry_seconds": .01}
    recognizer.inbox = AudioInbox(.4)
    recognizer.state = CaptionState(9)
    recognizer.mailbox = TranslationMailbox()
    recognizer.stop = threading.Event()
    updates = 0
    analyzed = []
    samples = []

    def results(stream):
        nonlocal updates
        updates += 1
        if updates <= 10:
            yield "Repeated hypothesis", "und", False, updates / 50
        elif updates == 11:
            yield "Repeated hypothesis", "en", True, updates / 50
        else:
            recognizer.stop.set()

    def analyze(text, language, final):
        analyzed.append((text, language, final))
        return [{"text": text, "language": language}], language

    def push(stream, audio):
        samples.append(audio.copy())
        if len(samples) < 12:
            recognizer.inbox.put(np.ones(320, dtype=np.float32))

    recognizer.runtime = SimpleNamespace(open=lambda: object(), results=results, push=push,
                                         stream_close=lambda stream: None, close=lambda: None)
    recognizer.span_detector = SimpleNamespace(analyze=analyze)
    recognizer.inbox.put(np.ones(320, dtype=np.float32))
    recognizer.run()
    return recognizer, analyzed, samples


def test_skip_only_identical_interims_keep_all_audio_and_final_language_update():
    optimized, analyses, optimized_audio = exercise(True)
    baseline, baseline_analyses, baseline_audio = exercise(False)
    assert len(analyses) == 2 and len(baseline_analyses) == 11
    assert analyses[-1] == ("Repeated hypothesis", "en", True)
    def rows(state):
        return [{k: v for k, v in row.items() if k != "updated"} for row in state.snapshot()["rows"]]
    assert rows(optimized.state) == rows(baseline.state)
    assert len(optimized_audio) == len(baseline_audio) == 12
    assert all(np.array_equal(a, b) for a, b in zip(optimized_audio, baseline_audio, strict=True))
    assert optimized.state.metrics["asr_duplicate_interims_skipped"] == 9
