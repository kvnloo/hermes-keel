#!/bin/sh
set -eu
# Unprivileged v2 phase. Runtime bytes are copied into the content-addressed package;
# privileged execution never references the mutable UID-1000 source runtime.
[ "$(id -u)" != 0 ] || { printf '%s\n' 'must run unprivileged' >&2; exit 1; }
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
OUT=${1:?absolute output directory required}
RUNTIME=${2:?exact reviewed Ollama runtime binary required}
case "$OUT" in /*) ;; *) printf '%s\n' 'output must be absolute' >&2; exit 1;; esac
[ ! -e "$OUT" ] || { printf '%s\n' 'output already exists' >&2; exit 1; }
cd "$SCRIPT_DIR/.."
exec /usr/bin/python3 -m privileged_broker.package_v2 build --runtime "$RUNTIME" --output "$OUT"
