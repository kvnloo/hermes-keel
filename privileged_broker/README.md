# Captain-gated privileged broker

Status: v2 implemented and rootless-rehearsed; **not installed, not approved, and no Ollama mutation performed**. All v1 and historical request shapes are retired evidence and are rejected.

## Chosen mechanism

A root-owned, stdlib-only fixed-action program plus one exact sudoers entry is smaller and easier to audit than a network daemon, arbitrary systemd control API, or password automation. There is no listener. The only passwordless command is the literal, argument-free `hermes-privileged-broker execute`; it reads one root-owned queue packet created by the authenticated approval path. Approval uses `pkexec`, so an agent may cause an authentication dialog but cannot create a receipt without Captain OS authentication and typing the displayed full request hash. No password enters Hermes or this code.

Trust boundary:

`canonical running Kanban task+run containing request hash -> unprivileged request JSON -> Captain pkexec approval + hash confirmation -> root HMAC receipt and root queue -> argument-free executor -> durable consume fsync -> fixed Ollama action -> health/smoke -> result or rollback`

The HMAC key only protects root-owned receipt integrity; it does not replace Captain authentication. Execution rechecks exact packet, host, task/run active state, canonical body hash, expiry, receipt MAC, uniqueness and replay ledger. The fixed action contains no caller-selected executable, argv, environment, service, paths, listener, model, threshold, or rollback.

## Bootstrap (sealed two-phase ceremony; not yet approved)

Never run the installer from this mutable checkout. First run unprivileged
`./build-package.sh /var/tmp/hermes-broker-package-UNIQUE /absolute/reviewed/ollama`, inspect every byte, and
record the printed `MANIFEST` SHA-256. The package contains the installer itself.
During a future specifically approved ceremony, transfer that exact package to
root ownership without following links (`sudo chown -hR root:root ABSOLUTE_PACKAGE`),
then run `sudo /bin/sh ABSOLUTE_PACKAGE/install.sh ABSOLUTE_PACKAGE FULL_MANIFEST_SHA256`.
The package must be under a non-user-renamable parent after ownership transfer.

The v2 package contains the exact reviewed runtime as `runtime/ollama`. Installation
publishes it at the content-addressed root-owned path encoded by `fixed_operation`;
the later service ceremony therefore never executes the UID-1000 mutable source path.
The root phase rejects symlinks, non-root ownership, mutable modes, wrong hashes,
relative paths, and pre-existing installation state. It stages code and policy on
their destination filesystems, parses staged policy before activation, fsyncs
files/directories, and places sudoers last. Failure before authority activation
removes staging. It does not start a daemon or modify Ollama. The root-only random
HMAC key authenticates both approval receipts and the chained execution ledger;
it is never exposed to callers and grants no command-selection authority.

## Request, approval, execution

1. A running canonical task/run must contain the exact SHA-256 of its request JSON in its body/comment projection visible to the configured board DB. Only after independent review, create with `python privileged_broker/broker.py create-request --task t_... --run N --package /sealed/root-owned/package --manifest-sha256 FULL_HASH --output request.json`. The request binds v2, package hash, content-addressed installed runtime, and board descriptor identity. This repository contains only a template; no live request is produced by rehearsal.
2. Send Captain the approval card below and request file/hash. Captain runs `pkexec /usr/local/sbin/hermes-privileged-broker approve /absolute/request.json`, inspects the complete fixed action, and types the full hash. The helper requires authenticated `PKEXEC_UID=1000` and a non-writable, UID-1000-owned regular packet beneath the sealed request root. This atomically writes the signed approval and root-owned queue packet.
3. Any worker may run only `sudo /usr/local/sbin/hermes-privileged-broker execute`. Arguments are not allowed by sudoers. Consumption is fsynced before mutation. Reuse fails.

Telegram card template:

```text
🔐 ROOT ACTION — APPROVE/DENY
Host: groot
Action: ollama-system-runtime-switch-v2 (Ollama 0.16.1 → sealed 0.32.14 CUDA)
Binary: d0758d…9bf4
Listen/store: 127.0.0.1:11434 / /mnt/zer0models/zer0-models/ollama
Risk: brief local API outage; model smoke loads qwen2.5:3b
Rollback: remove one drop-in, daemon-reload, restart sealed /usr/bin/ollama ab2736…353a
Expires: <UTC>; Task/run: <id>/<run>
Request: <full SHA-256>
One action: run the shown pkexec command and type the FULL hash; otherwise do nothing/deny.
```

Free-form “yes”, Telegram sender text, ambient `$USER`, a callback lacking OS authentication, and task prose without the exact hash are not approval.

## Fixed production transaction

Request creation captures and seals the effective fragment and drop-in hashes,
effective ExecStart/relevant environment, process PID/resolved executable/hash/version,
all port-11434 listener identities, and a byte-manifest hash of the model store.
Execution re-captures the complete state immediately before mutation and rejects
drift. Mutation uses `O_EXCL|O_NOFOLLOW`, fixed bytes, fsync, daemon-reload, and restart.
Health requires exactly one expected process, the sealed executable/version, only
loopback IPv4/IPv6 listeners owned by that process, unchanged model-store integrity,
explicit CUDA backend with one GPU, exact deterministic `OK`, and at least 100 eval
tok/s. Missing or unknown telemetry fails closed.

Rollback first re-verifies the sealed fragment, unrelated drop-ins, and model store;
then removes only the fixed drop-in, fsyncs, checks reload and restart status, and
verifies restored fragment/drop-ins/environment/executable/hash/version/model store
and loopback listener policy. Any query, command, or post-state mismatch makes
`rollback_ok=false`; exact command status/stdout/stderr is retained in the authenticated
result record rather than suppressed.

Crash policy is fail-closed: crash before consume causes no mutation; after consume makes the request permanently spent. A crash after mutation may require the documented operator recovery because no daemon is present to resume rollback; ledger ambiguity never authorizes retry. Result-receipt failure likewise leaves the consume record and requires inspection. Rollback failure is recorded `rollback_ok=false` and requires local recovery; it never retries or widens authority.

## Threat model coverage

Tests cover missing/forged/tampered/duplicate approval; packet mutation; stale expiry;
wrong host/action/task/run; extra command/args/env/service fields; terminal state; replay;
crash-after-consume; symlink/malformed/tampered ledger; rollback command evidence;
pre-state drift; public/unknown/duplicate listeners; sealed package bytes; health rollback;
malicious health-output redaction; and fixed paths/service/argv. `flock` serializes
execution. Every consume/result record carries a sequence, previous-record hash,
request/task/run/nonce identity, record hash, and HMAC and is fsynced with its directory.
The full chain is verified before action and after append; truncation, reordering,
editing, wrong key, and replay fail closed. A durable consume with no result remains
an explicitly spent, unknown-outcome operation requiring inspection.

Residual bootstrap assumptions: Captain must compare the full manifest hash, the
ownership-transfer target must be a unique absolute package beneath a safe parent,
`pkexec` policy must authenticate Kevin rather than permit active-session authorization
without challenge, the configured board must remain canonical, and root must protect
installed code/state/key. Independent re-review is mandatory. This implementation
and its builders do not certify bootstrap suitability.

## Rollback/uninstall

If an attempted action is unhealthy, code removes only `/etc/systemd/system/ollama.service.d/10-hermes-cuda-runtime.conf`, reloads systemd and restarts the original unit. For broker uninstall run `sudo ./uninstall.sh`. It removes sudoers and executable code while retaining `/var/lib/hermes-privileged-broker` evidence to prevent accidental replay; archive it before manual deletion.
