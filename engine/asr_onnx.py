"""INT8 native streaming recognizer; leaves GPU capacity for OBS and translation."""

import threading
import time
from collections import deque

import numpy as np

from .asr import Recognizer
from .core import RATE, Discontinuity, level_db
from .language import LanguageDetector


class OnnxRecognizer(Recognizer):
    def __init__(self, root, config, inbox, state, mailbox):
        import sherpa_onnx

        folder = root / "models" / "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-80ms-int8-2026-06-11"
        self.decoder = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(folder / "tokens.txt"),
            encoder=str(folder / "encoder.int8.onnx"),
            decoder=str(folder / "decoder.int8.onnx"),
            joiner=str(folder / "joiner.int8.onnx"),
            num_threads=config["cpu_threads"],
            feature_dim=128,
            provider="cpu",
            enable_endpoint_detection=False,
        )
        self.config, self.inbox, self.state, self.mailbox = config, inbox, state, mailbox
        self.language_detector = LanguageDetector()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="recognition-onnx", daemon=True)
        self.last_translation = 0
        self.last_progress = time.monotonic()
        # Warm native kernels before live audio is accepted.
        stream = self.decoder.create_stream()
        stream.set_option("language", "auto")
        stream.accept_waveform(RATE, np.zeros(RATE // 2, np.float32))
        while self.decoder.is_ready(stream):
            self.decoder.decode_stream(stream)

    def finish_stream(self, stream, segment, last_text):
        # Decoder lookahead must be drained even if OBS stops sending packets.
        stream.accept_waveform(RATE, np.zeros(RATE // 5, np.float32))
        stream.input_finished()
        while self.decoder.is_ready(stream):
            self.decoder.decode_stream(stream)
            result = self.decoder.get_result_all(stream)
            text = result.text.strip()
            if text and text != last_text:
                last_text = text
                self.on_text(segment, text, False, "".join(result.tokens))
        self.on_text(segment, last_text, True)

    def run(self):
        pre_roll = deque(maxlen=10)
        stream = None
        last_text = ""
        received = silence = 0
        epoch = None
        segment = 0
        last_audio = time.monotonic()
        while not self.stop.is_set():
            self.last_progress = time.monotonic()
            try:
                audio = self.inbox.get(epoch if stream else None)
                if audio is None:
                    if stream and time.monotonic() - last_audio > 0.8:
                        self.finish_stream(stream, segment, last_text)
                        stream = None
                    continue
                last_audio = time.monotonic()
                quiet = level_db(audio) < self.config["speech_threshold_db"]
                if stream is None:
                    if quiet:
                        pre_roll.append(audio)
                        continue
                    start = max(0, (self.inbox.last_offset - sum(x.size for x in pre_roll)) / RATE)
                    audio = np.concatenate([*pre_roll, audio])
                    pre_roll.clear()
                    segment = self.state.begin()
                    self.state.segment_audio_start_seconds = start
                    self.speech_started = time.monotonic()
                    self.first_text = False
                    self.last_translation = 0
                    epoch = self.inbox.epoch
                    received = silence = 0
                    last_text = ""
                    stream = self.decoder.create_stream()
                    stream.set_option("language", "auto")
                received += audio.size
                silence = silence + audio.size if quiet else 0
                stream.accept_waveform(RATE, audio)
                ended = (
                    silence >= self.config["silence_seconds"] * RATE
                    or received >= self.config["max_utterance_seconds"] * RATE
                )
                while self.decoder.is_ready(stream):
                    self.decoder.decode_stream(stream)
                    result = self.decoder.get_result_all(stream)
                    text = result.text.strip()
                    if text and text != last_text:
                        last_text = text
                        self.on_text(segment, text, False, "".join(result.tokens))
                if ended:
                    self.finish_stream(stream, segment, last_text)
                    last_text = ""
                    stream = None
            except Discontinuity:
                stream = None
                pre_roll.clear()
                self.state.clear()
                self.mailbox.clear()
            except Exception as exc:
                self.state.error = f"ASR INT8: {type(exc).__name__}: {str(exc)[:180]}"
                stream = None
                self.stop.wait(0.2)
