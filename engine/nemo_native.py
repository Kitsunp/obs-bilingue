"""Small binding to NVIDIA NeMo-Speech.cpp's published, size-prefixed C ABI."""

import ctypes as C
import os
from pathlib import Path

import numpy as np


class Backend(C.Structure):
    _fields_ = [("size", C.c_size_t), ("gpu", C.c_int32)]


class Model(C.Structure):
    _fields_ = [("size", C.c_size_t), ("path", C.c_char_p), ("name", C.c_char_p)]


class Streaming(C.Structure):
    _fields_ = [("size", C.c_size_t), ("chunk_size", C.c_float),
                ("left", C.c_float), ("right", C.c_float), ("rnnt_right_context", C.c_int32)]


class Endpointing(C.Structure):
    _fields_ = [("size", C.c_size_t), ("enable", C.c_bool), ("vad_based", C.c_bool),
                ("silence_ms", C.c_int32)]


class Vad(C.Structure):
    _fields_ = [("size", C.c_size_t), ("path", C.c_char_p), ("masking", C.c_bool),
                ("onset", C.c_float), ("offset", C.c_float)]


class Config(C.Structure):
    _fields_ = [("size", C.c_size_t)] + [(name, C.c_void_p) for name in (
        "backend", "model", "streaming", "decoder", "vad", "endpointing", "postproc", "diar", "batching"
    )]


class Batching(C.Structure):
    _fields_ = [("size", C.c_size_t), ("enable", C.c_bool)] + [
        (name, C.c_int32) for name in ("max_batch", "delay_us", "depth", "cohort_us", "slots")
    ]


class Options(C.Structure):
    _fields_ = [("size", C.c_size_t), ("request_id", C.c_char_p), ("language_code", C.c_char_p),
                ("interim_results", C.c_bool), ("word_times", C.c_bool), ("punctuation", C.c_bool),
                ("verbatim", C.c_bool), ("profanity", C.c_bool), ("silence_ms", C.c_int32),
                ("contexts", C.c_void_p), ("context_count", C.c_size_t), ("alternatives", C.c_int32),
                ("diarization", C.c_bool), ("speaker_count", C.c_int32)]


class NativeRuntime:
    def __init__(self, root, config):
        folder = (Path(root) / config["nemo_runtime"]).resolve() / "bin"
        self.dll_directory = os.add_dll_directory(str(folder))
        self.dll = C.CDLL(str(folder / "nemo_speech_asr_c.dll"))
        self._bind("last_error", C.c_char_p, [])
        self._bind("create", C.c_int, [C.POINTER(Config), C.POINTER(C.c_void_p)])
        self._bind("destroy", None, [C.c_void_p])
        self._bind("recognition_options_default", Options, [])
        self._bind("streaming_recognize", C.c_int,
                   [C.c_void_p, C.POINTER(Options), C.POINTER(C.c_void_p)])
        self._bind("stream_push_f32", C.c_int,
                   [C.c_void_p, C.POINTER(C.c_float), C.c_size_t, C.c_int32])
        self._bind("stream_next", C.c_int, [C.c_void_p, C.POINTER(C.c_void_p)])
        self._bind("stream_force_endpoint", C.c_int, [C.c_void_p])
        self._bind("stream_finish", C.c_int, [C.c_void_p])
        self._bind("stream_close", None, [C.c_void_p])
        self._bind("result_destroy", None, [C.c_void_p])
        self._bind("result_transcript", C.c_char_p, [C.c_void_p, C.c_size_t])
        self._bind("result_audio_processed", C.c_float, [C.c_void_p])
        self._bind("result_is_final", C.c_bool, [C.c_void_p])
        self._bind("result_language_count", C.c_size_t, [C.c_void_p, C.c_size_t])
        self._bind("result_language_code", C.c_char_p, [C.c_void_p, C.c_size_t, C.c_size_t])
        backend = Backend(C.sizeof(Backend), config["nemo_gpu_device"])
        model = Model(C.sizeof(Model), str((Path(root) / config["nemo_model"]).resolve()).encode(), None)
        streaming = Streaming(C.sizeof(Streaming), 0.16, 1.92, 1.92, config["nemo_right_context"])
        vad_path = config.get("nemo_vad_model")
        vad = Vad(C.sizeof(Vad), str((Path(root) / vad_path).resolve()).encode() if vad_path else None,
                  False, config.get("vad_onset", 0.5), config.get("vad_offset", 0.3))
        endpoint = Endpointing(C.sizeof(Endpointing), True, bool(vad_path),
                              int(config["endpoint_seconds"] * 1000))
        batching = Batching(C.sizeof(Batching), False, 1, 0, 1, 0, 1)
        cfg = Config()
        cfg.size = C.sizeof(Config)
        for key, value in (("backend", backend), ("model", model),
                           ("streaming", streaming), ("endpointing", endpoint), ("batching", batching)):
            setattr(cfg, key, C.cast(C.pointer(value), C.c_void_p))
        if vad_path:
            cfg.vad = C.cast(C.pointer(vad), C.c_void_p)
        self.handle = C.c_void_p()
        self.check(self.create(C.byref(cfg), C.byref(self.handle)))

    def _bind(self, name, result, arguments):
        function = getattr(self.dll, "nemo_speech_asr_" + name)
        function.restype, function.argtypes = result, arguments
        setattr(self, name, function)

    def check(self, status):
        if status:
            raise RuntimeError((self.last_error() or b"Error del runtime ASR").decode("utf-8", "replace"))

    def open(self):
        options = self.recognition_options_default()
        options.language_code = b"auto"
        options.interim_results = True
        options.word_times = False
        stream = C.c_void_p()
        self.check(self.streaming_recognize(self.handle, C.byref(options), C.byref(stream)))
        return stream

    def push(self, stream, audio):
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        pointer = audio.ctypes.data_as(C.POINTER(C.c_float))
        self.check(self.stream_push_f32(stream, pointer, audio.size, 16000))

    def results(self, stream):
        while True:
            result = C.c_void_p()
            self.check(self.stream_next(stream, C.byref(result)))
            if not result:
                return
            try:
                text = (self.result_transcript(result, 0) or b"").decode("utf-8", "replace").strip()
                languages = {
                    self.result_language_code(result, 0, i).decode().split("-")[0]
                    for i in range(self.result_language_count(result, 0))
                }
                language = next(iter(languages)) if len(languages) == 1 else "mixed" if languages else "und"
                yield (text, language, bool(self.result_is_final(result)),
                       float(self.result_audio_processed(result)))
            finally:
                self.result_destroy(result)

    def finish(self, stream):
        self.check(self.stream_finish(stream))

    def close(self):
        if self.handle:
            self.destroy(self.handle)
            self.handle = C.c_void_p()
        self.dll_directory.close()
