#!/bin/sh
set -eu
# Root phase accepts only a sealed absolute package and Captain-confirmed manifest hash.
[ "$(id -u)" = 0 ] || [ "${KEEL_ROOTLESS_FIXTURE:-0}" = 1 ] || { printf '%s\n' 'root required' >&2; exit 1; }
PACKAGE=${1:?sealed package directory required}
EXPECTED=${2:?Captain-confirmed MANIFEST sha256 required}
ROOT=${KEEL_INSTALL_ROOT:-}
TRUST_ROOT=${KEEL_TRUST_ROOT:-/root}
TRUST_UID=${KEEL_TRUST_UID:-0}
case "$PACKAGE" in /*) ;; *) printf '%s\n' 'package must be absolute' >&2; exit 1;; esac
case "$EXPECTED" in *[!0-9a-f]*|'') printf '%s\n' 'bad manifest hash' >&2; exit 1;; esac
[ "${#EXPECTED}" = 64 ] || exit 1
[ -d "$PACKAGE" ] && [ ! -L "$PACKAGE" ] || exit 1
case "$PACKAGE/" in "$TRUST_ROOT"/*) ;; *) printf '%s\n' 'package outside trusted staging root' >&2; exit 1;; esac
walk=$PACKAGE
while :; do
  [ ! -L "$walk" ] || { printf '%s\n' 'symlink in package ancestor chain' >&2; exit 1; }
  [ "$(/usr/bin/stat -c %u "$walk")" = "$TRUST_UID" ] || { printf '%s\n' 'untrusted package ancestor owner' >&2; exit 1; }
  perm=$(/usr/bin/stat -c %a "$walk"); perm=$((0$perm))
  [ $((perm & 0022)) = 0 ] || { printf '%s\n' 'writable package ancestor' >&2; exit 1; }
  [ "$walk" = "$TRUST_ROOT" ] && break
  parent=${walk%/*}; [ -n "$parent" ] || parent=/
  [ "$parent" != "$walk" ] || exit 1
  walk=$parent
done
OWNER=$(/usr/bin/stat -c %u "$PACKAGE")
MODE=$(/usr/bin/stat -c %a "$PACKAGE")
[ "$OWNER" = "$TRUST_UID" ] && [ "$MODE" = 555 ] || { printf '%s\n' 'package must first be sealed trusted-owned mode 0555' >&2; exit 1; }
[ "$(/usr/bin/sha256sum "$PACKAGE/MANIFEST" | /usr/bin/cut -d ' ' -f 1)" = "$EXPECTED" ] || { printf '%s\n' 'manifest hash mismatch' >&2; exit 1; }
for name in MANIFEST core.py broker.py package_v2.py hermes-privileged-broker.sudoers install.sh uninstall.sh runtime/ollama; do
  [ -f "$PACKAGE/$name" ] && [ ! -L "$PACKAGE/$name" ] || exit 1
  [ "$(/usr/bin/stat -c %u "$PACKAGE/$name")" = "$TRUST_UID" ] || exit 1
  [ "$(/usr/bin/stat -c %a "$PACKAGE/$name")" = 444 ] || exit 1
done
(cd "$PACKAGE" && /usr/bin/sha256sum -c MANIFEST)

# Stage on each destination filesystem; policy is parsed before any authority is activated.
LIB=$ROOT/usr/local/lib/hermes-privileged-broker
STATE=$ROOT/var/lib/hermes-privileged-broker
STAGE=$LIB.stage.$$
POLICY=$ROOT/etc/sudoers.d/hermes-privileged-broker
SBIN=$ROOT/usr/local/sbin/hermes-privileged-broker
POLICY_STAGE=$ROOT/etc/sudoers.d/.hermes-privileged-broker.$$
SBIN_STAGE=$ROOT/usr/local/sbin/.hermes-privileged-broker.$$
PUBLISHED_LIB=0
PUBLISHED_SBIN=0
PUBLISHED_STATE=0
PUBLISHED_POLICY=0
PHASE_MANIFEST=$ROOT/var/tmp/hermes-keel-install-phase.$$
cleanup() {
  /usr/bin/rm -rf "$STAGE"; /usr/bin/rm -f "$POLICY_STAGE" "$SBIN_STAGE"
  [ "$PUBLISHED_POLICY" = 0 ] || /usr/bin/rm -f "$POLICY"
  [ "$PUBLISHED_STATE" = 0 ] || /usr/bin/rm -rf "$STATE"
  [ "$PUBLISHED_SBIN" = 0 ] || /usr/bin/rm -f "$SBIN"
  [ "$PUBLISHED_LIB" = 0 ] || /usr/bin/rm -rf "$LIB"
  /usr/bin/rm -f "$PHASE_MANIFEST"
}
trap cleanup EXIT HUP INT TERM
phase() {
  printf '%s\n' "$1" > "$PHASE_MANIFEST"
  /usr/bin/python3 -c 'import os,sys; f=os.open(sys.argv[1],os.O_RDONLY); os.fsync(f); os.close(f)' "$PHASE_MANIFEST"
  [ "${KEEL_FAIL_AFTER:-}" != "$1" ] || { printf '%s\n' "injected failure after $1" >&2; exit 97; }
}
verify_parent() {
  parent=$1
  allow_sticky=${2:-0}
  [ -d "$parent" ] && [ ! -L "$parent" ] || { printf '%s\n' "unsafe or missing install parent: $parent" >&2; exit 1; }
  [ "$(/usr/bin/stat -c %u "$parent")" = "$TRUST_UID" ] || { printf '%s\n' "untrusted install parent owner: $parent" >&2; exit 1; }
  parent_mode=$(/usr/bin/stat -c %a "$parent"); parent_mode=$((0$parent_mode))
  if [ $((parent_mode & 0022)) != 0 ]; then
    [ "$allow_sticky" = 1 ] && [ $((parent_mode & 01000)) != 0 ] || {
      printf '%s\n' "writable install parent: $parent" >&2; exit 1;
    }
  fi
}
# All destination collisions and filesystem assumptions are rejected before publication.
[ ! -e "$LIB" ] && [ ! -L "$LIB" ] || { printf '%s\n' 'installed library already exists; uninstall first' >&2; exit 1; }
[ ! -e "$SBIN" ] && [ ! -L "$SBIN" ] || exit 1
[ ! -e "$POLICY" ] && [ ! -L "$POLICY" ] || exit 1
[ ! -e "$STATE" ] && [ ! -L "$STATE" ] || { printf '%s\n' 'state already exists; recovery/uninstall required' >&2; exit 1; }
# Shared ancestors are authority boundaries, never installer-owned objects.
# They must already exist and their modes are inspected, not repaired.
verify_parent "$ROOT/usr/local/lib"
verify_parent "$ROOT/usr/local/sbin"
verify_parent "$ROOT/etc/sudoers.d"
verify_parent "$ROOT/var/lib"
verify_parent "$(/usr/bin/dirname "$PHASE_MANIFEST")" 1
/usr/bin/install -d -o "$TRUST_UID" -m 0700 "$STAGE"
/usr/bin/install -o "$TRUST_UID" -m 0755 "$PACKAGE/core.py" "$PACKAGE/broker.py" "$PACKAGE/package_v2.py" "$STAGE/"
/usr/bin/install -d -o "$TRUST_UID" -m 0755 "$STAGE/runtimes/sha256-d0758d38ac5882a2c68fd930d0c1220af1952469fa9f30c268746d4021709bf4"
/usr/bin/install -o "$TRUST_UID" -m 0755 "$PACKAGE/runtime/ollama" "$STAGE/runtimes/sha256-d0758d38ac5882a2c68fd930d0c1220af1952469fa9f30c268746d4021709bf4/ollama"
/usr/bin/install -o "$TRUST_UID" -m 0440 "$PACKAGE/hermes-privileged-broker.sudoers" "$POLICY_STAGE"
if [ "${KEEL_ROOTLESS_FIXTURE:-0}" = 1 ]; then /bin/sh -n "$PACKAGE/install.sh"; else /usr/sbin/visudo -cf "$POLICY_STAGE"; fi
(cd "$STAGE" && /usr/bin/sha256sum core.py broker.py package_v2.py runtimes/sha256-d0758d38ac5882a2c68fd930d0c1220af1952469fa9f30c268746d4021709bf4/ollama) > "$STAGE/installed.sha256"
/usr/bin/chown "$TRUST_UID" "$STAGE/installed.sha256"; /usr/bin/chmod 0444 "$STAGE/installed.sha256"
/usr/bin/python3 -c 'import os,sys; [os.fsync(os.open(p,os.O_RDONLY)) for p in sys.argv[1:]]' "$STAGE/core.py" "$STAGE/broker.py" "$STAGE/installed.sha256" "$POLICY_STAGE"
/usr/bin/mv "$STAGE" "$LIB"
PUBLISHED_LIB=1
phase library
/usr/bin/ln -s "$LIB/broker.py" "$SBIN_STAGE"
/usr/bin/mv "$SBIN_STAGE" "$SBIN"
PUBLISHED_SBIN=1
phase launcher
/usr/bin/install -d -o "$TRUST_UID" -m 0700 "$STATE" "$STATE/queue"
PUBLISHED_STATE=1
phase state
[ -e "$STATE/approval.key" ] || { umask 077; /usr/bin/dd if=/dev/urandom of="$STATE/approval.key" bs=32 count=1 status=none; }
/usr/bin/chown "$TRUST_UID" "$STATE/approval.key"; /usr/bin/chmod 0600 "$STATE/approval.key"
phase key
/usr/bin/mv "$POLICY_STAGE" "$POLICY"
PUBLISHED_POLICY=1
phase policy
/usr/bin/python3 -c 'import os,sys; [os.fsync(os.open(p,os.O_RDONLY|os.O_DIRECTORY)) for p in sys.argv[1:]]' "$ROOT/usr/local/lib" "$ROOT/usr/local/sbin" "$ROOT/etc/sudoers.d" "$STATE"
PUBLISHED_LIB=0
PUBLISHED_SBIN=0
PUBLISHED_STATE=0
PUBLISHED_POLICY=0
/usr/bin/rm -f "$PHASE_MANIFEST"
trap - EXIT HUP INT TERM
printf '%s\n' 'Installed sealed broker package. No service was changed.'
