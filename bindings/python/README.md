# `manus_glove` Python Binding

The binding exposes the MANUS SDK through a small pull-based Python API. C++
receives SDK callbacks continuously and caches the latest frame; Python getters
return that latest frame at the caller's pace.

## API

The module exposes `manus_glove.ManusGlove` and `NodeInfo` objects.

| Call | Return | Description |
|---|---|---|
| `connect(mode, world_coordinates, timeout_seconds)` | `bool` | Initialize and connect to the glove/Core. |
| `disconnect()` | `None` | Stop the SDK and clear cached state. |
| `is_connected()` | `bool` | Current wrapper connection state. |
| `get_glove_id(side)` | `int` | Glove id for `left` or `right`, or `0`. |
| `vibrate_fingers(side, powers)` | `int` | Send one five-finger haptic command; powers are Thumb/Index/Middle/Ring/Pinky in `[0, 1]`. Returns `1` on success, `-1` when disconnected, `-2` on SDK transport failure, or `-3` for invalid powers. |
| `get_raw_skeleton(side)` | `numpy.ndarray` | Latest `(N, 10)` pose array. |
| `get_raw_skeleton_both()` | `dict` | Latest arrays for both sides. |
| `get_ergonomics()` | `numpy.ndarray` | Merged `(40,)` ergonomics array. |
| `get_node_info(side)` | `list[NodeInfo]` | Static node hierarchy in skeleton-row order. |
| `set_calibration(side, mcal_bytes)` | `int` | Write calibration data to a glove. |
| `drain_debug_events()` | `list[dict]` | Read and clear diagnostic events. |

Raw skeleton columns are ordered as:

```text
position x,y,z | quaternion w,x,y,z | scale x,y,z
```

See the examples for connection, calibration, recording, and visualization
patterns.
