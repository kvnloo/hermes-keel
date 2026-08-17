#!/bin/sh
set -eu
# Root phase accepts only a sealed absolute package and Captain-confirmed manifest hash.
[ "$(id -u)" = 0 ] || { printf '%s\n' 'root required' >&2; exit 1; }
PACKAGE=${1:?sealed package directory required}
EXPECTED=${2:?Captain-confirmed MANIFEST sha256 required}
case "$PACKAGE" in /*) ;; *) printf '%s\n' 'package must be absolute' >&2; exit 1;; esac
case "$EXPECTED" in *[!0-9a-f]*|'') printf '%s\n' 'bad manifest hash' >&2; exit 1;; esac
[ "${#EXPECTED}" = 64 ] || exit 1
[ -d "$PACKAGE" ] && [ ! -L "$PACKAGE" ] || exit 1
OWNER=$(/usr/bin/stat -c %u "$PACKAGE")
MODE=$(/usr/bin/stat -c %a "$PACKAGE")
[ "$OWNER" = 0 ] && [ "$MODE" = 555 ] || { printf '%s\n' 'package must first be sealed root-owned mode 0555' >&2; exit 1; }
[ "$(/usr/bin/sha256sum "$PACKAGE/MANIFEST" | /usr/bin/cut -d ' ' -f 1)" = "$EXPECTED" ] || { printf '%s\n' 'manifest hash mismatch' >&2; exit 1; }
for name in MANIFEST core.py broker.py package_v2.py hermes-privileged-broker.sudoers install.sh uninstall.sh runtime/ollama; do
  [ -f "$PACKAGE/$name" ] && [ ! -L "$PACKAGE/$name" ] || exit 1
  [ "$(/usr/bin/stat -c %u "$PACKAGE/$name")" = 0 ] || exit 1
  [ "$(/usr/bin/stat -c %a "$PACKAGE/$name")" = 444 ] || exit 1
done
(cd "$PACKAGE" && /usr/bin/sha256sum -c MANIFEST)

# Stage on each destination filesystem; policy is parsed before any authority is activated.
LIB=/usr/local/lib/hermes-privileged-broker
STATE=/var/lib/hermes-privileged-broker
STAGE=$LIB.stage.$$
POLICY_STAGE=/etc/sudoers.d/.hermes-privileged-broker.$$
SBIN_STAGE=/usr/local/sbin/.hermes-privileged-broker.$$
PUBLISHED_LIB=0
PUBLISHED_SBIN=0
cleanup() {
  /usr/bin/rm -rf "$STAGE"; /usr/bin/rm -f "$POLICY_STAGE" "$SBIN_STAGE"
  [ "$PUBLISHED_SBIN" = 0 ] || /usr/bin/rm -f /usr/local/sbin/hermes-privileged-broker
  [ "$PUBLISHED_LIB" = 0 ] || /usr/bin/rm -rf "$LIB"
}
trap cleanup EXIT HUP INT TERM
# All destination collisions and filesystem assumptions are rejected before publication.
[ ! -e "$LIB" ] && [ ! -L "$LIB" ] || { printf '%s\n' 'installed library already exists; uninstall first' >&2; exit 1; }
[ ! -e /usr/local/sbin/hermes-privileged-broker ] && [ ! -L /usr/local/sbin/hermes-privileged-broker ] || exit 1
[ ! -e /etc/sudoers.d/hermes-privileged-broker ] && [ ! -L /etc/sudoers.d/hermes-privileged-broker ] || exit 1
[ ! -e "$STATE" ] && [ ! -L "$STATE" ] || { printf '%s\n' 'state already exists; recovery/uninstall required' >&2; exit 1; }
/usr/bin/install -d -o root -g root -m 0700 "$STAGE"
/usr/bin/install -o root -g root -m 0755 "$PACKAGE/core.py" "$PACKAGE/broker.py" "$PACKAGE/package_v2.py" "$STAGE/"
/usr/bin/install -d -o root -g root -m 0755 "$STAGE/runtimes/sha256-d0758d38ac5882a2c68fd930d0c1220af1952469fa9f30c268746d4021709bf4"
/usr/bin/install -o root -g root -m 0755 "$PACKAGE/runtime/ollama" "$STAGE/runtimes/sha256-d0758d38ac5882a2c68fd930d0c1220af1952469fa9f30c268746d4021709bf4/ollama"
/usr/bin/install -o root -g root -m 0440 "$PACKAGE/hermes-privileged-broker.sudoers" "$POLICY_STAGE"
/usr/sbin/visudo -cf "$POLICY_STAGE"
(cd "$STAGE" && /usr/bin/sha256sum core.py broker.py package_v2.py runtimes/sha256-d0758d38ac5882a2c68fd930d0c1220af1952469fa9f30c268746d4021709bf4/ollama) > "$STAGE/installed.sha256"
/usr/bin/chown root:root "$STAGE/installed.sha256"; /usr/bin/chmod 0444 "$STAGE/installed.sha256"
/usr/bin/python3 -c 'import os,sys; [os.fsync(os.open(p,os.O_RDONLY)) for p in sys.argv[1:]]' "$STAGE/core.py" "$STAGE/broker.py" "$STAGE/installed.sha256" "$POLICY_STAGE"
/usr/bin/mv "$STAGE" "$LIB"
PUBLISHED_LIB=1
/usr/bin/ln -s "$LIB/broker.py" "$SBIN_STAGE"
/usr/bin/mv "$SBIN_STAGE" /usr/local/sbin/hermes-privileged-broker
PUBLISHED_SBIN=1
/usr/bin/install -d -o root -g root -m 0700 "$STATE" "$STATE/queue"
[ -e "$STATE/approval.key" ] || { umask 077; /usr/bin/dd if=/dev/urandom of="$STATE/approval.key" bs=32 count=1 status=none; }
/usr/bin/chown root:root "$STATE/approval.key"; /usr/bin/chmod 0600 "$STATE/approval.key"
/usr/bin/mv "$POLICY_STAGE" /etc/sudoers.d/hermes-privileged-broker
/usr/bin/python3 -c 'import os; [os.fsync(os.open(p,os.O_RDONLY|os.O_DIRECTORY)) for p in ("/usr/local/lib","/usr/local/sbin","/etc/sudoers.d","/var/lib/hermes-privileged-broker")]'
PUBLISHED_LIB=0
PUBLISHED_SBIN=0
trap - EXIT HUP INT TERM
printf '%s\n' 'Installed sealed broker package. No service was changed.'
