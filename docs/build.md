# Build and Runtime Notes

## Prerequisites

For the Python binding:

- CMake 3.15 or newer
- A C++17 compiler
- Python development headers
- `pybind11` and `numpy` in the active Python environment

For the C++ example:

- CMake 3.15 or newer
- A C++17 compiler
- ncurses development headers

## Python binding

```bash
./build.sh python
```

The CMake project uses the active Python interpreter through pybind11. If
pybind11 cannot be found, configure with its CMake directory explicitly:

```bash
cmake -S bindings/python -B build/python \
  -DCMAKE_PREFIX_PATH="$(python -c 'import pybind11; print(pybind11.get_cmake_dir())')"
cmake --build build/python -j
```

## C++ minimal client

```bash
./build.sh cpp
```

The executable is written to `build/cpp/SDKMinimalClient.out`. The CMake target
links the vendor library and bundled grpc/protobuf libraries, and embeds
`$ORIGIN`-relative RPATH entries so it is independent of the current directory.

## Docker and USB

The Dockerfiles are optional build environments. When using a privileged
container with USB passthrough, mount `/dev` but do not mount `/run/udev` or
start udev inside the container. Device rules belong on the host. The detailed
workflow is in `docs/DockerReadme.md`.

## Dependency inspection

```bash
ldd build/python/manus_glove*.so
ldd build/cpp/SDKMinimalClient.out
```

Any `not found` entry indicates a missing system dependency or an incorrect
runtime library path.
