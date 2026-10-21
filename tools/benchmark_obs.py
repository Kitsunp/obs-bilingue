"""Play a local video through real libobs + the native filter at 1x.

Only aggregate metrics are saved. Captions remain in memory for alignment.
The optional CTC alignment supplies an automatic English timing estimate,
not a human reference or a quality assessment of translations.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
from pathlib import Path

import httpx
import numpy as np
import psutil
from obs_test_paths import engine_base_url, test_environment

ROOT = Path(__file__).resolve().parents[1]


def summary(values):
    if not values:
        return {"samples": 0}
    return {
        "samples": len(values),
        "mean": round(float(np.mean(values)), 2),
        "p95": round(float(np.percentile(values, 95)), 2),
        "max": round(max(values), 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--start-seconds", type=float, default=300)
    parser.add_argument("--source", action="store_true", help="Probar la fuente nativa sin filtro de audio")
    parser.add_argument(
        "--translation",
        action="store_true",
        help="Activar y desactivar la traduccion opcional durante la prueba",
    )
    parser.add_argument("--report", type=Path, default=ROOT / "benchmark.json")
    parser.add_argument(
        "--align", action="store_true", help="Alineacion acustica automatica posterior en CPU"
    )
    args = parser.parse_args()
    if not args.video.is_file() or not 10 <= args.seconds <= 14400:
        raise SystemExit("Video inexistente o duracion fuera de 10..14400 segundos")
    env = test_environment(ROOT)
    if args.source:
        env["BILINGUE_SOURCE_TEST"] = "1"
    if args.translation:
        env["BILINGUE_TRANSLATE_TEST"] = "1"
    # Cap the test engine to 16 logical processors, representing at most 8 SMT cores.
    # This is not a replacement for benchmarking a different physical CPU.
    client = httpx.Client(base_url=engine_base_url(ROOT), timeout=2)
    health = client.get("/health").json()
    if not health["ready"]:
        raise SystemExit("Inicia el motor y espera a que este listo")
    process = psutil.Process(health["pid"])
    affinity = list(range(min(16, psutil.cpu_count())))
    process.cpu_affinity(affinity)
    for child in process.children(recursive=True):
        child.cpu_affinity(affinity)
    samples, updates, partials, translation_ages = [], [], [], []
    classification_times, observed_languages = [], set()
    seen_partial, seen_translation = set(), set()
    errors = set()
    before = time.monotonic()
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    host = subprocess.Popen(
        [
            str(ROOT / "build" / "obs-test-host.exe"),
            str(args.video),
            str(args.seconds),
            str(ROOT / "build" / "obs-bilingue.dll"),
            str(args.start_seconds),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    playback = {"media_start_seconds": args.start_seconds}

    def drain_output():
        for line in iter(host.stdout.readline, b""):
            try:
                value = json.loads(line)
                if "start_media_ms" in value:
                    playback["media_start_seconds"] = value["start_media_ms"] / 1000
            except (ValueError, UnicodeDecodeError):
                pass

    output_thread = threading.Thread(target=drain_output, daemon=True)
    output_thread.start()
    last_revision, last_report = -1, before
    connected = False
    try:
        while host.poll() is None:
            now = time.monotonic()
            data = client.get("/api/state").json()
            metrics = data["metrics"]
            connected |= data["status"] == "Recibiendo audio"
            if data["error"]:
                errors.add(data["error"])
            if data["revision"] != last_revision:
                if "language_classify_ms" in metrics:
                    classification_times.append(metrics["language_classify_ms"])
                observed_languages.add(data.get("source_language", "und"))
                last_revision = data["revision"]
                # Bounded diagnostic sample, no transcript file or persistent history.
                updates.append(
                    (
                        now,
                        data["segment"],
                        data["source"],
                        data["translation_source"],
                        data.get("segment_audio_start_seconds", 0),
                    )
                )
                if len(updates) > 5000:
                    del updates[:1000]
            key = (data["segment"], metrics.get("first_partial_ms"))
            if data["source"] and key not in seen_partial and key[1] is not None:
                partials.append(key[1])
                seen_partial.add(key)
            key = (data["segment"], data["translation_source"])
            if key[1] and key not in seen_translation:
                translation_ages.append(metrics.get("translation_age_ms", 0))
                seen_translation.add(key)
            if not samples or now - samples[-1]["at"] >= 1:
                samples.append({"at": now, "translation_enabled": data["translation_enabled"], **metrics})
            if now - last_report >= 15:
                print(
                    json.dumps(
                        {
                            "elapsed_s": round(now - before),
                            "gpu_mean": metrics.get("gpu_mean_percent"),
                            "rss_mib": metrics.get("rss_mib"),
                            "partial_ms": metrics.get("first_partial_ms"),
                            "translation_age_ms": metrics.get("translation_age_ms"),
                            "drops": metrics.get("audio_drops"),
                        }
                    ),
                    flush=True,
                )
                last_report = now
            time.sleep(0.04)
    finally:
        if host.poll() is None:
            host.terminate()
        host.wait(timeout=10)
        client.close()
    gpu = [x["gpu_percent"] for x in samples if "gpu_percent" in x]
    rss = [x["rss_mib"] for x in samples if "rss_mib" in x]
    report = {
        "video": args.video.name,
        "media_start_seconds": playback["media_start_seconds"],
        "playback": "1x via OBS libobs + obs-ffmpeg + native Bilingue "
        + ("source" if args.source else "filter"),
        "duration_seconds": round(time.monotonic() - before, 2),
        "obs_host_exit": host.returncode,
        "audio_connected": connected,
        "translation_model_loaded_samples": sum(bool(x.get("translation_model_loaded")) for x in samples),
        "translation_enabled_samples": sum(bool(x.get("translation_enabled")) for x in samples),
        "translation_model_loaded_at_end": bool(samples[-1].get("translation_model_loaded"))
        if samples
        else False,
        "cpu_affinity_logical_processors": 16,
        "configured_omp_threads": 4,
        "backend": health["asr_backend"],
        "gpu_global_percent": summary(gpu),
        "rss_mib": summary(rss),
        "first_partial_since_stream_open_ms": summary(partials),
        "translation_after_asr_job_ms": summary(translation_ages),
        "language_classifier_compute_ms": summary(classification_times),
        "observed_languages": sorted(observed_languages),
        "cpu_cores_used": summary([x["cpu_cores_used"] for x in samples if "cpu_cores_used" in x]),
        "caption_revisions": len(updates),
        "errors": sorted(errors),
        "audio_drops": samples[-1].get("audio_drops") if samples else None,
        "acoustic_translation_latency_verified": False,
        "important": "Partial onset and ASR-to-translation age do not prove <=1s acoustic latency. "
        "No human transcript/timestamps were supplied. No hours-long inference claim from this test.",
    }
    if args.align:
        from align_latency import align_updates

        origin = samples[-1].get("audio_connected_monotonic", before)
        report["automatic_acoustic_alignment"] = align_updates(
            args.video, updates, origin, playback["media_start_seconds"]
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
