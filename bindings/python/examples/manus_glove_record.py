"""
Manus Glove Data Recorder (+ optional Rerun visualization)

Records, per frame, the two quantities the SDK exposes:
- RawSkeletonData : {'left','right'} each (N,10) = pos(3)+quat wxyz(4)+scale(3).
  N (node count per hand) is NOT a compile-time constant -- it is whatever
  CoreSdk_GetRawSkeletonNodeCount returns at runtime. We LOCK N at the first
  valid frame and store it in the file metadata; if a hand reports a different
  node count it is recorded as invalid (NaN) for that frame.
- ErgonomicsData  : (40,) = [0:20]=left, [20:40]=right; per hand 5 fingers
  (Thumb,Index,Middle,Ring,Pinky) x [MCPSpread,MCPStretch,PIPStretch,DIPStretch] (deg).

Output: a single crash-safe HDF5 file (chunked, gzip, flushed every batch). The
file is closed BEFORE the SDK shutdown so the watchdog's os._exit() can never
leave it half-written.

Visualization (default on, --no-viz to disable) reuses the skeleton + ergonomics
table from manus_glove_rerun.py. rr.log() is async so it adds negligible cost to
the recording loop (single thread, as discussed).

Run in the `manus` mamba env:
    mamba activate manus
    python manus_glove_record.py                 # 60 Hz, viz on, auto-named file
    python manus_glove_record.py --rate 30 --no-viz --duration 120
    python manus_glove_record.py --out /path/to/take01.h5
"""

import argparse
import os
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np
import h5py

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
sys.path.insert(0, str(REPO_ROOT / "build/python"))
import manus_glove  # noqa: E402
import manus_glove_rerun as viz  # noqa: E402  reuse calib paths + viz helpers


# Ergonomics column labels in SDK order (ManusSDKTypes.h ErgonomicsDataType).
_FINGERS = ["Thumb", "Index", "Middle", "Ring", "Pinky"]
_ANGLES = ["MCPSpread", "MCPStretch", "PIPStretch", "DIPStretch"]
ERGO_LABELS = [f"{side}_{fng}_{ang}"
               for side in ("Left", "Right")
               for fng in _FINGERS
               for ang in _ANGLES]
assert len(ERGO_LABELS) == 40

# Set by the SIGINT handler so any wait loop can shut down in an orderly way.
_stop = False


def _request_stop(signum, frame):
    global _stop
    if not _stop:
        _stop = True
        sys.stderr.write("\nStopping (flushing + cleaning up, please wait)...\n")
        sys.stderr.flush()


def wait_and_calibrate(glove, timeout_s: float = 15.0, poll_s: float = 0.2) -> dict:
    """Poll until each side's glove id resolves (!=0), then apply its .mcal.

    Mirrors manus_glove_rerun.wait_and_calibrate but uses this module's _stop so
    Ctrl+C interrupts the wait cleanly.
    """
    pending = dict(viz.CALIB_FILES)
    ready = {}
    deadline = time.perf_counter() + timeout_s
    while pending and not _stop and time.perf_counter() < deadline:
        for side in list(pending):
            gid = glove.get_glove_id(side)
            if gid == 0:
                continue
            path = pending.pop(side)
            ready[side] = gid
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
    return ready


class H5Recorder:
    """Crash-safe, chunked HDF5 recorder. Datasets are created lazily once the
    per-hand node count N is known (first valid skeleton frame)."""

    def __init__(self, path: Path, rate_hz: float, world: bool,
                 glove_ids: dict, batch: int = 30):
        self.path = Path(path)
        self.rate_hz = rate_hz
        self.world = world
        self.glove_ids = glove_ids
        self.batch = batch
        self.f = None
        self.N = None
        self.count = 0
        self._buf = []
        self._d = {}
        self._mismatch_warned = False

    def _ensure_file(self, N: int):
        self.N = N
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = h5py.File(self.path, "w")
        f = self.f
        f.attrs["created_wall"] = time.time()
        f.attrs["created_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        f.attrs["rate_hz"] = float(self.rate_hz)
        f.attrs["world_coordinates"] = bool(self.world)
        f.attrs["N_nodes"] = int(N)
        f.attrs["left_glove_id"] = int(self.glove_ids.get("left", 0))
        f.attrs["right_glove_id"] = int(self.glove_ids.get("right", 0))
        f.attrs["coordinate_system"] = "RIGHT_HAND_Z_UP"
        f.attrs["quat_order"] = "wxyz"
        f.attrs["skel_cols"] = ("pos_x,pos_y,pos_z,quat_w,quat_x,quat_y,quat_z,"
                                "scale_x,scale_y,scale_z")
        f.attrs["pos_units"] = "meters"
        f.attrs["ergo_units"] = "degrees"
        f.attrs["ergo_labels"] = np.array(ERGO_LABELS, dtype=h5py.string_dtype())

        def mk(name, shape, dtype):
            self._d[name] = f.create_dataset(
                name, shape=(0,) + shape, maxshape=(None,) + shape,
                dtype=dtype, chunks=(self.batch,) + shape,
                compression="gzip", compression_opts=4)

        mk("t_wall", (), "f8")          # unix seconds (time.time)
        mk("t_mono", (), "f8")          # seconds since start (perf_counter)
        mk("frame", (), "i8")           # loop iteration index
        mk("left_skel", (N, 10), "f4")  # NaN where invalid
        mk("right_skel", (N, 10), "f4")
        mk("left_valid", (), "?")
        mk("right_valid", (), "?")
        mk("ergo", (40,), "f4")
        f.flush()
        print(f"\nLocked N={N} nodes/hand. Recording -> {self.path}")

    def store_node_info(self, side: str, info):
        """Store one hand's static hierarchy once (self-describing file)."""
        if self.f is None or not info:
            return
        grp = self.f.require_group("node_info")
        if side in grp:
            return
        sg = grp.create_group(side)
        sg.create_dataset("node_id", data=np.array([int(n.node_id) for n in info], np.uint32))
        sg.create_dataset("parent_id", data=np.array([int(n.parent_id) for n in info], np.uint32))
        sg.create_dataset("chain_type", data=np.array([int(n.chain_type) for n in info], np.int32))
        sg.create_dataset("finger_joint_type",
                          data=np.array([int(n.finger_joint_type) for n in info], np.int32))
        sg.create_dataset("side", data=np.array([int(n.side) for n in info], np.int32))
        self.f.flush()

    def add(self, t_wall, t_mono, frame, left, right, ergo) -> bool:
        """Buffer one frame. Returns False (skipped) until a skeleton appears."""
        if self.N is None:
            n = None
            if left is not None and left.shape[0] > 0:
                n = left.shape[0]
            elif right is not None and right.shape[0] > 0:
                n = right.shape[0]
            if n is None:
                return False  # no skeleton yet -> don't start the file
            self._ensure_file(n)

        nan = np.full((self.N, 10), np.nan, np.float32)
        lv = left is not None and left.shape[0] == self.N
        rv = right is not None and right.shape[0] == self.N
        if not self._mismatch_warned:
            if (left is not None and left.shape[0] not in (0, self.N)) or \
               (right is not None and right.shape[0] not in (0, self.N)):
                sys.stderr.write(f"\n[warn] a hand reported node count != N({self.N}); "
                                 f"recording it as invalid for those frames.\n")
                self._mismatch_warned = True

        self._buf.append((
            float(t_wall), float(t_mono), int(frame),
            left.astype(np.float32) if lv else nan,
            right.astype(np.float32) if rv else nan,
            bool(lv), bool(rv), ergo.astype(np.float32),
        ))
        if len(self._buf) >= self.batch:
            self.flush()
        return True

    def flush(self):
        if not self._buf or self.f is None:
            return
        b, self._buf = self._buf, []
        old, new = self.count, self.count + len(b)
        for d in self._d.values():
            d.resize(new, axis=0)
        self._d["t_wall"][old:new] = [r[0] for r in b]
        self._d["t_mono"][old:new] = [r[1] for r in b]
        self._d["frame"][old:new] = [r[2] for r in b]
        self._d["left_skel"][old:new] = np.stack([r[3] for r in b])
        self._d["right_skel"][old:new] = np.stack([r[4] for r in b])
        self._d["left_valid"][old:new] = [r[5] for r in b]
        self._d["right_valid"][old:new] = [r[6] for r in b]
        self._d["ergo"][old:new] = np.stack([r[7] for r in b])
        self.count = new
        self.f.flush()

    def close(self):
        try:
            self.flush()
        finally:
            if self.f is not None:
                self.f.attrs["num_frames"] = int(self.count)
                self.f.close()
                self.f = None


def default_out_path() -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return HERE / "recordings" / f"manus_{stamp}.h5"


def parse_args():
    p = argparse.ArgumentParser(description="Record Manus raw skeleton + ergonomics to HDF5.")
    p.add_argument("--rate", type=float, default=60.0, help="recording/poll rate in Hz (default 60)")
    p.add_argument("--out", type=Path, default=None, help="output .h5 path (default recordings/manus_<ts>.h5)")
    p.add_argument("--duration", type=float, default=None, help="stop after N seconds (default: until Ctrl+C)")
    p.add_argument("--no-viz", action="store_true", help="disable Rerun visualization (pure recording)")
    p.add_argument("--batch", type=int, default=30, help="HDF5 flush batch size in frames (default 30)")
    return p.parse_args()


def run():
    global _stop
    _stop = False
    args = parse_args()
    out = args.out or default_out_path()
    dt_target = 1.0 / args.rate
    do_viz = not args.no_viz
    console_every = max(1, int(round(args.rate / 10.0)))  # ~10 Hz console refresh

    print("Manus Glove Recorder")
    print(f"  rate={args.rate:g} Hz   viz={'on' if do_viz else 'off'}   out={out}")

    glove = manus_glove.ManusGlove()
    recorder = None
    cursor_hidden = False
    log_line_count = 0
    prev_handler = signal.signal(signal.SIGINT, _request_stop)
    try:
        print("Connecting to Manus Core (integrated, world coordinates)...")
        if not glove.connect(mode="integrated", world_coordinates=True, timeout_seconds=10):
            print("connect failed", file=sys.stderr)
            return
        print("connected. world_coordinates =", glove.is_world_coordinates())

        print("Waiting for gloves and applying calibration...")
        wait_and_calibrate(glove)
        glove_ids = {"left": glove.get_glove_id("left"), "right": glove.get_glove_id("right")}
        print("left glove id:", glove_ids["left"], " right glove id:", glove_ids["right"])

        if do_viz:
            print("Setting up Rerun...")
            viz.setup_rerun()

        recorder = H5Recorder(out, args.rate, glove.is_world_coordinates(), glove_ids, batch=args.batch)

        node_info = {"left": None, "right": None}
        bones = {"left": [], "right": []}

        start = time.perf_counter()
        sys.stdout.write(viz.ANSI_HIDE_CURSOR)
        sys.stdout.flush()
        cursor_hidden = True

        iteration = 0
        recorded = 0
        waiting_printed = False
        while not _stop:
            loop_start = time.perf_counter()
            t_mono = loop_start - start
            if args.duration is not None and t_mono >= args.duration:
                break

            both = glove.get_raw_skeleton_both()
            ergo = glove.get_ergonomics()
            left, right = both["left"], both["right"]

            wrote = recorder.add(time.time(), t_mono, iteration, left, right, ergo)
            if wrote:
                recorded += 1
                # Lock + store static hierarchy once the file (and N) exist.
                for side, skel in (("left", left), ("right", right)):
                    if node_info[side] is None and skel.shape[0] > 0:
                        info = glove.get_node_info(side)
                        if info:
                            node_info[side] = info
                            bones[side] = viz.build_bone_index(info)
                            recorder.store_node_info(side, info)
            elif not waiting_printed:
                sys.stdout.write("waiting for a glove skeleton to start recording...\n")
                sys.stdout.flush()
                waiting_printed = True

            if do_viz:
                import rerun as rr
                rr.set_time("frame", sequence=iteration)
                rr.set_time("time", duration=t_mono)
                for side, skel in (("left", left), ("right", right)):
                    viz.log_hand(side, skel, bones[side], node_info[side])

            if iteration % console_every == 0:
                lines = viz.format_ergo_table(iteration, t_mono, ergo)
                status = (f"  REC {'●' if recorder.f else '○'}  frames={recorded:>7}  "
                          f"{recorded / t_mono if t_mono > 0 else 0:5.1f} Hz  "
                          f"N={recorder.N if recorder.N else '?'}  -> {out.name}")
                lines = [status] + lines
                buf = []
                if log_line_count > 0:
                    buf.append(f"\033[{log_line_count}F\033[J")
                buf.append("\n".join(lines) + "\n")
                sys.stdout.write("".join(buf))
                sys.stdout.flush()
                log_line_count = len(lines)

            sleep = dt_target - (time.perf_counter() - loop_start)
            if sleep > 0:
                time.sleep(sleep)
            iteration += 1

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if cursor_hidden:
            sys.stdout.write(viz.ANSI_SHOW_CURSOR + "\n")
            sys.stdout.flush()

        # Close the HDF5 file FIRST so data is safe on disk even if the SDK
        # shutdown below hangs and the watchdog force-exits the process.
        if recorder is not None:
            recorder.close()
            print(f"Saved {recorder.count} frames (N={recorder.N}) to {out}")

        if do_viz:
            try:
                import rerun as rr
                rr.disconnect()
            except Exception:
                pass

        print("Closing SDK...")

        def _force_exit():
            sys.stderr.write("\nSDK shutdown timed out; forcing exit.\n")
            sys.stderr.flush()
            os._exit(0)

        watchdog = threading.Timer(6.0, _force_exit)
        watchdog.daemon = True
        watchdog.start()
        glove.disconnect()
        watchdog.cancel()
        print("disconnected")
        signal.signal(signal.SIGINT, prev_handler)


if __name__ == "__main__":
    run()
