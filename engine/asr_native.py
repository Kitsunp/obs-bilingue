"""Native Nemotron streaming; acoustic language tags, bounded stream lifetime."""

import threading
import time

import numpy as np

from .asr import Recognizer
from .core import RATE, Discontinuity
from .nemo_native import NativeRuntime
from .spans import SpanDetector


class NativeRecognizer(Recognizer):
    def __init__(self, root, config, inbox, state, mailbox):
        self.config, self.inbox, self.state, self.mailbox = config, inbox, state, mailbox
        self.runtime = NativeRuntime(root, config)
        self.span_detector = SpanDetector(config)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="recognition-native", daemon=True)
        self.last_progress = time.monotonic()
        self.decode_started = None
        self.last_translation = 0

    def run(self):
        stream, segment = None, None
        received = 0
        stream_start = segment_start = 0.0
        epoch = self.inbox.epoch
        last_audio = time.monotonic()
        last_result = None
        samples_submitted = 0
        samples_at_text_change = 0
        forced_boundary_pending = False
        continue_caption = False
        zero_limit = int(self.config.get("native_zero_idle_seconds", 2.0) * RATE)
        zero_samples = 0
        self.state.metrics.update(asr_result_updates=0, asr_duplicate_interims_skipped=0,
                                  asr_samples_submitted=0, asr_audio_seconds_since_text_change=0,
                                  asr_zero_samples_skipped=0, asr_zero_idle_closes=0,
                                  asr_zero_idle_seconds=zero_limit / RATE)

        def publish():
            nonlocal segment, received, segment_start, last_result, samples_at_text_change
            nonlocal forced_boundary_pending, continue_caption
            for text, language, final, processed_seconds in self.runtime.results(stream):
                self.state.metrics["asr_result_updates"] += 1
                result = (text, language, final)
                if (self.config.get("native_deduplicate_interims", True)
                        and not final and result == last_result):
                    self.state.metrics["asr_duplicate_interims_skipped"] += 1
                    continue
                if text and (last_result is None or text != last_result[0]):
                    samples_at_text_change = samples_submitted
                last_result = result if not final else None
                if text and segment is None:
                    segment = self.state.begin(continuation=continue_caption)
                    continue_caption = False
                    self.state.segment_audio_start_seconds = segment_start
                    self.first_text = False
                    self.last_translation = 0
                if segment is not None:
                    started = time.monotonic()
                    spans, detected = self.span_detector.analyze(text, language, final)
                    self.state.metrics["language_spans_ms"] = round((time.monotonic() - started) * 1000, 2)
                    self.state.metrics["acoustic_language"] = language
                    self.state.metrics["language_evidence_conflict"] = (
                        language not in ("und", "mixed") and detected not in ("und", "mixed", language)
                    )
                    self.publish_text(segment, text, final, detected, spans)
                if final:
                    continue_caption = forced_boundary_pending and bool(text)
                    forced_boundary_pending = False
                    segment = None
                    received = 0
                    segment_start = stream_start + processed_seconds
                    self.speech_started = time.monotonic()

        try:
            while not self.stop.is_set():
                self.last_progress = time.monotonic()
                try:
                    audio = self.inbox.get(epoch, timeout=0.1)
                    if audio is None:
                        if stream and time.monotonic() - last_audio >= self.config["audio_idle_seconds"]:
                            self.decode_started = time.monotonic()
                            forced_boundary_pending = False
                            self.runtime.finish(stream)
                            publish()
                            self.runtime.stream_close(stream)
                            stream, segment = None, None
                            continue_caption = False
                            zero_samples = 0
                            self.decode_started = None
                        continue
                    last_audio = time.monotonic()
                    self.decode_started = last_audio
                    # Exact digital zero is the only condition that permits skipping.
                    # Quiet speech and VAD uncertainty must still reach the model.
                    digital_zero = zero_limit > 0 and not np.any(audio)
                    zero_samples = min(zero_limit, zero_samples + audio.size) if digital_zero else 0
                    if digital_zero and stream is None:
                        self.state.metrics["asr_zero_samples_skipped"] += audio.size
                        self.decode_started = None
                        continue
                    if stream is None:
                        last_result = None
                        stream = self.runtime.open()
                        received = 0
                        self.speech_started = last_audio
                        stream_start = segment_start = self.inbox.last_offset / RATE
                    received += audio.size
                    self.runtime.push(stream, audio)
                    samples_submitted += audio.size
                    publish()
                    self.state.metrics["asr_samples_submitted"] = samples_submitted
                    self.state.metrics["asr_audio_seconds_since_text_change"] = round(
                        (samples_submitted - samples_at_text_change) / RATE, 2
                    )
                    if digital_zero and zero_samples >= zero_limit:
                        forced_boundary_pending = False
                        self.runtime.finish(stream)
                        publish()
                        self.runtime.stream_close(stream)
                        stream, segment = None, None
                        continue_caption = False
                        received = 0
                        self.state.metrics["asr_zero_idle_closes"] += 1
                    elif received >= self.config["max_utterance_seconds"] * RATE:
                        # Publish a boundary without EOS padding or dropping acoustic caches.
                        forced_boundary_pending = True
                        self.runtime.check(self.runtime.stream_force_endpoint(stream))
                        publish()
                        received = 0
                    self.state.metrics["asr_decode_ms"] = round(
                        (time.monotonic() - self.decode_started) * 1000, 2
                    )
                    self.decode_started = None
                    self.state.error = ""
                except Discontinuity:
                    if stream:
                        self.runtime.stream_close(stream)
                    stream, segment = None, None
                    forced_boundary_pending = continue_caption = False
                    zero_samples = 0
                    epoch = self.inbox.epoch
                    self.decode_started = None
                    self.state.clear()
                    self.mailbox.clear()
                except Exception as exc:
                    self.state.error = f"ASR nativo: {type(exc).__name__}: {str(exc)[:180]}"
                    if stream:
                        self.runtime.stream_close(stream)
                    stream, segment = None, None
                    forced_boundary_pending = continue_caption = False
                    zero_samples = 0
                    self.decode_started = None
                    self.stop.wait(self.config["asr_error_retry_seconds"])
        finally:
            if stream:
                self.runtime.stream_close(stream)
            self.runtime.close()
