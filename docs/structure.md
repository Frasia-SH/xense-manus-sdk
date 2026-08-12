# Repository Structure

## `vendor/manus`

Vendor-provided MANUS headers and prebuilt shared libraries. These files are
consumed by the examples and binding; they are not compiled in this repository.

## `runtime/linux-x86_64`

Bundled grpc, grpc++, protobuf, and gpr libraries required by the vendor SDK.
The platform is explicit so another architecture can be added without mixing
incompatible binaries.

## `bindings/python`

The Xense C++/pybind11 wrapper and Python examples. The wrapper owns SDK
callbacks and exposes the latest cached frame to Python; it does not queue all
incoming frames.

## `examples/cpp_minimal`

The minimal vendor-style C++ client, kept as a smoke-test and reference for
direct SDK usage.

## `calibration`, `docker`, and `docs`

Calibration inputs, optional container build environments, and repository
documentation are kept outside the implementation directories.
