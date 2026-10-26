"""Verify scene-scoped PCM with real libobs and simultaneous outside audio.

Uses the isolated synthetic host; never controls a running OBS instance.
"""
import argparse
import json
from pathlib import Path

from verify_scene_audio import ROOT, exercise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--modern", type=Path, default=ROOT / "build/obs-bilingue.dll")
    parser.add_argument("--stress-seconds", type=int, default=0,
                        help="Also alternate scenes every 300 ms for this duration (0 disables)")
    args = parser.parse_args()
    if not 0 <= args.stress_seconds <= 600:
        parser.error("stress duration must be between 0 and 600 seconds")
    root = ROOT / ".build/scene-isolation-test"
    baseline = exercise(args.legacy, root / "legacy", legacy_scene=True)
    results = {"legacy_scene": baseline}
    assert baseline["exit_code"] == 0 and baseline["frames"] == 0
    assert baseline["reference_peak"] > .14
    cases = ["basic", "nested", "group", "two-inputs", "shared", "hidden-item", "edit", "switch",
             "inactive", "muted-scene", "removed-scene"]
    for case in cases:
        result = exercise(args.modern, root / case, scene_case=case)
        results[case] = result
        # Print only aggregate metrics; private libobs logs stay under .build/.
        print(json.dumps({"case": case, **result}), flush=True)
        assert result["exit_code"] == 0 and not result["errors"], case
        assert result["reference_peak"] > .09, case
        if case == "removed-scene":
            assert result["frames"] > 48000 and result["peak"] < .102, case
            continue
        assert result["frames"] > 48000 * 3, case
        expected_peak = {"inactive": 0, "group": .05, "two-inputs": .125, "edit": .125}.get(case, .1)
        assert abs(result["peak"] - expected_peak) < .002, case
        if case in ("basic", "hidden-item", "muted-scene"):
            assert result["zero_frames"] > 48000, case
        if case in ("basic", "nested", "shared", "hidden-item", "muted-scene", "switch"):
            assert result["muted_interval_frames"] == 0, "Outside audio leaked: " + case
        if case in ("edit", "two-inputs"):
            assert result["two_inputs_frames"] > 48000, case
        if case == "switch":
            assert result["quarter_volume_frames"] > 48000, case
            assert result["sequence_gaps"] >= 2, "Source changes must reset the previous ASR segment"
    empty = exercise(args.modern, root / "empty-track", empty_track=True, scene_case="basic")
    results["empty-track"] = empty
    assert empty["exit_code"] == 0 and empty["frames"] > 48000 * 3 and empty["peak"] == 0
    visible = exercise(args.modern, root / "visibility", visibility=True, scene_case="nested")
    results["visibility"] = visible
    assert visible["exit_code"] == 0 and 48000 * 2.5 < visible["frames"] < 48000 * 5
    assert abs(visible["peak"] - .1) < .002 and visible["muted_interval_frames"] == 0
    if args.stress_seconds:
        stress = exercise(args.modern, root / "stress", scene_case="stress", seconds=args.stress_seconds)
        results["stress"] = stress
        print(json.dumps({"case": "stress", **stress}), flush=True)
        assert stress["exit_code"] == 0 and not stress["errors"]
        assert stress["frames"] > 48000 * args.stress_seconds * .85
        assert abs(stress["peak"] - .1) < .002 and stress["muted_interval_frames"] == 0
        assert stress["quarter_volume_frames"] > 48000 * args.stress_seconds * .3
        assert stress["sequence_gaps"] >= args.stress_seconds * 2
    (root / "results.json").write_text(json.dumps(results, indent=2))
    print("Scene isolation passed: previous failure + 13 current routing/lifecycle cases")


if __name__ == "__main__":
    main()
