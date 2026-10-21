"""Silent, single-instance entry point used by the OBS source."""

import ctypes
import json
import os
import runpy
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil


def owns_pid(process, pid):
    if pid == process.pid:
        return True
    try:
        return any(parent.pid == process.pid for parent in psutil.Process(pid).parents())
    except psutil.Error:
        return False


def terminate_worker(process):
    # Windows venv launchers can redirect to a second pythonw process.
    try:
        children = psutil.Process(process.pid).children(recursive=True)
    except psutil.Error:
        children = []
    for child in reversed(children):
        try:
            child.terminate()
        except psutil.Error:
            pass
    if process.poll() is None:
        process.terminate()
    process.wait(timeout=5)


def restart_reason(health, uptime, unavailable_seconds, config, started_ready=False):
    """A silent transcript is valid; only dead/stalled execution triggers recovery."""
    timeout = config["asr_stall_timeout_seconds"]
    if health is None:
        startup = config["asr_startup_timeout_seconds"]
        limit = timeout if started_ready else startup
        return "health_unavailable" if unavailable_seconds > limit else None
    if health.get("stopping"):
        return None
    if health.get("ready"):
        if not health.get("recognizer_alive", True):
            return "recognizer_stopped"
        if health.get("recognizer_progress_age_seconds", 0) > timeout:
            return "recognizer_stalled"
    elif not health.get("error") and uptime > config["asr_startup_timeout_seconds"]:
        return "initialization_stalled"
    return None


def probe(url):
    try:
        with urllib.request.urlopen(url, timeout=0.4) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return None


def supervise(root, config):
    url = f"http://127.0.0.1:{config['http_port']}/health"
    recoveries = 0
    while True:
        environment = dict(os.environ, BILINGUE_RECOVERY_COUNT=str(recoveries))
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "engine.launch", "--worker"], cwd=root, env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        started = available = time.monotonic()
        started_ready = False
        try:
            while process.poll() is None:
                health = probe(url)
                now = time.monotonic()
                if health is not None and owns_pid(process, health.get("pid")):
                    available = now
                    started_ready |= bool(health.get("ready"))
                else:
                    health = None
                if restart_reason(health, now - started, now - available, config, started_ready):
                    # Only our child is terminated. OBS and its settings are untouched.
                    terminate_worker(process)
                    break
                time.sleep(config["supervisor_poll_seconds"])
        finally:
            if process.poll() is None:
                terminate_worker(process)
        if process.returncode == 0:
            return
        recoveries += 1
        time.sleep(config["asr_error_retry_seconds"])


def main():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    if "--worker" in sys.argv:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w")
        runpy.run_module("engine.server", run_name="__main__")
        return
    # A manual/development engine may already own the port without our mutex.
    if probe(f"http://127.0.0.1:{config['http_port']}/health") is not None:
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    ctypes.set_last_error(0)
    mutex = kernel.CreateMutexW(None, False, f"Local\\OBS_Bilingue_Engine_{config['http_port']}")
    if not mutex:
        raise OSError(ctypes.get_last_error(), "No se pudo reservar el motor local")
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(mutex)
        return
    try:
        # pythonw intentionally has no console; logging still needs valid streams.
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w")
        for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
            os.environ[key] = str(config["cpu_threads"])
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", BILINGUE_MANAGED="1")
        supervise(root, config)
    finally:
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
