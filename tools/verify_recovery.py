"""Suspend only the managed ASR worker; verify OBS continues and captions return."""

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
    args = parser.parse_args()
    client = httpx.Client(base_url=engine_base_url(ROOT), timeout=0.5)
    try:
        client.get("/health").raise_for_status()
    except httpx.HTTPError:
        pass
    else:
        raise SystemExit("Oculta la fuente activa antes de esta prueba aislada")
    env = test_environment(ROOT)
    env["BILINGUE_SOURCE_TEST"] = "1"
    host = subprocess.Popen([str(ROOT / "build/obs-test-host.exe"), str(args.video), "45",
                             str(ROOT / "build/obs-bilingue.dll"), "300"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    def drain():
        for _line in iter(host.stdout.readline, b""):
            pass

    threading.Thread(target=drain, daemon=True).start()
    started = time.monotonic()
    suspended = None
    fault_at = recovered_at = None
    initial_captions = recovered_captions = False
    recoveries = 0
    worker_pids = set()
    try:
        while host.poll() is None and time.monotonic() - started < 65:
            try:
                health = client.get("/health").json()
                if health["ready"]:
                    worker_pids.add(health["pid"])
                    state = client.get("/api/state").json()
                    if fault_at is None:
                        initial_captions |= bool(state["source"])
                        if time.monotonic() - started >= 8 and initial_captions:
                            worker = psutil.Process(health["pid"])
                            if not health["managed"] or "engine.launch" not in worker.cmdline():
                                raise RuntimeError("El proceso no es el worker de prueba administrado")
                            if Path(worker.cwd()).resolve() != ROOT.resolve():
                                raise RuntimeError("El worker no pertenece al proyecto")
                            worker.suspend()
                            suspended = worker
                            fault_at = time.monotonic()
                    elif health["pid"] != suspended.pid:
                        recoveries = health["recovery_count"]
                        if recovered_at is None:
                            recovered_at = time.monotonic()
                        recovered_captions |= bool(state["source"])
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.1)
        if host.poll() is None:
            raise RuntimeError("El host excedio el plazo de prueba")
        host.wait(timeout=5)
    finally:
        if suspended is not None and suspended.is_running():
            try:
                suspended.resume()
            except psutil.Error:
                pass
        if host.poll() is None:
            host.terminate()
            host.wait(timeout=5)
        client.close()
    report = {"backend": "nemo_cuda", "input": "real libobs source, local video at 1x",
              "fault": "managed ASR worker suspended, external supervisor left running",
              "initial_captions": initial_captions, "recovered_captions": recovered_captions,
              "recovery_count": recoveries, "worker_instances": len(worker_pids),
              "recovery_seconds": round(recovered_at - fault_at, 2) if recovered_at else None,
              "obs_host_exit": host.returncode,
              "passed": bool(initial_captions and recovered_captions and recoveries >= 1
                             and host.returncode == 0)}
    (ROOT / "verification/nemotron-native-recovery.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
