import json
import threading
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from engine.asr_native import NativeRecognizer
from engine.core import CaptionState, TranslationMailbox
from engine.server import read_config


def exercise(blocks, threshold=2):
    recognizer = NativeRecognizer.__new__(NativeRecognizer)
    recognizer.config = {"native_zero_idle_seconds": threshold, "audio_idle_seconds": .8,
                         "max_utterance_seconds": 8, "asr_error_retry_seconds": .01}
    recognizer.state = CaptionState(9)
    recognizer.mailbox = TranslationMailbox()
    recognizer.stop = threading.Event()
    remaining = iter(blocks)
    events = deque()
    opened, closed, finished, submitted = [], [], [], []
    last_text = {}
    analyzed = []
    inbox = SimpleNamespace(epoch=0, last_offset=0)
    offset = 0

    def get(epoch, timeout):
        nonlocal offset
        try:
            audio = next(remaining)
        except StopIteration:
            recognizer.stop.set()
            return None
        inbox.last_offset = offset
        offset += len(audio)
        return audio

    inbox.get = get
    recognizer.inbox = inbox

    def open_stream():
        stream = len(opened) + 1
        opened.append(stream)
        return stream

    def push(stream, audio):
        submitted.append((stream, audio.copy()))
        if np.any(audio):
            text = f"Utterance {stream}"
            last_text[stream] = text
            events.append((text, "und", False, offset / 16000))

    def finish(stream):
        finished.append(stream)
        if stream in last_text:
            events.append((last_text.pop(stream), "und", True, offset / 16000))

    def results(stream):
        while events:
            yield events.popleft()

    recognizer.runtime = SimpleNamespace(
        open=open_stream, push=push, finish=finish, results=results,
        stream_close=closed.append, close=lambda: None,
    )
    def analyze(text, language, final):
        analyzed.append((text, final))
        return [{"text": text, "language": language}], language

    recognizer.span_detector = SimpleNamespace(analyze=analyze, calls=analyzed)
    recognizer.run()
    assert recognizer.state.error == ""
    return recognizer, opened, closed, finished, submitted


def test_long_exact_zero_gap_finalizes_once_reopens_and_keeps_physical_clock():
    voice = np.ones(320, np.float32)
    zero = np.zeros(320, np.float32)
    recognizer, opened, closed, finished, submitted = exercise([voice, *[zero] * 150, voice])
    assert opened == closed == [1, 2]
    assert finished == [1]
    assert recognizer.state.segment_audio_start_seconds == pytest.approx(3.02)
    rows = recognizer.state.snapshot()["rows"]
    assert [row["source"] for row in rows] == ["Utterance 1", "Utterance 2"]
    assert ("Utterance 1", True) in recognizer.span_detector.calls
    assert not recognizer.state.final
    assert rows[0]["flow_group"] != rows[1]["flow_group"]
    assert len(submitted) == 102  # voice + 2 s flush tail + voice; other zeros skipped
    assert recognizer.state.metrics["asr_zero_idle_closes"] == 1
    assert recognizer.state.metrics["asr_zero_samples_skipped"] == 16000


@pytest.mark.parametrize("amplitude", [1e-8, np.finfo(np.float32).tiny])
def test_quiet_nonzero_audio_is_never_classified_as_digital_silence(amplitude):
    quiet = np.full(320, amplitude, np.float32)
    recognizer, opened, _, finished, submitted = exercise([quiet] * 150)
    assert opened == [1] and not finished
    assert len(submitted) == 150
    assert all(np.array_equal(audio, quiet) for _, audio in submitted)
    assert recognizer.state.metrics["asr_zero_samples_skipped"] == 0


def test_short_zero_pause_preserves_context_and_every_sample():
    voice = np.ones(320, np.float32)
    zero = np.zeros(320, np.float32)
    recognizer, opened, _, finished, submitted = exercise([voice, *[zero] * 20, voice])
    assert opened == [1] and not finished
    assert len(submitted) == 22
    assert recognizer.state.metrics["asr_zero_samples_skipped"] == 0


def test_disabled_optimization_keeps_continuous_stream_and_all_zero_samples():
    voice = np.ones(320, np.float32)
    zero = np.zeros(320, np.float32)
    _, opened, _, finished, submitted = exercise([voice, *[zero] * 150, voice], threshold=0)
    assert opened == [1] and not finished
    assert len(submitted) == 152


def test_zero_only_input_does_not_open_gpu_stream_but_next_quiet_signal_does():
    zero = np.zeros(320, np.float32)
    quiet = np.full(320, 1e-8, np.float32)
    recognizer, opened, _, finished, submitted = exercise([*[zero] * 150, quiet])
    assert opened == [1] and not finished
    assert len(submitted) == 1 and np.array_equal(submitted[0][1], quiet)
    assert recognizer.state.segment_audio_start_seconds == pytest.approx(3)
    assert recognizer.state.metrics["asr_zero_samples_skipped"] == 48000


@pytest.mark.parametrize("value", [True, -1, .5, 31, float("nan"), float("inf")])
def test_zero_idle_config_rejects_invalid_or_insufficient_flush_tail(tmp_path, value):
    config = read_config()
    config["native_zero_idle_seconds"] = value
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="Pausa digital"):
        read_config(tmp_path)


@pytest.mark.parametrize("value", [0, 2, 5])
def test_zero_idle_config_can_be_disabled_or_use_a_valid_tail(tmp_path, value):
    config = read_config()
    config["native_zero_idle_seconds"] = value
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    assert read_config(tmp_path)["native_zero_idle_seconds"] == value
