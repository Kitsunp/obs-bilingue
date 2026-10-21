"""Loopback-only audio transport and local browser overlays."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import struct
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import psutil
import soxr
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from .asr import Recognizer
from .core import RATE, AudioInbox, CaptionState, TranslationMailbox, level_db
from .language import parse_colors
from .style import validate_style
from .translation import Translator

ROOT = Path(__file__).resolve().parents[1]
HEADER = struct.Struct("<4sIIII")
LOG = logging.getLogger("bilingue")


def read_config(root=ROOT):
    cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
    if cfg["host"] != "127.0.0.1":
        raise ValueError("Este motor solo admite conexiones locales 127.0.0.1")
    for key in ("http_port", "audio_port", "translation_port"):
        if not isinstance(cfg[key], int) or not 1024 <= cfg[key] <= 65535:
            raise ValueError(f"Puerto invalido: {key}")
    if len({cfg[x] for x in ("http_port", "audio_port", "translation_port")}) != 3:
        raise ValueError("Los tres puertos deben ser diferentes")
    if not 1 <= cfg["cpu_threads"] <= 8:
        raise ValueError("cpu_threads debe estar entre 1 y 8")
    for key in (
        "audio_queue_seconds",
        "max_utterance_seconds",
        "subtitle_ttl_seconds",
        "context_ttl_seconds",
        "translation_interval_seconds",
        "silence_seconds",
        "asr_stall_timeout_seconds",
        "asr_startup_timeout_seconds",
        "supervisor_poll_seconds",
        "asr_error_retry_seconds",
        "audio_idle_seconds",
        "endpoint_seconds",
    ):
        if not isinstance(cfg[key], (int, float)) or not math.isfinite(cfg[key]) or cfg[key] <= 0:
            raise ValueError(f"Valor invalido: {key}")
    if cfg["audio_queue_seconds"] > 3 or cfg["max_utterance_seconds"] > 15:
        raise ValueError("Audio limitado a 3s de cola y 15s por sesion")
    if cfg["nemo_right_context"] not in (0, 3, 6, 13):
        raise ValueError("Contexto derecho no soportado por Nemotron")
    zero_idle = cfg.setdefault("native_zero_idle_seconds", 2.0)
    minimum_tail = cfg["endpoint_seconds"] + (cfg["nemo_right_context"] + 1) * .08
    if (type(zero_idle) not in (int, float) or not math.isfinite(zero_idle)
            or not (zero_idle == 0 or minimum_tail <= zero_idle <= 30)):
        raise ValueError("Pausa digital invalida: usa 0 o un tiempo que cubra endpoint y contexto derecho")
    if cfg["asr_backend"] not in ("onnx_cpu", "nemo_cuda", "torch"):
        raise ValueError("Backend ASR desconocido")
    if cfg.get("audio_resample_quality", "MQ") not in ("LQ", "MQ", "HQ"):
        raise ValueError("Calidad de remuestreo invalida")
    if not 0 <= cfg.get("vad_offset", 0.3) < cfg.get("vad_onset", 0.5) <= 1:
        raise ValueError("Umbrales VAD invalidos")
    threshold = cfg["span_language_min_confidence"]
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Umbral de idioma de fragmentos invalido")
    posterior = cfg["span_language_min_posterior"]
    ratio = cfg["span_language_margin_ratio"]
    if (type(posterior) not in (int, float) or not math.isfinite(posterior)
            or not 0 < posterior <= threshold or type(ratio) not in (int, float)
            or not math.isfinite(ratio) or ratio < 1):
        raise ValueError("Margen de evidencia de idioma invalido")
    for key in ("span_language_min_letters", "span_language_min_unspaced_letters"):
        if type(cfg[key]) is not int or not 1 <= cfg[key] <= 64:
            raise ValueError(f"Cantidad de letras invalida: {key}")
    return cfg


class Engine:
    def __init__(self, config):
        self.config = config
        self.inbox = AudioInbox(config["audio_queue_seconds"])
        self.state = CaptionState(config["subtitle_ttl_seconds"])
        self.mailbox = TranslationMailbox()
        self.recognizer = None
        self.translator = None
        self.audio_server = None
        self.active_writer = None
        self.connected = False
        self.idle_since = time.monotonic()
        self.on_idle_exit = None
        self.stopping = threading.Event()
        self.ready = False
        self.gpu_samples = []
        self.telemetry = threading.Thread(target=self.monitor, name="resource-monitor", daemon=True)

    def load(self):
        try:
            self.translator = Translator(ROOT, self.config, self.state, self.mailbox)
            self.translator.start()
            if self.config.get("asr_backend") == "nemo_cuda":
                from .asr_native import NativeRecognizer

                self.recognizer = NativeRecognizer(ROOT, self.config, self.inbox, self.state, self.mailbox)
            elif self.config.get("asr_backend") == "onnx_cpu":
                from .asr_onnx import OnnxRecognizer

                self.recognizer = OnnxRecognizer(ROOT, self.config, self.inbox, self.state, self.mailbox)
            else:
                self.recognizer = Recognizer(ROOT, self.config, self.inbox, self.state, self.mailbox)
            self.recognizer.start()
            self.state.status = "Listo; esperando audio de OBS"
            self.ready = True
            self.idle_since = time.monotonic()
            self.telemetry.start()
        except Exception as exc:
            self.state.status = "No se pudo iniciar"
            self.state.error = f"{type(exc).__name__}: {str(exc)[:320]}"
            LOG.error("Model initialization failed: %s", self.state.error)
            if self.translator:
                self.translator.close()

    async def audio(self, reader, writer):
        if self.connected or not self.ready:
            writer.close()
            await writer.wait_closed()
            return
        self.connected, self.active_writer = True, writer
        self.idle_since = time.monotonic()
        self.state.metrics["audio_connected_monotonic"] = time.monotonic()
        self.inbox.reset()
        self.state.clear()
        self.translator.context.clear()
        self.state.status = "Recibiendo audio"
        resampler, rate, previous = None, None, None
        try:
            while not self.stopping.is_set():
                raw = await asyncio.wait_for(reader.readexactly(HEADER.size), timeout=3)
                magic, next_rate, count, sequence, flags = HEADER.unpack(raw)
                if magic == b"BLCP" and next_rate == count == sequence == flags == 0:
                    continue
                if magic == b"BLCF":
                    if not 1 <= count <= 8192:
                        raise ValueError("Configuracion demasiado grande")
                    options = json.loads(
                        (await asyncio.wait_for(reader.readexactly(count), 1)).decode("utf-8")
                    )
                    colors, default = parse_colors(options["color_rules"], options["default_color"])
                    style = validate_style(options)
                    self.state.set_translation(options.get("translation_enabled", False))
                    with self.state.lock:
                        self.state.color_rules, self.state.default_color = colors, default
                        self.state.style = style
                        self.state.ttl = style["duration_seconds"]
                        self.state.revision += 1
                    continue
                if magic != b"BLC1" or not 8000 <= next_rate <= 192000 or not 1 <= count <= 2048:
                    raise ValueError("Paquete de audio invalido")
                payload = await asyncio.wait_for(reader.readexactly(count * 4), timeout=1)
                if rate != next_rate or (previous is not None and sequence != (previous + 1) & 0xFFFFFFFF):
                    if rate is not None:
                        self.state.metrics["transport_discontinuities"] = (
                            self.state.metrics.get("transport_discontinuities", 0) + 1
                        )
                        self.inbox.reset()
                        self.state.clear()
                        self.mailbox.clear()
                    rate = next_rate
                    resampler = soxr.ResampleStream(
                        rate, RATE, 1, dtype="float32",
                        quality=self.config.get("audio_resample_quality", "MQ"),
                    )
                previous = sequence
                audio = np.frombuffer(payload, dtype="<f4")
                if not np.isfinite(audio).all():
                    raise ValueError("Audio con valores no finitos")
                audio = np.zeros_like(audio) if flags & 1 else np.clip(audio, -1, 1)
                self.state.metrics["audio_muted"] = bool(flags & 1)
                self.state.metrics["audio_input_peak_db"] = round(
                    20 * math.log10(max(float(np.max(np.abs(audio))), 1e-8)), 1
                )
                output = resampler.resample_chunk(audio)
                if output.size:
                    self.inbox.put(output)
                    self.state.metrics["audio_input_db"] = round(level_db(output), 1)
                    self.state.metrics["audio_received_seconds"] = round(self.inbox.received / RATE, 2)
                    self.state.metrics["resampler_pending_ms"] = round(resampler.delay() * 1000 / RATE, 2)
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            pass
        except (ValueError, KeyError, TypeError, UnicodeError):
            self.state.error = "Paquete de audio o configuracion invalido"
        finally:
            self.connected, self.active_writer = False, None
            self.idle_since = time.monotonic()
            self.inbox.reset()
            self.mailbox.clear()
            self.translator.context.clear()
            self.state.clear()
            self.state.set_translation(False)
            self.state.status = "En pausa; fuente oculta o desconectada"
            writer.close()
            await writer.wait_closed()

    def should_idle_exit(self, now=None):
        now = time.monotonic() if now is None else now
        return (
            self.config.get("_managed", False)
            and self.ready
            and not self.connected
            and now - self.idle_since >= self.config.get("idle_shutdown_seconds", 3.0)
        )

    def monitor(self):
        from collections import deque

        samples = deque(maxlen=60)
        process = psutil.Process()
        child_processes = {}
        process.cpu_percent()
        while not self.stopping.is_set():
            if self.connected:
                self.idle_since = time.monotonic()
            if self.should_idle_exit() and self.on_idle_exit:
                self.ready = False
                self.on_idle_exit()
                break
            self.state.expire()
            try:
                flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                out = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=utilization.gpu,memory.used,power.draw",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    creationflags=flags,
                )
                values = [float(x.strip()) for x in out.stdout.splitlines()[0].split(",")]
                samples.append((time.monotonic(), *values))
                cutoff = time.monotonic() - self.config["gpu_target_window_seconds"]
                while samples and samples[0][0] < cutoff:
                    samples.popleft()
                mean = sum(x[1] for x in samples) / len(samples)
                self.state.metrics.update(
                    {
                        "gpu_percent": values[0],
                        "gpu_mean_percent": round(mean, 1),
                        "gpu_memory_mib_global": values[1],
                        "gpu_power_watts": values[2],
                        "gpu_within_target": mean <= self.config["gpu_target_percent"],
                        "gpu_window_samples": len(samples),
                    }
                )
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                self.state.metrics["gpu_monitor_available"] = False
            total_rss = process.memory_info().rss
            total_cpu = process.cpu_percent()
            try:
                current = {child.pid: child for child in process.children()}
                for pid, child in current.items():
                    if pid not in child_processes:
                        child_processes[pid] = child
                    total_rss += child_processes[pid].memory_info().rss
                    total_cpu += child_processes[pid].cpu_percent()
                child_processes = {pid: child for pid, child in child_processes.items() if pid in current}
            except psutil.Error:
                pass
            self.state.metrics.update(
                {
                    "rss_mib": round(total_rss / 2**20),
                    "cpu_cores_used": round(total_cpu / 100, 2),
                    "cpu_percent_of_8_cores": round(total_cpu / 8, 1),
                    "audio_queue_ms": round(self.inbox.samples / RATE * 1000),
                    "audio_drops": self.inbox.dropped,
                    "asr_cuda_mib": round(self.recognizer.torch.cuda.memory_reserved() / 2**20)
                    if hasattr(self.recognizer, "torch") and self.config["asr_device"] == "cuda"
                    else None,
                    "asr_backend": self.config["asr_backend"],
                    "cpu_threads_per_engine": None if self.config["asr_backend"] == "nemo_cuda"
                    else self.config["cpu_threads"],
                }
            )
            self.stopping.wait(1)

    def close(self):
        self.stopping.set()
        if self.recognizer:
            self.recognizer.close()
        if self.translator:
            self.translator.close()
        self.state.clear()


def create_app(config=None):
    config = config or read_config()
    engine = Engine(config)

    @asynccontextmanager
    async def lifespan(app):
        engine.audio_server = await asyncio.start_server(
            engine.audio, "127.0.0.1", config["audio_port"], limit=16384
        )
        loading = asyncio.create_task(asyncio.to_thread(engine.load))
        try:
            yield
        finally:
            engine.audio_server.close()
            await engine.audio_server.wait_closed()
            if engine.active_writer:
                engine.active_writer.close()
            await loading
            await asyncio.to_thread(engine.close)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "testserver"):
            return HTMLResponse("Host no permitido", status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'"
        )
        return response

    @app.get("/api/state")
    def state():
        return engine.state.snapshot()

    @app.get("/health")
    def health():
        recognizer = engine.recognizer
        return {
            "ready": engine.ready,
            "status": engine.state.status,
            "error": engine.state.error,
            "pid": os.getpid(),
            "managed": bool(config.get("_managed", False)),
            "asr_backend": config.get("asr_backend", "torch"),
            "vad_enabled": bool(config.get("nemo_vad_model")),
            "asr_right_context": config.get("nemo_right_context"),
            "language_analysis": "acoustic_and_text_spans_v3",
            "engine_version": "0.3.5",
            "connected": engine.connected,
            "stopping": engine.stopping.is_set(),
            "recognizer_alive": bool(recognizer and recognizer.thread.is_alive()),
            "recognizer_progress_age_seconds": round(
                time.monotonic() - getattr(recognizer, "last_progress", time.monotonic()), 2
            ),
            "recovery_count": int(os.environ.get("BILINGUE_RECOVERY_COUNT", "0")),
        }

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        return (ROOT / "web" / "control.html").read_text(encoding="utf-8")

    @app.post("/api/stop")
    async def stop(request: Request):
        origin = request.headers.get("origin")
        if origin and origin not in (
            f"http://127.0.0.1:{config['http_port']}",
            f"http://localhost:{config['http_port']}",
        ):
            raise HTTPException(403)
        if hasattr(app.state, "server"):
            app.state.server.should_exit = True
        return {"stopping": True}

    @app.get("/overlay/{lang}", response_class=HTMLResponse)
    def overlay(lang: str):
        if lang not in ("original", "es", "en"):
            raise HTTPException(404)
        return (ROOT / "web" / "overlay.html").read_text(encoding="utf-8").replace("__LANG__", lang)

    return app


if __name__ == "__main__":
    import uvicorn

    cfg = read_config()
    cfg["_managed"] = os.environ.get("BILINGUE_MANAGED") == "1"
    app = create_app(cfg)
    server = uvicorn.Server(
        uvicorn.Config(app, host=cfg["host"], port=cfg["http_port"], access_log=False, log_level="warning")
    )
    app.state.server = server
    app.state.engine.on_idle_exit = lambda: setattr(server, "should_exit", True)
    server.run()
