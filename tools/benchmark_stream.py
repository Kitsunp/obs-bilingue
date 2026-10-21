"""Isolated 1x libobs benchmark. References are evaluated only in the parent.

No reference text, lyrics or language hints are sent to the recognizer process.
Reports contain aggregate metrics only. Does not control the user's OBS instance.
"""

import argparse
import collections
import hashlib
import json
import math
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from pathlib import Path

import httpx
from obs_test_paths import test_environment
from streaming_metrics import StreamingMetric

ROOT = Path(__file__).resolve().parents[1]


def distance(reference, actual):
    previous = list(range(len(actual) + 1))
    for i, token in enumerate(reference, 1):
        row = [i]
        for j, candidate in enumerate(actual, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (token != candidate)))
        previous = row
    return previous[-1]


def normalize(text):
    return "".join(c.lower() if c.isalnum() else " "
                   for c in unicodedata.normalize("NFKC", text))


def free_ports():
    sockets = [socket.socket() for _ in range(3)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", type=Path)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--quality", choices=["LQ", "MQ", "HQ"], default="MQ")
    parser.add_argument("--keep-duplicate-interims", action="store_true")
    parser.add_argument("--zero-idle-seconds", type=float,
                        help="Comparar cierre tras ceros digitales; 0 conserva el flujo continuo")
    parser.add_argument("--reference", type=Path, help="Plain text or LRC for this exact recording")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--nemo-model", type=Path,
                        help="GGUF experimental, solo para el motor aislado de esta prueba")
    parser.add_argument("--exact-audio-window", action="store_true",
                        help="Extraer solo el audio del tramo a PCM antes de reproducirlo en OBS")
    parser.add_argument("--source", action="store_true", help="Probar fuente completa y navegador aislados")
    parser.add_argument("--worker-ports", nargs=3, type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.nemo_model and (not args.nemo_model.is_file() or args.nemo_model.suffix.lower() != ".gguf"):
        parser.error("--nemo-model debe indicar un archivo GGUF existente")
    if args.zero_idle_seconds is not None and (
            not math.isfinite(args.zero_idle_seconds) or not 0 <= args.zero_idle_seconds <= 30):
        parser.error("--zero-idle-seconds debe ser finito, entre 0 y 30")
    if args.worker_ports:
        sys.path.insert(0, str(ROOT))
        import uvicorn

        from engine.server import create_app, read_config
        config = read_config()
        if args.nemo_model:
            if config["asr_backend"] != "nemo_cuda":
                parser.error("La prueba GGUF requiere asr_backend=nemo_cuda")
            config["nemo_model"] = str(args.nemo_model.resolve())
        config.update(zip(("http_port", "audio_port", "translation_port"), args.worker_ports, strict=True))
        config.update(audio_resample_quality=args.quality,
                      native_deduplicate_interims=not args.keep_duplicate_interims)
        if args.zero_idle_seconds is not None:
            minimum_tail = config["endpoint_seconds"] + (config["nemo_right_context"] + 1) * .08
            if 0 < args.zero_idle_seconds < minimum_tail:
                parser.error("El cierre digital debe cubrir el endpoint y el contexto derecho")
            config["native_zero_idle_seconds"] = args.zero_idle_seconds
        app = create_app(config)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=config["http_port"],
                                              access_log=False, log_level="error"))
        app.state.server = server
        server.run()
        return
    if not args.media.is_file() or not 5 <= args.seconds <= 600 or args.start < 0 or args.report is None:
        parser.error("Indica un archivo local, --report y una duracion de 5..600 segundos")
    reference = ""
    if args.reference:
        reference = args.reference.read_text(encoding="utf-8")
        if args.reference.suffix.lower() == ".lrc":
            lines = []
            for line in reference.splitlines():
                match = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)", line)
                if match and args.start <= int(match[1]) * 60 + float(match[2]) < args.start + args.seconds:
                    lines.append(match[3])
            reference = " ".join(lines)
    ports = free_ports()
    env = test_environment(ROOT)
    env["BILINGUE_TEST_AUDIO_PORT"] = str(ports[1])
    env["BILINGUE_TEST_HTTP_PORT"] = str(ports[0])
    env.pop("BILINGUE_SOURCE_TEST", None)
    env["BILINGUE_TEST_TAIL_SECONDS"] = "2"
    isolated_data = tempfile.TemporaryDirectory(prefix="caption-benchmark-", dir=ROOT / ".test-runtime")
    data_folder = Path(isolated_data.name)
    (data_folder / "config.json").write_text(json.dumps({"http_port": ports[0], "audio_port": ports[1]}))
    (data_folder / "runtime.json").write_text(json.dumps({"root": str(data_folder)}))
    env["BILINGUE_TEST_PLUGIN_DATA"] = str(data_folder)
    if args.source:
        env["BILINGUE_SOURCE_TEST"] = "1"
    playback_media, playback_start = args.media.resolve(), args.start
    if args.exact_audio_window:
        env["BILINGUE_TEST_DEFER_MEDIA"] = "1"
        playback_media, playback_start = data_folder / "input.wav", 0
        subprocess.run(["ffmpeg", "-v", "error", "-ss", str(args.start), "-i", str(args.media.resolve()),
                        "-t", str(args.seconds), "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_f32le",
                        str(playback_media)], check=True, timeout=90,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    command = [sys.executable, str(Path(__file__).resolve()), str(args.media.resolve()),
               "--worker-ports", *map(str, ports), "--quality", args.quality]
    if args.keep_duplicate_interims:
        command.append("--keep-duplicate-interims")
    if args.zero_idle_seconds is not None:
        command.extend(["--zero-idle-seconds", str(args.zero_idle_seconds)])
    if args.nemo_model:
        command.extend(["--nemo-model", str(args.nemo_model.resolve())])
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    worker = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, creationflags=flags)
    host = None
    host_reader = None
    host_events = collections.deque(maxlen=650)
    resource_metrics = {key: StreamingMetric() for key in (
        "gpu_percent", "rss_mib", "cpu_cores_used", "asr_decode_ms",
        "audio_queue_ms", "resampler_pending_ms")}
    captions = collections.OrderedDict()
    row_births = []
    changed_hypotheses = line_break_hypotheses = repeated_space_hypotheses = 0
    languages, errors = set(), set()
    peak_drops = 0
    metrics = {}
    client = httpx.Client(base_url=f"http://127.0.0.1:{ports[0]}", timeout=1)
    try:
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            try:
                health = client.get("/health").json()
                if health["error"]:
                    raise RuntimeError(health["error"])
                if health["ready"]:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.1)
        else:
            raise TimeoutError("El motor aislado no inicio")
        host = subprocess.Popen([str(ROOT / "build/obs-test-host.exe"), str(playback_media),
                                 str(args.seconds), str(ROOT / "build/obs-bilingue.dll"),
                                 str(playback_start)],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                creationflags=flags)
        def read_host_events():
            for line in iter(host.stdout.readline, b""):
                if line.startswith(b"{"):
                    try:
                        host_events.append(json.loads(line))
                    except ValueError:
                        pass
        host_reader = threading.Thread(target=read_host_events, daemon=True)
        host_reader.start()
        playback_started = time.monotonic()
        deadline = time.monotonic() + args.seconds + 20
        while host.poll() is None:
            if time.monotonic() > deadline:
                raise TimeoutError("El host aislado excedio su plazo")
            state = client.get("/api/state").json()
            metrics = state["metrics"]
            for key, accumulator in resource_metrics.items():
                accumulator.add(metrics.get(key))
            peak_drops = max(peak_drops, metrics.get("audio_drops", 0))
            if state["error"]:
                errors.add(state["error"])
            for row in state["rows"]:
                if row["source"]:
                    identity = (row["id"], row["epoch"])
                    if identity not in captions:
                        row_births.append({
                            "first_seen_seconds": round(time.monotonic() - playback_started, 3),
                            "flow_group": row.get("flow_group", row["id"]),
                            "source_audio_start_seconds": state["segment_audio_start_seconds"]
                            if row["id"] == state["segment"] else None})
                    if captions.get(identity) != row["source"]:
                        changed_hypotheses += 1
                        line_break_hypotheses += bool(re.search(r"[\r\n]", row["source"]))
                        repeated_space_hypotheses += bool(re.search(r" {2,}|\t", row["source"]))
                    captions[identity] = row["source"]
                    languages.update(p["language"] for p in row.get("spans", []))
            if len(captions) > 256:
                raise RuntimeError("Demasiados segmentos para la prueba acotada")
            time.sleep(.1)
        last_metrics = metrics
        host_reader.join(timeout=2)
        renderer_port_verified = any(event.get("renderer_http_port_matches_engine") is True
                                     for event in host_events)
        if args.source and not renderer_port_verified:
            errors.add("El navegador aislado no confirmo el puerto del motor de prueba")
        actual = " ".join(captions.values())
        model_hash = None
        if args.nemo_model:
            with args.nemo_model.open("rb") as model_file:
                model_hash = hashlib.file_digest(model_file, "sha256").hexdigest()
        report = {"path": "libobs + native capture + full Python engine; 1x; isolated ports/profile",
                  "experimental_model": str(args.nemo_model.resolve()) if args.nemo_model else None,
                  "experimental_model_sha256": model_hash,
                  "native_source_and_browser": args.source,
                  "exact_pcm_audio_window": args.exact_audio_window,
                  "renderer_http_port_matches_engine": renderer_port_verified if args.source else None,
                  "quality": args.quality, "skip_duplicate_interims": not args.keep_duplicate_interims,
                  "source_start_seconds": args.start, "requested_seconds": args.seconds,
                  "audio_received_seconds": last_metrics.get("audio_received_seconds", 0),
                  "audio_samples_submitted": last_metrics.get("asr_samples_submitted", 0),
                  "zero_idle_seconds": last_metrics.get("asr_zero_idle_seconds"),
                  "zero_samples_skipped": last_metrics.get("asr_zero_samples_skipped", 0),
                  "zero_idle_closes": last_metrics.get("asr_zero_idle_closes", 0),
                  "duplicate_interims_skipped": last_metrics.get("asr_duplicate_interims_skipped", 0),
                  "asr_results": last_metrics.get("asr_result_updates", 0),
                  "audio_drops": peak_drops,
                  "caption_segments": len(captions), "detected_languages": sorted(languages),
                  "segment_character_counts": [len(normalize(text).replace(" ", ""))
                                               for text in captions.values()],
                  "distinct_normalized_segments": len({normalize(text).replace(" ", "")
                                                       for text in captions.values()}),
                  "layout_diagnostics": {"sampled_changed_hypotheses": changed_hypotheses,
                                         "display_flow_groups": len({
                                             row["flow_group"] for row in row_births}),
                                         "hypotheses_with_line_breaks": line_break_hypotheses,
                                         "hypotheses_with_repeated_spaces": repeated_space_hypotheses,
                                         "row_births": row_births},
                  "errors": sorted(errors), "host_exit_code": host.returncode,
                  "resources": {key: accumulator.summary() for key, accumulator in resource_metrics.items()},
                  "reference_used_only_after_recognition": bool(reference),
                  "limitations": "GPU is global and includes other apps. LRC timings/lyrics are external and "
                                  "may differ from this recording; metrics are approximate until verified. "
                                  "No acoustic-to-screen delay measured. No translation enabled in this run."}
        if reference:
            ref, hyp = normalize(reference), normalize(actual)
            ref_chars, hyp_chars = ref.replace(" ", ""), hyp.replace(" ", "")
            report.update(reference_words=len(ref.split()), recognized_words=len(hyp.split()),
                          approximate_wer=round(distance(ref.split(), hyp.split()) /
                                                 max(1, len(ref.split())), 3),
                          approximate_cer=round(distance(ref_chars, hyp_chars) / max(1, len(ref_chars)), 3))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
    finally:
        if host and host.poll() is None:
            host.terminate()
            host.wait(timeout=5)
        if host_reader:
            host_reader.join(timeout=2)
        try:
            client.post("/api/stop")
            worker.wait(timeout=10)
        except (httpx.HTTPError, subprocess.TimeoutExpired):
            worker.terminate()
            worker.wait(timeout=5)
        client.close()
        isolated_data.cleanup()


if __name__ == "__main__":
    main()
