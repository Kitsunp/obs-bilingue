"""Test isolated source audio and registered source-hotkey callbacks.

All routing/key events stay inside the separate synthetic libobs host.
"""
import argparse
import json
import statistics
from pathlib import Path

from verify_scene_audio import ROOT, exercise


def middle_peak(result, second):
    values = [value for bucket, peaks in result["timeline"].items()
              if second * 10 + 3 <= int(bucket) < second * 10 + 7 for value in peaks]
    assert values, f"No PCM in second {second}"
    return statistics.median(values)


def main():
    cases = ("routing-source", "routing-window", "routing-toggle", "routing-missing-mic",
             "routing-hidden", "routing-ambiguous", "routing-left")
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", type=Path, default=ROOT / "build/obs-bilingue.dll")
    parser.add_argument("--case", choices=cases, action="append", help="Run only the chosen case(s)")
    args = parser.parse_args()
    root = ROOT / ".build/routing-test"
    results = {}
    for case in args.case or cases:
        result = exercise(args.plugin, root / case, scene_case=case, seconds=10)
        (root / case / "result.json").write_text(json.dumps(result, indent=2))
        results[case] = result
        summary = {key: value for key, value in result.items() if key != "timeline"}
        print(json.dumps({"case": case, **summary}), flush=True)
        assert result["exit_code"] == 0 and not result["errors"], case
        assert result["muted_interval_frames"] == 0, "Outside desktop audio leaked: " + case
        assert abs(result["peak"] - (.075 if case == "routing-ambiguous" else .1)) < .002, case
        reference = {"routing-window": .15, "routing-toggle": .15, "routing-hidden": .225}.get(case, .25)
        assert abs(result["reference_peak"] - reference) < .002, "Caption audio changed the program mix"
        if case == "routing-hidden":
            assert 48000 * 7 < result["frames"] < 48000 * 9
            assert result["microphone_frames"] == 0
            continue
        assert result["frames"] > 48000 * 9
        patterns = {
            "routing-toggle": [.1, .1, .1, .075, .075, .1, .1, .075, .1, .1],
            "routing-ambiguous": [.075] * 10,
            "routing-left": [.1, .1, .1, .075, .075, .1, .075, .075, .075, .075],
        }
        expected = patterns.get(case, [.1] * 10)
        for second, peak in enumerate(expected):
            assert abs(middle_peak(result, second) - peak) < .002, (case, second)
        if case in ("routing-toggle", "routing-left"):
            assert result["microphone_frames"] > 48000 * 2.5
            assert result["sequence_gaps"] >= (3 if case == "routing-left" else 4)
        elif case == "routing-ambiguous":
            assert result["microphone_frames"] > 48000 * 9
            assert result["sequence_gaps"] == 0
        else:
            assert result["microphone_frames"] == 0
            assert result["sequence_gaps"] == 0
    (root / "results.json").write_text(json.dumps(results, indent=2))
    print("Source isolation and hotkeys passed: native input, private app audio, toggle, "
          "held key, missing mic, hidden source, ambiguity and return to microphone")


if __name__ == "__main__":
    main()
