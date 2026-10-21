"""Native cache-aware Nemotron streaming, reset at bounded utterance boundaries."""

from __future__ import annotations

import math
import re
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from .core import RATE, Discontinuity, TranslationJob, level_db
from .language import LanguageDetector


class TokenSink:
    def __init__(self, processor, callback):
        self.processor, self.callback = processor, callback
        self.tokens: list[int] = []
        self.text = ""
        self.raw = ""
        self.last = 0.0

    def put(self, values):
        self.tokens.extend(values.reshape(-1).tolist())
        self.raw = self.processor.tokenizer.decode(self.tokens, skip_special_tokens=False)
        raw = self.processor.tokenizer.decode(self.tokens, skip_special_tokens=True)
        text = re.sub(r"<[^>]*>", "", raw).strip()
        if "\ufffd" in text:
            return
        if text != self.text:
            self.text = text
            now = time.monotonic()
            if now - self.last >= 0.04:
                self.callback(text, False, self.raw)
                self.last = now

    def end(self):
        self.callback(self.text, True, self.raw)


class Recognizer:
    def __init__(self, root: Path, config, inbox, state, mailbox):
        import torch
        from transformers import AutoModelForRNNT, AutoProcessor

        self.torch, self.config = torch, config
        self.inbox, self.state, self.mailbox = inbox, state, mailbox
        torch.set_num_threads(config["cpu_threads"])
        torch.set_num_interop_threads(1)
        device = config["asr_device"]
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA no disponible. Ejecuta PREPARAR.ps1 o selecciona asr_device=cpu.")
        model_path = root / "models" / "nemotron"
        self.processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
        self.processor.set_num_lookahead_tokens(config["lookahead_tokens"])
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        self.model = (
            AutoModelForRNNT.from_pretrained(
                model_path, dtype=dtype, local_files_only=True, attn_implementation="sdpa"
            )
            .to(device)
            .eval()
        )
        for layer in self.model.modules():
            if isinstance(layer, torch.nn.LSTM):
                layer.flatten_parameters()
        with torch.inference_mode():
            warm = self.processor(
                np.zeros(RATE, np.float32), sampling_rate=RATE, language="auto", return_tensors="pt"
            )
            self.model.generate(**warm.to(device, dtype=dtype), max_new_tokens=16, do_sample=False)
        self.stop = threading.Event()
        self.language_detector = LanguageDetector()
        self.thread = threading.Thread(target=self.run, name="recognition", daemon=True)
        self.session_seconds = 0.0
        self.last_translation = 0.0
        self.last_progress = time.monotonic()

    def start(self):
        self.thread.start()

    def run(self):
        pre_roll = deque(maxlen=10)
        with self.torch.inference_mode():
            while not self.stop.is_set():
                self.last_progress = time.monotonic()
                audio = self.inbox.get()
                if audio is None:
                    continue
                if level_db(audio) < self.config["speech_threshold_db"]:
                    pre_roll.append(audio)
                    continue
                pre_roll_samples = sum(x.size for x in pre_roll)
                initial = np.concatenate([*pre_roll, audio])
                pre_roll.clear()
                segment = self.state.begin()
                self.state.segment_audio_start_seconds = max(
                    0, (self.inbox.last_offset - pre_roll_samples) / RATE
                )
                self.speech_started = time.monotonic()
                self.first_text = False
                epoch = self.inbox.epoch
                self.last_translation = 0
                sink = TokenSink(
                    self.processor, lambda text, final, raw, sid=segment: self.on_text(sid, text, final, raw)
                )
                try:
                    # RNN-T generation counts blank advances as well as emitted symbols.
                    # Budget from the bounded audio duration and the model's symbol limit.
                    enc = self.model.config.encoder_config
                    frame_seconds = (
                        self.processor.feature_extractor.hop_length * enc.subsampling_factor / RATE
                    )
                    frames = math.ceil((self.config["max_utterance_seconds"]
                                        + self.config["audio_queue_seconds"]) / frame_seconds)
                    steps = (frames + self.config["lookahead_tokens"] + 2) * (
                        self.model.config.max_symbols_per_step + 1
                    )
                    features = self.features(initial, epoch)
                    self.model.generate(
                        input_features=features,
                        prompt_ids=self.processor._resolve_prompt_ids("auto", 1).to(self.model.device),
                        num_lookahead_tokens=self.config["lookahead_tokens"],
                        streamer=sink,
                        max_new_tokens=steps,
                        do_sample=False,
                    )
                except Discontinuity:
                    self.state.clear()
                    self.mailbox.clear()
                except Exception as exc:
                    self.state.error = f"Reconocimiento: {type(exc).__name__}: {str(exc)[:240]}"
                    self.state.status = "Error de reconocimiento; reintentando"
                    self.stop.wait(1)
                finally:
                    # Each generate owns its caches. No hours-long encoder buffer.
                    sink.tokens.clear()

    def on_text(self, segment, text, final, raw=""):
        classification_start = time.monotonic()
        detected = self.language_detector.identify(text, raw)
        self.state.metrics["language_classify_ms"] = round(
            (time.monotonic() - classification_start) * 1000, 2
        )
        self.publish_text(segment, text, final, detected)

    def publish_text(self, segment, text, final, detected, spans=None):
        # Partial hypotheses are revisions, not proof that two languages were spoken.
        self.state.source_language = detected
        visible = self.state.partial(segment, text, final, spans=spans)
        if visible is None:
            return
        if not text:
            return
        now = time.monotonic()
        if not self.first_text:
            self.state.metrics["first_partial_ms"] = round((now - self.speech_started) * 1000)
            self.first_text = True
        if self.state.translation_enabled and (
            final or now - self.last_translation >= self.config["translation_interval_seconds"]
        ):
            row_epoch = self.state.translation_token(segment)
            if row_epoch is not None:
                self.mailbox.put(TranslationJob(segment, visible[-500:], final, now,
                                                self.state.source_language, row_epoch))
                self.last_translation = now

    def features(self, initial, epoch):
        p = self.processor
        samples = initial
        total = initial.size
        silence = 0
        start = 0
        first = True
        ended = False
        last_input = time.monotonic()
        while not self.stop.is_set():
            self.last_progress = time.monotonic()
            size = p.num_samples_first_audio_chunk if first else p.num_samples_per_audio_chunk
            end = start + size
            while samples.size < end and not ended and not self.stop.is_set():
                block = self.inbox.get(epoch)
                if block is None:
                    ended = self.inbox.closed or time.monotonic() - last_input > 0.8
                    continue
                last_input = time.monotonic()
                samples = np.concatenate((samples, block))
                total += block.size
                silence = silence + block.size if level_db(block) < self.config["speech_threshold_db"] else 0
                ended = (
                    silence >= self.config["silence_seconds"] * RATE
                    or total >= self.config["max_utterance_seconds"] * RATE
                )
            if self.stop.is_set():
                return
            if samples.size <= start:
                return
            part = samples[start:end]
            if part.size < size:
                part = np.pad(part, (0, size - part.size))
            inputs = p(
                part,
                sampling_rate=RATE,
                is_streaming=True,
                is_first_audio_chunk=first,
                language="auto",
                return_tensors="pt",
            )
            features = inputs.input_features
            if first:
                features = features[:, : p.num_mel_frames_first_audio_chunk, :]
            yield features.to(device=self.model.device, dtype=self.model.dtype)
            advance = (
                p.num_mel_frames_first_audio_chunk * p.feature_extractor.hop_length
                - p.feature_extractor.n_fft // 2
                if first
                else p.num_mel_frames_per_audio_chunk * p.feature_extractor.hop_length
            )
            start += advance
            first = False
            if ended and start >= samples.size - p.feature_extractor.win_length:
                return
            # Keep only the overlap needed by STFT, regardless of utterance duration.
            samples = np.pad(samples, (-start, 0)) if start < 0 else samples[start:].copy()
            start = 0

    def close(self):
        self.stop.set()
        self.inbox.close()
        if self.thread.is_alive():
            self.thread.join(timeout=5)
