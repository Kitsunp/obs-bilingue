"""Exercise OBS's real show/hide lifecycle; retain only aggregate evidence."""

import argparse
import json
import subprocess
import threading
import time
from pathlib import Path

import httpx
import psutil
from obs_test_paths import engine_base_url, test_environment

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--report", type=Path, default=ROOT / "verification" / "visibility.json")
    args = parser.parse_args()
    client = httpx.Client(base_url=engine_base_url(ROOT), timeout=0.3)
    try:
        client.get("/health").raise_for_status()
    except httpx.HTTPError:
        pass
    else:
        raise SystemExit("La prueba necesita empezar con el motor apagado y sin otra fuente activa")
    env = test_environment(ROOT)
    env.update(BILINGUE_SOURCE_TEST="1", BILINGUE_VISIBILITY_TEST="1")
    host = subprocess.Popen(
        [
            str(ROOT / "build" / "obs-test-host.exe"),
            str(args.video),
            "42",
            str(ROOT / "build" / "obs-bilingue.dll"),
            "300",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    playback = {"elapsed": 0.0}
    events, samples = [], []
    source_info = {}

    def drain():
        for line in iter(host.stdout.readline, b""):
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if "elapsed_ms" in value:
                playback["elapsed"] = value["elapsed_ms"] / 1000
            if "visible" in value:
                events.append({**value, "received": time.monotonic()})
            if "source_creation_ms" in value:
                source_info.update(value)

    threading.Thread(target=drain, daemon=True).start()
    deadline = time.monotonic() + 65
    known_pids = set()
    worker_pids = set()
    try:
        while host.poll() is None and time.monotonic() < deadline:
            row = {"elapsed": playback["elapsed"], "ready": False, "text": False}
            try:
                health = client.get("/health").json()
                row.update(ready=health["ready"], managed=health["managed"], pid=health["pid"])
                worker_pids.add(health["pid"])
                known_pids.add(health["pid"])
                try:
                    for parent in psutil.Process(health["pid"]).parents():
                        if "engine.launch" in parent.cmdline():
                            known_pids.add(parent.pid)
                except psutil.Error:
                    pass
                state = client.get("/api/state").json()
                row.update(text=bool(state["source"]), error=bool(state["error"]), **state["metrics"])
            except (httpx.HTTPError, ValueError):
                pass
            row["engine_process_exists"] = any(psutil.pid_exists(pid) for pid in known_pids)
            samples.append(row)
            if len(samples) > 320:
                raise RuntimeError("Limite de muestras de prueba superado")
            time.sleep(0.25)
        if host.poll() is None:
            host.terminate()
            raise RuntimeError("El host no termino en el tiempo previsto")
        host.wait(timeout=5)
    finally:
        if host.poll() is None:
            host.terminate()
        client.close()

    def window(start, end):
        return [row for row in samples if start <= row["elapsed"] < end]

    initial, first_on, first_off = window(0, 4), window(8, 14), window(19, 22)
    second_on, second_off = window(26, 34), window(39, 42)
    checks = {
        "hidden_initially_no_engine": bool(initial) and not any(r["ready"] for r in initial),
        "first_show_starts_and_captions": any(r["ready"] and r["text"] for r in first_on),
        "first_hide_releases_engine_process": bool(first_off)
        and not any(r["engine_process_exists"] for r in first_off),
        "second_show_recovers_and_captions": any(r["ready"] and r["text"] for r in second_on),
        "second_hide_releases_engine_process": bool(second_off)
        and not any(r["engine_process_exists"] for r in second_off),
        "managed_start": all(r.get("managed", True) for r in samples),
        "clean_obs_shutdown": host.returncode == 0,
        "no_engine_errors": not any(r.get("error") for r in samples),
        "native_language_controls": source_info.get("language_ui_verified", False),
    }
    active_rss = [r["rss_mib"] for r in samples if r["ready"] and "rss_mib" in r]
    report = {
        "playback": "OBS libobs + obs-ffmpeg + native source + obs-browser, 1x, no stream/recording",
        "video": args.video.name,
        "checks": checks,
        "passed": all(checks.values()),
        "source_creation_ms": source_info.get("source_creation_ms"),
        "managed_engine_instances": len(worker_pids),
        "active_engine_rss_mib_max": max(active_rss) if active_rss else None,
        "visibility_events": [{k: v for k, v in e.items() if k != "received"} for e in events],
        "samples": len(samples),
        "important": "Lifecycle/controls test only; no <=1s acoustic latency or hours-long inference claim.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
