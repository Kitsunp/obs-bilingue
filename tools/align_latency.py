"""Independent MMS CTC word alignment for benchmark timing estimates.

No transcript is written to disk. This assesses timing, not translation quality.
"""

import re
import subprocess
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np


def words(text):
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(x for x in text if not unicodedata.combining(x))
    return re.findall("[a-z]+", text)


def stats(values):
    if not values:
        return {"samples": 0}
    return {
        "samples": len(values),
        "mean_ms": round(float(np.mean(values))),
        "p95_ms": round(float(np.percentile(values, 95))),
        "max_ms": round(max(values)),
        "within_1s_percent": round(sum(x <= 1000 for x in values) / len(values) * 100, 1),
    }


def align_updates(video, updates, origin, media_offset=0):
    import torch
    import torchaudio

    torch.set_num_threads(4)
    bundle = torchaudio.pipelines.MMS_FA
    cache = Path(__file__).resolve().parents[3] / "work" / "alignment-model"
    model = bundle.get_model(dl_kwargs={"model_dir": str(cache)}).eval()
    tokenizer, aligner = bundle.get_tokenizer(), bundle.get_aligner()
    groups = defaultdict(list)
    for update in updates:
        groups[update[1]].append(update)
    partial_lags, translated_lags = [], []
    rejected, accepted = 0, 0
    for entries in groups.values():
        transcript = max((entry[2] for entry in entries), key=len)
        target_words = words(transcript)
        if not target_words:
            continue
        start = entries[0][4]
        end = min(start + 13, entries[-1][0] - origin + 0.4)
        duration = end - start
        if duration <= 0:
            continue
        decoded = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(start + media_offset),
                "-i",
                str(video),
                "-t",
                str(duration),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "f32le",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
        )
        waveform = torch.from_numpy(np.frombuffer(decoded.stdout, dtype="<f4").copy()).unsqueeze(0)
        if waveform.shape[1] < 1000:
            continue
        try:
            with torch.inference_mode():
                emission, _ = model(waveform)
                spans = aligner(emission[0], tokenizer(target_words))
        except (RuntimeError, ValueError):
            rejected += len(target_words)
            continue
        seconds_per_frame = waveform.shape[1] / 16000 / emission.shape[1]
        for index, span in enumerate(spans):
            confidence = sum(token.score for token in span) / max(1, len(span))
            if confidence < 0.5:
                rejected += 1
                continue
            accepted += 1
            audio_end = origin + start + span[-1].end * seconds_per_frame
            prefix = target_words[: index + 1]
            for column, destination in ((2, partial_lags), (3, translated_lags)):
                seen = next(
                    (entry[0] for entry in entries if words(entry[column])[: index + 1] == prefix), None
                )
                if seen is not None:
                    lag = (seen - audio_end) * 1000
                    # Large negative alignments imply mismatch (lyrics, recognition errors, bad segmentation).
                    if lag >= -200:
                        destination.append(lag)
    return {
        "method": "MMS independent CTC alignment; recognized words, confidence>=0.5; no human reference",
        "timing_uncertainty_ms": 150,
        "accepted_words": accepted,
        "rejected_words": rejected,
        "recognition_word_end_to_api": stats(partial_lags),
        "translation_word_end_to_api": stats(translated_lags),
        "overlay_additional_budget_ms": 150,
        "strict_1s_verified": False,
        "note": "Automatic timing estimate only; browser/OBS rendering not measured and errors/unrecognized "
        "words cannot be counted as passing. Negative lag within 200ms reflects alignment uncertainty.",
    }
