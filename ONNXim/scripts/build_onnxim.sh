#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ONNXIM_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-${ONNXIM_ROOT}/build}"
BUILD_TYPE="${CMAKE_BUILD_TYPE:-Release}"

if ! command -v conan >/dev/null 2>&1; then
  echo "error: Conan is required. Install Conan 1.x with: pip3 install 'conan<2'" >&2
  exit 1
fi

CONAN_VERSION="$(conan --version 2>/dev/null || true)"
if [[ "${CONAN_VERSION}" != Conan\ version\ 1* ]]; then
  echo "error: This project currently expects Conan 1.x because CMake uses conanbuildinfo.cmake." >&2
  echo "Install a 1.x release with: pip3 install 'conan<2'" >&2
  exit 1
fi

conan_args=(install .. --build=missing)
if grep -q '_GLIBCXX_USE_CXX11_ABI=0' "${ONNXIM_ROOT}/CMakeLists.txt"; then
  cxx_bin="${CXX:-g++}"
  if command -v "${cxx_bin}" >/dev/null 2>&1; then
    compiler_banner="$("${cxx_bin}" --version 2>/dev/null | head -n 1 || true)"
    if [[ "${compiler_banner}" == *"g++"* || "${compiler_banner}" == *"gcc"* || "${compiler_banner}" == *"GNU"* ]]; then
      conan_args+=(-s compiler.libcxx=libstdc++)
    fi
  fi
fi

mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

echo "[1/3] ${conan_args[*]}"
conan "${conan_args[@]}"

cmake_args=(
  -DCMAKE_BUILD_TYPE="${BUILD_TYPE}"
  -DBUILD_ONNXIM_TESTS=OFF
)

echo "[2/3] cmake .. ${cmake_args[*]} $*"
cmake .. "${cmake_args[@]}" "$@"

if command -v nproc >/dev/null 2>&1; then
  jobs="$(nproc)"
elif command -v sysctl >/dev/null 2>&1; then
  jobs="$(sysctl -n hw.ncpu)"
else
  jobs=8
fi

echo "[3/3] cmake --build . -j ${jobs}"
cmake --build . -j "${jobs}"
