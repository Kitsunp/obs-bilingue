from types import SimpleNamespace

from engine.asr_onnx import OnnxRecognizer


def test_final_caption_includes_pending_decoder_tail():
    stream = SimpleNamespace(finished=False, decoded=False)
    stream.accept_waveform = lambda rate, samples: None
    stream.input_finished = lambda: setattr(stream, "finished", True)
    recognizer = OnnxRecognizer.__new__(OnnxRecognizer)
    recognizer.decoder = SimpleNamespace(
        is_ready=lambda s: s.finished and not s.decoded,
        decode_stream=lambda s: setattr(s, "decoded", True),
        get_result_all=lambda s: SimpleNamespace(text="Hola a todos", tokens=[]),
    )
    captions = []
    recognizer.on_text = lambda segment, text, final, raw="": captions.append((text, final))
    recognizer.finish_stream(stream, 1, "Hola")
    assert captions[-1] == ("Hola a todos", True)
