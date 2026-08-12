# Xense MANUS SDK

Linux runtime package for reading MANUS glove data from Xense applications.
It contains the vendor MANUS SDK runtime, the Xense-maintained `manus_glove`
Python binding, and minimal C++/Python examples.

## Scope

- MANUS SDK version: `3.1.1`
- Supported platform: Linux `x86_64`
- Primary API: Python module `manus_glove`
- Connection modes: integrated, local Core, and remote Core
- Vendor libraries: prebuilt; this repository does not build the MANUS SDK

## Layout

```text
xense-manus-sdk/
├── vendor/manus/                 # MANUS headers and SDK shared libraries
├── runtime/linux-x86_64/         # Bundled grpc/protobuf runtime libraries
├── bindings/python/
│   ├── src/                      # C++ pybind11 implementation
│   └── examples/                 # Python usage and diagnostics examples
├── examples/cpp_minimal/         # Minimal C++ client
├── calibration/                  # Example .mcal files
├── docker/                       # Optional build environments
├── docs/                         # Build and structure documentation
├── build.sh                      # Unified build entry point
└── license/                      # Vendor license
```

## Build Python binding

Use the same Python environment that will import the extension:

```bash
python -m pip install pybind11 numpy
./build.sh python
```

The module is generated at:

```text
build/python/manus_glove*.so
```

Run the basic example with optional calibration directory:

```bash
python bindings/python/examples/example.py \
  --calibration-dir calibration
```

## Build C++ example

```bash
./build.sh cpp
./build/cpp/SDKMinimalClient.out
```

The executable uses `$ORIGIN`-relative RPATH entries and can be launched from
any working directory.

## Runtime requirements

The vendor library requires system libraries including `libudev`,
`libusb-1.0`, `libzmq`, pthreads, zlib, and the standard C/C++ runtime. The
repository bundles grpc, grpc++, protobuf, and gpr libraries under
`runtime/linux-x86_64`.

For Docker and USB device permissions, see `docs/build.md` and
`docs/DockerReadme.md`.

## API documentation

The Python API and array layouts are documented in
`bindings/python/README.md`.
