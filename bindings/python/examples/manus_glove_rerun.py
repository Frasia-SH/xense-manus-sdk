"""
Manus Glove Skeleton Visualization with Rerun

Visualizes:
- World coordinate system origin + ground grid
- Both hands' raw skeletons as joints (Points3D) + bones (LineStrips3D)
- Live ErgonomicsData (5 fingers x 4 angles per hand) as an in-place console table

Manus Coordinate System (set in ManusGlove.cpp via CoordinateSystemVUH):
- handedness = Right, up = +Z, view = XFromViewer, unit = meters
- i.e. RIGHT-HANDED, Z-up.

Data model (from the manus_glove pybind module):
- get_raw_skeleton_both() -> {'left': (N,10), 'right': (N,10)}
    each row = position(3) + quaternion wxyz(4) + scale(3); ~26 nodes/hand
- get_node_info(side) -> [NodeInfo(node_id, parent_id, chain_type, side, finger_joint_type)]
    static hierarchy; parent_id is a node_id (not a row index) -> build id->index map for bones
- get_ergonomics() -> (40,) : [0:20]=left, [20:40]=right
    per hand: 5 fingers x [MCPSpread, MCPStretch, PIPStretch, DIPStretch] in degrees
    finger order: Thumb, Index, Middle, Ring, Pinky
"""

import os
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np
import rerun as rr

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "build/python"))
import manus_glove


# === Calibration (follows example.py) ===
CALIB_DIR = REPO_ROOT / "calibration"
CALIB_FILES = {
    "left": CALIB_DIR / "Left.mcal",
    "right": CALIB_DIR / "Right.mcal",
}

# === ChainType enum values (ManusSDKTypes.h, 0-indexed from Invalid) ===
CHAIN_THUMB = 5
CHAIN_INDEX = 6
CHAIN_MIDDLE = 7
CHAIN_RING = 8
CHAIN_PINKY = 9
CHAIN_HAND = 13

# Per-finger colors (RGB), keyed by chain_type. Wrist/palm + fallback in gray.
CHAIN_COLORS = {
    CHAIN_THUMB: [255, 80, 80],     # red
    CHAIN_INDEX: [255, 170, 60],    # orange
    CHAIN_MIDDLE: [80, 220, 100],   # green
    CHAIN_RING: [80, 160, 255],     # blue
    CHAIN_PINKY: [200, 110, 230],   # purple
    CHAIN_HAND: [180, 180, 180],    # gray
}
DEFAULT_COLOR = [150, 150, 150]

# Side accent for joints, so left/right are distinguishable at a glance.
SIDE_JOINT_COLOR = {
    "left": [120, 200, 255],
    "right": [255, 200, 120],
}

# Manus raw skeleton is wrist-LOCAL: node0 (wrist) is always at (0,0,0) for BOTH
# hands, so without an offset the two hands collapse onto the world origin and on
# top of each other. Anchor each hand to its own spot purely for display.
HAND_OFFSET = {
    "left": [-0.15, 0.0, 0.0],
    "right": [0.15, 0.0, 0.0],
}

# Ergonomics layout: per hand, 5 fingers x 4 angles.
FINGER_NAMES = ["Thumb", "Index", "Middle", "Ring", "Pinky"]
ANGLE_NAMES = ["Spread", "MCP", "PIP", "DIP"]

ANSI_HIDE_CURSOR = "\033[?25l"
ANSI_SHOW_CURSOR = "\033[?25h"

MAIN_LOOP_HZ = 60.0
MAIN_LOOP_DT = 1.0 / MAIN_LOOP_HZ

CONSOLE_REFRESH_EVERY = 6  # ~10 Hz console refresh at 60 Hz loop

# Set by the SIGINT handler to request an orderly shutdown from any wait loop.
_stop = False


def chain_color(chain_type: int) -> list:
    return CHAIN_COLORS.get(chain_type, DEFAULT_COLOR)


def wait_and_calibrate(glove, timeout_s: float = 15.0, poll_s: float = 0.2) -> dict:
    """Poll until each side's glove id is resolved (!=0), then apply its .mcal.

    The glove<->side mapping arrives via the landscape stream shortly after
    connect(); set_calibration() returns -1 until the side's glove id is known.
    Gloves may also power on at different times, so each side is handled
    independently and calibrated as soon as it appears. Returns {side: glove_id}
    for the sides that became ready within the timeout.
    """
    pending = dict(CALIB_FILES)
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


def build_bone_index(node_info) -> list:
    """From a hand's node_info list build a list of (parent_row, child_row, chain_type).

    parent_id is a node_id (not a row index); root nodes point to themselves and are
    skipped. Returns one entry per drawable bone (child colored by its chain).
    """
    id_to_row = {int(n.node_id): i for i, n in enumerate(node_info)}
    bones = []
    for row, n in enumerate(node_info):
        pid = int(n.parent_id)
        prow = id_to_row.get(pid)
        if prow is None or prow == row:
            continue  # root / dangling parent
        bones.append((prow, row, int(n.chain_type)))
    return bones


def log_hand(side: str, skel: np.ndarray, bones: list, node_info) -> int:
    """Log one hand's joints (points) and bones (line strips). Returns node count drawn.

    Joints/bones live under "world/{side}_hand", which carries a static display
    offset (see setup_rerun) so the two wrist-local hands don't pile on the origin.
    """
    base = f"world/{side}_hand"
    if skel is None or skel.shape[0] == 0:
        rr.log(f"{base}/joints", rr.Clear(recursive=True))
        rr.log(f"{base}/bones", rr.Clear(recursive=True))
        return 0

    positions = skel[:, 0:3].astype(np.float32)
    n = positions.shape[0]

    # Joints: colored per chain when node_info is available, else a side accent.
    if node_info is not None and len(node_info) == n:
        joint_colors = [chain_color(int(node_info[i].chain_type)) for i in range(n)]
    else:
        joint_colors = [SIDE_JOINT_COLOR.get(side, DEFAULT_COLOR)] * n

    rr.log(
        f"{base}/joints",
        rr.Points3D(positions, colors=joint_colors, radii=0.008),
    )

    # Bones: parent->child segments, colored by the child's chain.
    if bones:
        segments = []
        seg_colors = []
        for prow, crow, ctype in bones:
            if prow < n and crow < n:
                segments.append([positions[prow], positions[crow]])
                seg_colors.append(chain_color(ctype))
        if segments:
            rr.log(
                f"{base}/bones",
                rr.LineStrips3D(segments, colors=seg_colors, radii=0.004),
            )
    return n


def setup_rerun():
    """Initialize Rerun and lay out the static scene (axes + ground grid)."""
    # Flush almost every frame so the live viewer stays at the latest pose
    # (large batching makes updates arrive in bursts and feel frozen).
    os.environ.setdefault("RERUN_FLUSH_NUM_BYTES", "1024")
    rr.init("Manus Glove Skeleton Visualization")

    # Two viewer modes:
    #   default        -> rr.spawn(): launch a detached viewer process.
    #   MANUS_RERUN_CONNECT set -> connect to a viewer you started yourself
    #                       (run `rerun` in another terminal first). This fully
    #                       decouples the viewer from this script's lifecycle, so
    #                       Ctrl+C here never disturbs the GPU window.
    if os.environ.get("MANUS_RERUN_CONNECT"):
        rr.connect_grpc(os.environ.get("MANUS_RERUN_URL") or None)
        print("rerun: connected to an external viewer")
    else:
        rr.spawn(memory_limit=os.environ.get("RERUN_MEMORY_LIMIT", "500MB"))

    # Manus: right-handed, Z up.
    rr.log("world", rr.ViewCoordinates.RIGHT_HAND_Z_UP, static=True)

    # World origin axes: X=red, Y=green, Z=blue (Z up). Kept small so the hands,
    # which sit near the origin, are not buried inside the gizmo.
    origin = np.array([0.0, 0.0, 0.0])
    axis_len = 0.1
    rr.log(
        "world/origin/axes",
        rr.Arrows3D(
            origins=[origin, origin, origin],
            vectors=[[axis_len, 0, 0], [0, axis_len, 0], [0, 0, axis_len]],
            colors=[[255, 50, 50], [50, 255, 50], [50, 50, 255]],
            radii=0.003,
        ),
        static=True,
    )

    # Static display anchor + label per hand: the raw skeleton is wrist-local
    # (node0 == origin for both hands), so we shift each hand subtree to its own
    # spot. Joints/bones logged under "world/{side}_hand/..." inherit this offset.
    for side, off in HAND_OFFSET.items():
        rr.log(
            f"world/{side}_hand",
            rr.Transform3D(translation=off),
            static=True,
        )
        rr.log(
            f"world/{side}_hand/label",
            rr.Points3D(
                [[0.0, 0.0, 0.12]],
                labels=[side.upper()],
                show_labels=True,
                colors=[SIDE_JOINT_COLOR.get(side, DEFAULT_COLOR)],
                radii=0.004,
            ),
            static=True,
        )

    # Ground grid on the XY plane (z=0).
    grid_size = 1.0
    grid_lines = 21
    grid_points = []
    for i in range(grid_lines):
        t = -grid_size / 2 + i * grid_size / (grid_lines - 1)
        grid_points.append([[t, -grid_size / 2, 0], [t, grid_size / 2, 0]])
        grid_points.append([[-grid_size / 2, t, 0], [grid_size / 2, t, 0]])
    rr.log(
        "world/grid",
        rr.LineStrips3D(grid_points, colors=[[100, 100, 100, 60]]),
        static=True,
    )


def format_ergo_table(iteration: int, elapsed: float, ergo: np.ndarray) -> list:
    """Build an in-place console dashboard for the 40-value ergonomics array.

    ergo layout: [0:20]=left, [20:40]=right; per hand 5 fingers x [Spread,MCP,PIP,DIP] (deg).
    """
    header = f"── Manus Ergonomics  iter={iteration:>6}  t={elapsed:7.2f}s ".ljust(78, "─")
    col = "          │  Spread    MCP    PIP    DIP   │  Spread    MCP    PIP    DIP"
    sub = f"  Finger  │{'  LEFT (deg)':^32}│{'  RIGHT (deg)':^32}"
    lines = [header, sub, col, "  " + "─" * 74]

    have = ergo is not None and ergo.shape[0] >= 40
    for f, name in enumerate(FINGER_NAMES):
        if have:
            lo = f * 4
            ro = 20 + f * 4
            lvals = "".join(f"{ergo[lo + k]:+7.1f}" for k in range(4))
            rvals = "".join(f"{ergo[ro + k]:+7.1f}" for k in range(4))
            lines.append(f"  {name:<7} │ {lvals}   │ {rvals}")
        else:
            lines.append(f"  {name:<7} │ {'(no data)':^30} │ {'(no data)':^30}")
    lines.append("─" * 78)
    return lines


def _request_stop(signum, frame):
    """SIGINT handler: ask the loop to finish this iteration and shut down.

    We set a flag instead of raising so Ctrl+C can never land in the middle of a
    blocking SDK call. Further SIGINTs are ignored during cleanup (see finally)
    so the USB/Core shutdown is not interrupted half-way (which can wedge the
    dongle and, on some setups, the desktop session).
    """
    global _stop
    if not _stop:
        _stop = True
        sys.stderr.write("\nStopping (cleaning up, please wait)...\n")
        sys.stderr.flush()


def run_visualization():
    global _stop
    _stop = False
    print("Starting Manus Glove Skeleton Visualization with Rerun...")

    glove = manus_glove.ManusGlove()
    log_line_count = 0
    cursor_hidden = False
    prev_handler = signal.signal(signal.SIGINT, _request_stop)
    try:
        print("Connecting to Manus Core (integrated, world coordinates)...")
        ok = glove.connect(mode="integrated", world_coordinates=True, timeout_seconds=10)
        if not ok:
            print("connect failed", file=sys.stderr)
            return
        print("connected. world_coordinates =", glove.is_world_coordinates())

        # Wait for gloves to be resolved to sides, then load calibration. Avoids
        # the set_calibration() -> -1 race when calibrating before the glove id
        # is known. Skeleton data also starts flowing once a glove is ready.
        print("Waiting for gloves and applying calibration...")
        wait_and_calibrate(glove)

        print("Setting up Rerun...")
        setup_rerun()

        print("left glove id:", glove.get_glove_id("left"))
        print("right glove id:", glove.get_glove_id("right"))

        # Node hierarchy is static; fetch lazily once it becomes available per side.
        node_info = {"left": None, "right": None}
        bones = {"left": [], "right": []}

        start_time = time.perf_counter()
        sys.stdout.write(ANSI_HIDE_CURSOR)
        sys.stdout.flush()
        cursor_hidden = True

        iteration = 0
        while not _stop:
            loop_start = time.perf_counter()
            rr.set_time("frame", sequence=iteration)
            rr.set_time("time", duration=loop_start - start_time)

            both = glove.get_raw_skeleton_both()
            for side in ("left", "right"):
                skel = both[side]
                # Lazily resolve the static hierarchy once skeleton rows exist.
                if node_info[side] is None and skel.shape[0] > 0:
                    info = glove.get_node_info(side)
                    if info:
                        node_info[side] = info
                        bones[side] = build_bone_index(info)
                log_hand(side, skel, bones[side], node_info[side])

            ergo = glove.get_ergonomics()

            if iteration % CONSOLE_REFRESH_EVERY == 0:
                elapsed = time.perf_counter() - start_time
                lines = format_ergo_table(iteration, elapsed, ergo)
                buf = []
                if log_line_count > 0:
                    buf.append(f"\033[{log_line_count}F\033[J")
                buf.append("\n".join(lines))
                buf.append("\n")
                sys.stdout.write("".join(buf))
                sys.stdout.flush()
                log_line_count = len(lines)

            # Plain sleep (no busy-spin): frees the CPU for the viewer process,
            # which keeps rendering latency down. Sub-ms loop accuracy is not
            # needed for hand visualization.
            dt = time.perf_counter() - loop_start
            time.sleep(max(0.0, MAIN_LOOP_DT - dt))
            iteration += 1

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        # Ignore further SIGINT so a second Ctrl+C cannot interrupt USB/Core
        # shutdown half-way (the main cause of the dongle/desktop wedging).
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if cursor_hidden:
            sys.stdout.write(ANSI_SHOW_CURSOR + "\n")
            sys.stdout.flush()
        # Detach the rerun data stream first (viewer process keeps running),
        # then shut the SDK down.
        try:
            rr.disconnect()
        except Exception:
            pass

        # CoreSdk_ShutDown() (inside glove.disconnect()) can block indefinitely
        # if the integrated Core is in a bad state (e.g. a glove dropped mid
        # session). Guard it with a watchdog so the process always exits within a
        # few seconds instead of hanging the terminal; os._exit() force-kills the
        # stuck SDK threads. The rerun viewer is a separate process and is
        # unaffected.
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
    run_visualization()
