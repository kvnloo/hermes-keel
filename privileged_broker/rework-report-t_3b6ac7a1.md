# Keel privileged broker rework evidence — t_3b6ac7a1

Status: implementation reworked and locally regression-tested. **Not independently approved, not certified for bootstrap, not installed, and not executed against Ollama.** Fresh review `t_28a8c942` is graph-gated on this repair and Luna synthesis `t_aa62402d`; that reviewer owns any suitability verdict.

## Safety boundary observed

No `sudo`, `pkexec`, approval creation, installation, root mutation, systemd/service change, or Ollama switch was performed. Work stayed in `/workspace/zer0/oss/hermes-keel/privileged_broker`. Unrelated untracked `token_master/` and `docs/token-master-shadow.md` were not modified.

## Finding repairs

### F-001 — rollback truth

- `OllamaBackend.rollback()` now checks every query, daemon-reload, and restart.
- Command failures preserve exact argv, exit status, stdout, and stderr in the authenticated result error.
- Rollback verifies fragment bytes, unrelated drop-ins, effective environment/ExecStart, executable/hash/version, model-store manifest, daemon uniqueness, and loopback listeners before it can return.
- Any query, command, or restored-state ambiguity raises; `execute()` records `rollback_ok=false` and the exact rollback exception rather than suppressing it.
- Regression: `test_f001_rollback_failure_preserves_exact_status_and_never_claims_success`.

### F-002 — sealed effective pre-state and rollback target

- Request schema advanced to fixed action v2.
- Production `create-request` captures effective fragment/drop-in paths and hashes, ExecStart, relevant environment, active/MainPID, resolved process executable/hash/version, all port-11434 listener identities, all Ollama process PIDs, and a model-store byte-manifest hash.
- The complete snapshot is request-hash/approval-bound and re-captured immediately before mutation.
- Rollback rejects drift in immutable rollback target bytes/config/model store and verifies the restored state; PID changes caused by the intended restart are permitted only while daemon uniqueness, identity, and listener policy remain exact.
- Regression: `test_f002_complete_pre_state_is_bound_and_drift_rejected_before_write`.

### F-003 — strict health proof

- `/proc` inspection requires exactly one Ollama process and it must equal systemd MainPID.
- Every port-11434 listener must be IPv4/IPv6 loopback and owned by that PID; wildcard, LAN/tailnet, missing-PID, duplicate, empty, and malformed telemetry fail closed.
- Executable realpath/hash and API/CLI version must be exact.
- CUDA proof requires loaded `libcuda`/`libcublas`, `/dev/nvidiactl`, and exactly `/dev/nvidia0` opened by the daemon; unreadable/unknown telemetry fails closed.
- Model-store manifest must remain byte-identical.
- Fixed smoke requires exact `OK` and at least 100 eval tokens/second.
- Regression: `test_f003_public_unknown_and_duplicate_runtime_fail_closed`.

### F-004 — sealed package and atomic bootstrap

- Added unprivileged `build-package.sh`; it copies a fixed file set (including installer), emits per-file SHA-256 `MANIFEST` plus a Captain-confirmable manifest hash, and seals package/files mode 0555/0444.
- Root installer refuses mutable checkout use: package and every opened source must be root-owned, immutable-mode, non-symlink regular files under an absolute path, with the Captain-confirmed manifest hash and all file hashes matching.
- Documentation requires unique safe-parent package placement and no-follow root ownership transfer before invoking the packaged installer.
- Installer uses absolute commands/sanitized fixed inputs, stages code and policy on destination filesystems, parses policy before activation, fsyncs staged files and destination directories, rejects pre-existing library state, and places sudoers last. Trap cleanup removes pre-activation staging.
- Regression: `test_f004_unprivileged_builder_emits_self_verifying_sealed_package` plus shell syntax and visudo parse.

### F-005 — authenticated durable ledger

- Every consume/result record now includes sequence, previous record hash, record hash, HMAC, request hash, operation ID, task, run, nonce hash, and timestamp.
- Full chain verification occurs before action, before each append, and after append.
- Durable append handles short writes, fsyncs the record and parent directory, and opens ledgers with `O_NOFOLLOW` plus owner/mode checks.
- Edits, reordering, wrong key, malformed input, symlinks, and replay fail closed. A consumed record without result remains permanently spent/unknown-outcome.
- Regression: `test_f005_chain_detects_edit_truncation_reorder_and_wrong_key`; prior crash/replay and malformed-ledger adversarial tests retained.

## Additional attack coverage retained/retested

Missing/forged/tampered/duplicate approval; expiry mutation; wrong host/action/task/run; arbitrary command/args/environment/service/path schema injection; terminal task/run; replay; concurrent consume semantics; crash after consume; result suppression; symlink/malformed/tampered ledger; malicious health output suppression; fixed argv/service/listener; rollback exception; package symlink/hash/mode invariants; exact sudoers command; uninstall retains evidence and removes only policy/code.

## Executed verification

- `python -m pytest -q` → **53 passed**.
- `python -m unittest discover -v` → **46 passed** (whole repository discovery).
- `python -m py_compile privileged_broker/*.py` → pass.
- `sh -n privileged_broker/build-package.sh privileged_broker/install.sh privileged_broker/uninstall.sh` → pass.
- `visudo -cf privileged_broker/hermes-privileged-broker.sudoers` → parsed OK.
- `git diff --check` → pass.
- Static scan for `shell=True`, `subprocess.Popen`, `os.system(`, and `NOPASSWD: ALL` → no matches.
- `shellcheck` was unavailable; this is reported rather than inferred as passing.

## SHA-256 manifest

- `core.py` `822fa72f5ed6a88129556d68130eec693a93c5a9185fe36995465276c9826d32`
- `broker.py` `2e9a98ed163dc78c29759dab23d419287405b19160a1f48980f124ea48ff1e60`
- `build-package.sh` `e443bfe798eb6af99faceb5ce4a160ccbb6ed1e372b8da0816dbea0fd11ff5b4`
- `install.sh` `2d93710fde9cdd1cbf429aedfa7c6f99087671be845d79bb73de76321f68ee3d`
- `uninstall.sh` `60c87fbc1a9448b5036ce0d354e545f2f15d9339261cbf8a3bb3f1a11f0d371e`
- `hermes-privileged-broker.sudoers` `259551c7e8874ce402e7408ef5b31820a1d940e7916b683d4d695a87a1211f5f`
- `README.md` `065468ca9f768f80953ad1ffe68a3df4aa825e1388a3467cbd4986bc72c70053`
- `test_broker.py` `30fa1f456efff35f10eb1d0a1709a6d3417ede5d95f990db427b61ba9c102a70`
- retained adversarial tests `test_adversarial_review.py` `77bb976619a6ee79f8a8ee3c73ea74bee9df41f2b295a94bbaef7986677534610`
- new regressions `test_rework.py` `634349a9e4fa408a67fa6abdcfc28c4579eb4f05b7f9e5cf524f7253e0ffe28e`

## Review handoff

This report records implementation and test evidence only. It deliberately does not claim that F-001–F-005 are authoritatively closed or that bootstrap is suitable. Reviewer `t_28a8c942` must inspect cold, consume ranked Luna synthesis when released, attack package TOCTOU/partial-activation and runtime telemetry independently, and issue the verdict.
