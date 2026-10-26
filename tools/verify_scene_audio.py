"""Exercise internal-scene + global audio in a separate, small libobs process.

No ASR/model load, device capture, user profile or live OBS control is involved.
Only synthetic audio and aggregate routing metrics are retained.
"""
import argparse
import array
import json
import os
import socket
import struct
import subprocess
import threading
import time
import wave
from pathlib import Path

from obs_test_paths import find_obs_bin

ROOT = Path(__file__).resolve().parents[1]
HEADER = struct.Struct("<4sIIII")


def receive_exact(connection, size):
    data = bytearray()
    while len(data) < size:
        block = connection.recv(size - len(data))
        if not block:
            raise EOFError
        data.extend(block)
    return data


def exercise(plugin, folder, legacy_scene=False, individual=False, empty_track=False,
             visibility=False, scene_case="", seconds=6):
    started = time.monotonic()
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / "synthetic.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(struct.pack("<hh", 3277, 3277) * (48000 * 12))
    metrics = {"frames": 0, "peak": 0.0, "muted_interval_frames": 0, "zero_frames": 0,
               "quarter_volume_frames": 0, "two_inputs_frames": 0, "sequence_gaps": 0, "errors": []}
    if scene_case.startswith("routing-"):
        metrics.update(microphone_frames=0, timeline={})
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(0.3)
    stop = threading.Event()

    def collect():
        first_audio_at = None
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            with connection:
                connection.settimeout(2)
                previous_sequence = None
                try:
                    while not stop.is_set():
                        header = receive_exact(connection, HEADER.size)
                        magic, rate, count, sequence, flags = HEADER.unpack(header)
                        if magic == b"BLCF":
                            receive_exact(connection, count)
                        elif magic == b"BLCP":
                            continue
                        elif magic == b"BLC1":
                            assert rate == 48000 and 0 < count <= 2048
                            if (previous_sequence is not None and
                                    sequence != (previous_sequence + 1) & 0xFFFFFFFF):
                                metrics["sequence_gaps"] += 1
                            previous_sequence = sequence
                            values = array.array("f", receive_exact(connection, count * 4))
                            peak = max(abs(value) for value in values)
                            if "timeline" in metrics:
                                received_at = time.monotonic()
                                if first_audio_at is None:
                                    first_audio_at = received_at
                                # Handoffs discard old PCM. A sample-count clock would
                                # compress those gaps and move later assertions in time.
                                bucket = str(int((received_at - first_audio_at) * 10))
                                values_in_bucket = metrics["timeline"].setdefault(bucket, [])
                                values_in_bucket.append(round(peak, 6))
                                if .074 < peak < .076:
                                    metrics["microphone_frames"] += count
                            metrics["frames"] += count
                            metrics["peak"] = max(metrics["peak"], peak)
                            if 0.045 < peak < 0.055:
                                metrics["muted_interval_frames"] += count
                            if peak == 0:
                                metrics["zero_frames"] += count
                            if .024 < peak < .026:
                                metrics["quarter_volume_frames"] += count
                            if .124 < peak < .126:
                                metrics["two_inputs_frames"] += count
                        else:
                            raise ValueError("Invalid native packet")
                except (EOFError, TimeoutError, OSError):
                    pass
                except Exception as error:
                    metrics["errors"].append(type(error).__name__)

    thread = threading.Thread(target=collect, daemon=True)
    thread.start()
    environment = dict(os.environ)
    environment.update(BILINGUE_MIX_TEST="1", BILINGUE_SOURCE_TEST="1",
                       BILINGUE_TEST_AUDIO_PORT=str(listener.getsockname()[1]),
                       BILINGUE_TEST_CONFIG=str(folder / "profile"),
                       BILINGUE_TEST_PLUGIN_DATA=str(folder / "data"))
    (folder / "data").mkdir(exist_ok=True)
    (folder / "profile").mkdir(exist_ok=True)
    environment["PATH"] = str(find_obs_bin()) + os.pathsep + environment.get("PATH", "")
    if legacy_scene:
        environment["BILINGUE_TEST_LEGACY_SCENE"] = "1"
    if individual:
        environment["BILINGUE_TEST_INDIVIDUAL"] = "1"
    if empty_track:
        environment["BILINGUE_TEST_EMPTY_TRACK"] = "1"
    if visibility:
        environment["BILINGUE_TEST_MIX_VISIBILITY"] = "1"
    if scene_case:
        environment["BILINGUE_TEST_SCENE_CASE"] = scene_case
    if scene_case.startswith("routing-"):
        mic_audio = folder / "synthetic-microphone.wav"
        with wave.open(str(mic_audio), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(48000)
            output.writeframes(struct.pack("<hh", 2458, 2458) * (48000 * 12))
        environment["BILINGUE_TEST_MIC_AUDIO"] = str(mic_audio)
        environment["BILINGUE_TEST_APP_AUDIO"] = str(audio)
    try:
        command = [str(ROOT / "build/obs-test-host.exe"), str(audio), str(seconds), str(plugin.resolve())]
        result = subprocess.run(command,
                                cwd=ROOT, env=environment, capture_output=True, timeout=seconds + 30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as error:
        metrics["errors"].append("TimeoutExpired")
        result = subprocess.CompletedProcess(command, -1, error.stdout or b"", error.stderr or b"")
    finally:
        stop.set()
        thread.join(timeout=3)
        listener.close()
    # Private diagnostic logs, never source/release content.
    (folder / "host.log").write_bytes(result.stdout + result.stderr)
    reference = []
    for line in result.stdout.decode(errors="replace").splitlines():
        if line.startswith("{"):
            try:
                value = json.loads(line)
                if "reference_peak_scaled" in value:
                    reference.append(value)
            except ValueError:
                pass
    metrics["exit_code"] = result.returncode
    metrics["reference_peak"] = max((x["reference_peak_scaled"] / 1000000 for x in reference), default=0)
    metrics["reference_frames"] = max((x["reference_frames"] for x in reference), default=0)
    metrics["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--modern", type=Path, default=ROOT / "build/obs-bilingue.dll")
    args = parser.parse_args()
    root = ROOT / ".build/scene-audio-test"
    results = {
        "legacy_scene": exercise(args.legacy, root / "legacy", legacy_scene=True),
        "native_mix": exercise(args.modern, root / "modern"),
        "individual_source": exercise(args.modern, root / "individual", individual=True),
        "empty_track": exercise(args.modern, root / "empty-track", empty_track=True),
        "visibility": exercise(args.modern, root / "visibility", visibility=True),
    }
    (root / "results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    baseline = results["legacy_scene"]
    assert baseline["exit_code"] == 0 and baseline["reference_peak"] > 0.14
    assert baseline["frames"] == 0, "Expected the legacy scene-capture failure"
    for mode in ("native_mix", "individual_source", "empty_track", "visibility"):
        data = results[mode]
        assert data["exit_code"] == 0 and not data["errors"], mode
        assert data["frames"] > 48000 * 2.5, mode
    mixed = results["native_mix"]
    assert abs(mixed["peak"] - mixed["reference_peak"]) < 0.002
    assert mixed["muted_interval_frames"] > 48000
    assert abs(results["individual_source"]["peak"] - .1) < .002
    assert results["empty_track"]["peak"] == 0
    hidden = results["visibility"]
    assert abs(hidden["peak"] - hidden["reference_peak"]) < 0.002
    assert hidden["frames"] < mixed["frames"] - 48000
    assert hidden["muted_interval_frames"] < 24000


if __name__ == "__main__":
    main()
