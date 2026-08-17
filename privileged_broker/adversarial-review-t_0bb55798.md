# Independent adversarial review — t_0bb55798

Verdict: **CHANGES REQUIRED / NOT SUITABLE FOR BOOTSTRAP**

Scope was reconstructed cold from parent `t_9966a8c5`, superseded review `t_a2da5d22`, and the untracked broker sources. No sudo/pkexec command was run, no root file was installed, no approval was created, and Ollama was not mutated. The expired parent request remains terminal and forbidden.

## Blocking findings

### F-001 — rollback reports success without checking recovery (HIGH)

`privileged_broker/core.py:185-186` unlinks the drop-in and invokes `systemctl daemon-reload` and `systemctl restart`, but discards both return codes. `execute()` therefore records `rollback_ok=true` whenever the Python method returns, even when daemon reload and restart both fail. This suppresses the actual recovery failure and violates fail-closed rollback evidence.

Required change: make rollback verify every command, verify the original service is active, verify the exact old runtime/version and localhost-only listener, and raise on any failed or ambiguous predicate. Add mutation tests for daemon-reload failure, restart failure, inactive post-state, wrong version/binary, and public listener.

### F-002 — expected pre-state and rollback target are not actually sealed (HIGH)

`core.py:66-68` claims the old binary and localhost listener as expected pre-state, but `OllamaBackend.check_pre()` at `core.py:166-170` checks only hostname, two binary hashes, drop-in absence, and `systemctl is-active`. It does not verify the active unit's current `ExecStart`, unit/drop-in bytes, environment/model-store, process executable, version, PID, or listening addresses. A drifted or malicious pre-existing unit passes; rollback then removes the new drop-in and restarts that unsealed unit. `rollback()`'s `restore_executable`/`restore_sha256` fields are descriptive only and are never enforced.

Required change: seal and verify the complete effective pre-state before consume/mutation, including root-owned unit/drop-ins and hashes, effective ExecStart/environment, process executable/version, model store, and exclusive localhost listener. Bind a byte-exact backup/rollback plan and verify restored post-state before recording success.

### F-003 — success health gate does not prove localhost-only exposure or CUDA (HIGH)

`core.py:177-184` proves only that loopback HTTP answers with version `0.32.14` and one model exceeds 100 tok/s. It never detects an additional `0.0.0.0`, `[::]`, non-loopback listener, duplicate daemon, or whether the installed backend is CUDA. Thus a public/duplicate listener can coexist with a passing result, and the claimed CUDA runtime switch is not verified.

Required change: after restart, inspect service PID/process executable and all TCP listeners for port 11434; require exactly the intended daemon and loopback-only IPv4/IPv6 policy. Verify CUDA backend evidence and fail/rollback on ambiguity. Add adversarial public-listener and duplicate-daemon tests.

### F-004 — bootstrap copies mutable user-owned source as root without a sealed manifest (HIGH)

`install.sh:5-13` is intended to be launched with sudo from a UID-1000-owned working tree. It copies `core.py`, `broker.py`, and sudoers by relative path with no pre-opened descriptors, ownership/mode checks, immutable manifest, or expected hashes. Source can change between human review and root copy (including path replacement), so the one-shot ceremony does not install the reviewed bytes. It also installs sudoers before proving the complete installed tree matches a sealed manifest and leaves partial state on failure.

Required change: bootstrap from a root-opened, non-symlink, root-owned staging package or verify a Captain-confirmed manifest of every source byte before and after atomic installation. Reject writable parents/symlinks, validate installed hashes/owners/modes, validate policy before atomic placement, and cleanly rollback partial installation. Add adversarial source-swap/symlink and partial-install tests.

### F-005 — append-only ledger integrity is not authenticated (MEDIUM)

Approval records are HMAC-authenticated, but consume/result ledger records at `core.py:148-160` are not MACed or hash-chained. Root ownership protects the intended installation, but malformed/truncated content blocks all future execution and there is no cryptographic binding between consume and result. This falls short of the requested append-only receipts with hashes and weakens crash-window diagnosis.

Required change: MAC or hash-chain every consume/result record, bind operation ID/task/run/nonce hash and previous record hash, validate the full chain, and distinguish durable consumed-with-unknown-outcome from rollback/result states.

## Positive controls observed

- Exact schema rejects caller-supplied command, args, environment, service, host, action, paths, model, threshold, and rollback changes.
- Sudoers parses and grants only literal `... broker execute`; approval is not NOPASSWD.
- Approval receipt binds canonical packet hash and HMAC; duplicate valid approvals are ambiguous and rejected.
- Task and run must both be running; terminal parent request cannot execute.
- Authorization consumption is fsynced before backend calls; replay is rejected under `flock`.
- No network listener or sudo-password storage exists in the broker.
- The fixed drop-in text binds `OLLAMA_HOST=127.0.0.1:11434`, but runtime listener verification is still required.

## Executed verification

- `python -m pytest -q` → 48 passed.
- `python -m unittest discover -v` → 41 passed.
- Added five independent probes in `privileged_broker/test_adversarial_review.py`: duplicate approval ambiguity, expiry mutation, task/run substitution, rollback exception recording, malformed-ledger rejection.
- `python -m py_compile privileged_broker/*.py` → pass.
- `sh -n privileged_broker/install.sh privileged_broker/uninstall.sh` → pass.
- `visudo -cf privileged_broker/hermes-privileged-broker.sudoers` → parsed OK.
- `git diff --check` → pass.
- Read-only listener inspection showed `127.0.0.1:11434`; this is ambient evidence only, not broker certification.

## SHA-256 manifest

- `core.py` `6808c285408ceffd6d0e596c6eea09d7e4350761616807db19b7800325222b79`
- `broker.py` `b6023a14f177c0f3ebfa74220f315da434de146f27f7f6711bb89c5d8f697067`
- `install.sh` `34c078b8c1d07a847dacbbc9673994523955ca8a09000c3b8924ec79b3c9c2c6`
- `uninstall.sh` `60c87fbc1a9448b5036ce0d354e545f2f15d9339261cbf8a3bb3f1a11f0d371e`
- `hermes-privileged-broker.sudoers` `259551c7e8874ce402e7408ef5b31820a1d940e7916b683d4d695a87a1211f5f`
- expired request file bytes `776f77d541868c28c4c091df8b52227f22da313837bcef37a1e12c90dd90c1ee`
- adversarial tests `77bb976619a6ee79f8aee3c73ea74bee9df41f2b295a94bbaef7986677534610`

The parent comment's `7daea...` is the broker's canonical JSON semantic digest; the file-byte SHA above includes its trailing newline. These are distinct hash domains and must not be conflated.
