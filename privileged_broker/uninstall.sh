#!/bin/sh
set -eu
test "$(id -u)" = 0 || { echo 'run locally with sudo' >&2; exit 1; }
STATE=/var/lib/hermes-privileged-broker
DROPIN=/etc/systemd/system/ollama.service.d/10-hermes-cuda-runtime.conf
# Never silently remove code while a broker-created runtime effect may still be active.
[ ! -e "$DROPIN" ] && [ ! -L "$DROPIN" ] || {
  printf '%s\n' 'recovery required: broker drop-in still exists; rollback and verify service first' >&2
  exit 2
}
/usr/bin/rm -f /etc/sudoers.d/hermes-privileged-broker /usr/local/sbin/hermes-privileged-broker
/usr/bin/rm -rf /usr/local/lib/hermes-privileged-broker
# Remove reusable authority and pending work, while retaining append-only audit/checkpoint evidence.
/usr/bin/rm -f "$STATE/approval.key" "$STATE/approvals.jsonl" "$STATE/execute.lock"
/usr/bin/rm -rf "$STATE/queue" "$STATE/inflight"
[ ! -e /etc/sudoers.d/hermes-privileged-broker ]
[ ! -e /usr/local/sbin/hermes-privileged-broker ]
[ ! -e /usr/local/lib/hermes-privileged-broker ]
[ ! -e "$STATE/approval.key" ]
printf '%s\n' 'Code, policy, queue, and signing authority removed; ledger/checkpoint audit evidence retained.'
