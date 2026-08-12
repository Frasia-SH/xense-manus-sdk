#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

usage() {
    cat <<'EOF'
Usage: ./build.sh {python|cpp|clean}

  python  Build the manus_glove Python extension
  cpp     Build the minimal C++ client
  clean   Remove local build outputs
EOF
}

case "${1:-}" in
    python)
        python_executable=$(command -v python)
        pybind11_cmake_dir=$(python -c 'import pybind11; print(pybind11.get_cmake_dir())')
        cmake -S "$repo_root/bindings/python" -B "$repo_root/build/python" \
            -DCMAKE_PREFIX_PATH="$pybind11_cmake_dir" \
            -DPython_EXECUTABLE="$python_executable"
        cmake --build "$repo_root/build/python" -j
        ;;
    cpp)
        cmake -S "$repo_root/examples/cpp_minimal" -B "$repo_root/build/cpp"
        cmake --build "$repo_root/build/cpp" -j
        ;;
    clean)
        rm -rf "$repo_root/build"
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
