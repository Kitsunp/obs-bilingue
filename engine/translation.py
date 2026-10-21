"""Quantized translator. Bounded final/partial jobs and expiring context."""

from __future__ import annotations

import secrets
import subprocess
import threading
import time
from pathlib import Path

import httpx

from .core import Context


class Translator:
    def __init__(self, root: Path, config, state, mailbox):
        self.root, self.config, self.state, self.mailbox = root, config, state, mailbox
        self.context = Context(ttl=config["context_ttl_seconds"])
        self.stop = threading.Event()
        self.process = None
        self.thread = threading.Thread(target=self.run, name="translation", daemon=True)
        self.api_key = secrets.token_urlsafe(32)
        self.client = httpx.Client(
            base_url=f"http://127.0.0.1:{config['translation_port']}",
            timeout=10,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        self.completed_segment = -1
        self.last_text = ""
        self.last_segment = -1
        self.last_row_epoch = None
        self.last_started = 0.0
        self.last_activity = time.monotonic()
        self.cache_cleared = True

    def start(self):
        # Start only the coordinator. Subtitling never needs a translation model.
        self.thread.start()

    def load_model(self):
        binary = self.root / "runtime" / "llama" / "llama-server.exe"
        if not binary.is_file():
            raise RuntimeError("Falta runtime/llama/llama-server.exe; ejecuta PREPARAR.ps1")
        args = [
            str(binary),
            "--model",
            str(self.root / self.config["translation_model"]),
            "--host",
            "127.0.0.1",
            "--api-key",
            self.api_key,
            "--port",
            str(self.config["translation_port"]),
            "--ctx-size",
            str(self.config["translation_context_tokens"]),
            "--parallel",
            "1",
            "--threads",
            str(self.config["cpu_threads"]),
            "--threads-batch",
            str(self.config["cpu_threads"]),
            "--n-gpu-layers",
            str(self.config["translation_gpu_layers"]),
            "--batch-size",
            "256",
            "--ubatch-size",
            "128",
            "--no-webui",
            "--no-warmup",
            "--log-disable",
            "--cache-ram",
            "0",
        ]
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        self.process = subprocess.Popen(
            args,
            cwd=binary.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and not self.stop.is_set() and self.state.translation_enabled:
            if self.process.poll() is not None:
                raise RuntimeError(f"llama-server termino con codigo {self.process.returncode}")
            try:
                if self.client.get("/health").status_code == 200:
                    self.state.metrics["translation_model_loaded"] = True
                    return True
            except httpx.HTTPError:
                pass
            self.stop.wait(0.2)
        if self.stop.is_set() or not self.state.translation_enabled:
            return False
        raise RuntimeError("El traductor no termino de cargar en 90 segundos")

    def translate(self, text, target, context):
        language = {"es": "Spanish", "en": "English"}[target]
        prompt = ""
        if context:
            prompt += f"[Background Information]\n{context}\n\n"
        prompt += (
            f"Translate the following text into {language}. "
            "Only output the translated result without any additional explanation. "
            "The source may contain multiple languages. Preserve parts already in the target language. "
            "Translate only [Source Text]; do not repeat background information.\n\n"
            f"[Source Text]\n{text}"
        )
        response = self.client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": self.config["translation_max_tokens"],
                "cache_prompt": True,
                "id_slot": 0,
            },
        )
        response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]
        self.state.metrics["translation_truncated"] = choice.get("finish_reason") == "length"
        return choice["message"]["content"].strip()

    def eligible(self, job):
        return bool(job.text and (job.final or time.monotonic() - job.created <= 2)
                    and self.state.translation_is_current(job.segment, job.text, job.row_epoch)
                    and self.state.translation_required(job.segment))

    def run(self):
        while not self.stop.is_set():
            job = self.mailbox.get()
            if not self.state.translation_enabled:
                if self.process is not None:
                    self.unload_model()
                self.last_text = ""
                self.last_segment = self.completed_segment = -1
                self.last_row_epoch = None
                continue
            if job is None:
                if (
                    not self.cache_cleared
                    and time.monotonic() - self.last_activity > self.config["context_ttl_seconds"]
                ):
                    self.context.clear()
                    for slot in (0,):
                        try:
                            self.client.post(
                                "/completion",
                                json={"prompt": "", "n_predict": 0, "cache_prompt": False, "id_slot": slot},
                            ).raise_for_status()
                        except httpx.HTTPError:
                            pass
                    self.last_text = ""
                    self.cache_cleared = True
                continue
            if not self.eligible(job):
                continue
            if (job.segment == self.last_segment and job.row_epoch == self.last_row_epoch
                    and job.text == self.last_text):
                if job.final and self.completed_segment != job.segment:
                    self.context.add(job.text)
                    self.completed_segment = job.segment
                continue
            # Coalesce revisions to avoid translating every token.
            delay = max(
                0, self.config["translation_interval_seconds"] - (time.monotonic() - self.last_started)
            )
            if self.stop.wait(delay):
                break
            newer = self.mailbox.get(timeout=0) if not job.final else None
            if newer is not None:
                job = newer
            if not self.eligible(job):
                continue
            started = time.monotonic()
            self.last_started = started
            self.last_activity = started
            self.cache_cleared = False
            try:
                if self.process is None or self.process.poll() is not None:
                    if not self.load_model():
                        self.unload_model()
                        continue
                    # Loading can take seconds. Consume only the latest bounded revision.
                    newer = self.mailbox.get(timeout=0) if not job.final else None
                    if newer is not None:
                        job = newer
                    if not self.eligible(job):
                        continue
                context = self.context.text()
                values = {
                    lang: self.translate(job.text, lang, context)
                    for lang in ("es",)
                }
                if not self.state.translation_enabled:
                    continue
                if not self.state.translated(job.segment, job.text, values, job.row_epoch):
                    continue
                self.state.metrics["translation_ms"] = round((time.monotonic() - started) * 1000)
                self.state.metrics["translation_age_ms"] = round((time.monotonic() - job.created) * 1000)
                self.last_text, self.last_segment = job.text, job.segment
                self.last_row_epoch = job.row_epoch
                if job.final and self.completed_segment != job.segment:
                    self.context.add(job.text)
                    self.completed_segment = job.segment
            except Exception as exc:
                self.state.error = f"Traduccion: {type(exc).__name__}: {str(exc)[:160]}"
                if self.process is None or self.process.poll() is not None:
                    self.unload_model()
                self.stop.wait(0.5)

    def unload_model(self):
        self.context.clear()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None
        self.cache_cleared = True
        self.state.metrics["translation_model_loaded"] = False

    def close(self):
        self.stop.set()
        self.mailbox.close()
        if self.thread.is_alive():
            self.thread.join(timeout=12)
        self.client.close()
        self.unload_model()
