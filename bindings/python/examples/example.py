"""Minimal usage example for the manus_glove pybind11 module."""

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "build/python"))

import numpy as np
import manus_glove

LOG_INTERVAL_S = 2.0
DIAGNOSTIC_LOG_INTERVAL_S = 3.0
DIAGNOSTIC_LOG_PATH = Path(__file__).resolve().parents[3] / "manus.log"


def append_debug_events(events, reason):
    if not events:
        return
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with DIAGNOSTIC_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n[{timestamp}] {reason}\n")
        for e in events:
            source = e.get("source", "")
            if source == "system":
                f.write(
                    f"  #{e.get('sequence')} +{e.get('timestamp_ms')}ms "
                    f"system {e.get('type_name')}({e.get('type')}) "
                    f"info_uint={e.get('info_uint')} message={e.get('message')}\n"
                )
            else:
                f.write(
                    f"  #{e.get('sequence')} +{e.get('timestamp_ms')}ms "
                    f"sdk_log {e.get('severity_name')} message={e.get('message')}\n"
                )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--calibration-dir",
        type=Path,
        default=REPO_ROOT / "calibration",
        help="directory containing Left.mcal and Right.mcal",
    )
    parser.add_argument("--log-path", type=Path, default=REPO_ROOT / "manus.log")
    args = parser.parse_args()
    global DIAGNOSTIC_LOG_PATH
    DIAGNOSTIC_LOG_PATH = args.log_path

    calib_files = {
        "left": args.calibration_dir / "Left.mcal",
        "right": args.calibration_dir / "Right.mcal",
    }
    glove = manus_glove.ManusGlove()

    # Plan A: global vs local is chosen here and fixed for the connection.
    #   world_coordinates=True  -> global/world coordinates
    #   world_coordinates=False -> local (relative to parent)
    # mode: "integrated" (no Manus Core), "local", or "remote".
    ok = glove.connect(mode="integrated", world_coordinates=True, timeout_seconds=10)
    if not ok:
        print("connect failed")
        return
    print("connected. world_coordinates =", glove.is_world_coordinates())

    # Load .mcal calibration captured from the official tool. Must be done AFTER
    # the glove id (and its side) is known: the glove<->side mapping arrives via
    # the landscape stream a moment after connect(), and set_calibration()
    # returns -1 until then. Gloves can also power on at different times, so poll
    # each side and calibrate it as soon as its glove id becomes non-zero.
    # Left.mcal must go to "left", Right.mcal to "right" (a wrong-side file
    # returns a non-success code).
    def wait_and_calibrate(timeout_s=15.0, poll_s=0.2):
        pending = dict(calib_files)
        deadline = time.perf_counter() + timeout_s
        while pending and time.perf_counter() < deadline:
            for side in list(pending):
                gid = glove.get_glove_id(side)
                if gid == 0:
                    continue
                path = pending.pop(side)
                if not path.is_file():
                    print(f"{side}: calibration file not found: {path}")
                    continue
                code = glove.set_calibration(side, path.read_bytes())
                print(f"{side} glove ready (id={gid}), calibration <- {path.name} "
                      f"-> code {code} (1 == success)")
            if pending:
                time.sleep(poll_s)
        for side in pending:
            print(f"{side}: glove not detected within {timeout_s:.0f}s (skipped calibration)")

    wait_and_calibrate()

    print("left glove id:", glove.get_glove_id("left"))
    print("right glove id:", glove.get_glove_id("right"))

    try:
        next_log_time = 0.0
        next_diagnostic_log_time = 0.0
        while True:
            both = glove.get_raw_skeleton_both()      # {'left': (N,10), 'right': (N,10)}
            left = both["left"]                        # numpy (N,10): pos(3)+quat wxyz(4)+scale(3)
            right = both["right"]
            ergo = glove.get_ergonomics()             # numpy (40,)

            now = time.perf_counter()
            if now >= next_log_time:
                print(f"left {left.shape} right {right.shape} ergo {ergo.shape}")
                for side, skeleton in (("left", left), ("right", right)):
                    if skeleton.shape[0] > 0:
                        print(f"  {side} node0 pos:", skeleton[0, 0:3], "quat:", skeleton[0, 3:7])
                    else:
                        print(f"  {side} node0: no skeleton data")
                next_log_time = now + LOG_INTERVAL_S

            if now >= next_diagnostic_log_time:
                missing_sides = [
                    side for side, skeleton in (("left", left), ("right", right))
                    if glove.get_glove_id(side) == 0 or skeleton.shape[0] == 0
                ]
                events = glove.drain_debug_events()
                if missing_sides:
                    append_debug_events(
                        events, "missing/empty hand data: " + ", ".join(missing_sides)
                    )
                next_diagnostic_log_time = now + DIAGNOSTIC_LOG_INTERVAL_S

            # -> feed keypoints into dex-retargeting here
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        glove.disconnect()
        print("disconnected")


if __name__ == "__main__":
    main()
