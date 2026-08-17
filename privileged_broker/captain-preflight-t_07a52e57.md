# Keel Captain ceremony preflight — t_07a52e57 / run 149

Observed: 2026-08-17T17:08:15-05:00 on `groot` as UID/GID 1000 (`kvn`).

## Verdict

**FAIL CLOSED — no approvable request or command issued.** No sudo, pkexec, install, approval, service mutation, Ollama mutation, LF-007, or Level 1 was performed.

The reviewed source hashes and tests are unchanged, but the requested ceremony cannot be prepared safely from this source/state:

1. Task requires only `ollama-system-runtime-switch-v1`; reviewed code fixes `ACTION` to `ollama-system-runtime-switch-v2`. Issuing a v2 request would exceed authority; changing it would drift the independently reviewed source.
2. Target CUDA runtime and binary are UID 1000-owned/mutable (`0755`), not sealed root-owned identities. F-002/K-002 are therefore not closed.
3. Canonical board DB is UID 1000 mode `0644`; current request schema does not seal its descriptor/owner/mode/inode. K-002/K-008 remain open.
4. Installer still ingests package members by pathname and has no unprivileged kill-at-every-publication rehearsal. F-004 remains open.
5. Sustained live CUDA evidence for 3B/7B/27B and a complete secret-canary matrix were not present and may not be created by mutating/running Ollama in this prohibited preflight. F-003/K-005 remain open.
6. Privileged install/uninstall/restoration rehearsal is prohibited here. K-007 remains open. K-006/K-008 cannot be claimed closed without installed root identity/key/checkpoint/policy evidence.

## Reviewed source and verification

- `core.py`: `d8d7ddb7e18e31145f78fa2dfd23458a154609bc9b7717ecbeb5c9d6f5da9b8c`
- third-review probes: `06947443fe0583f35503bd6f767b5f932100c94b4d9ab52596f2fffd8301da84`
- fourth-repair matrix: `70b759d6ab3c0ccb7d11945c7ff29900701c0ad848d361bd4a2962c5cd1b686e`
- `install.sh`: `31921ed195cc4e622c991dc0622379ce343ef6e9bcec474a498943e6e19924c7`
- `uninstall.sh`: `34246e6dc551522860898832225e279c34c996a97fa0118472d8a3f6d0e77a74`
- `build-package.sh`: `e443bfe798eb6af99faceb5ce4a160ccbb6ed1e372b8da0816dbea0fd11ff5b4`
- `broker.py`: `e544ce5ea328487f1623dca016cd6c5c6ba4a71eff5cfa0f35bd0b3a41b447fc`
- `python -m pytest -q`: 68 passed
- `python -m unittest discover -s privileged_broker -p 'test*.py' -q`: 36 passed
- py_compile, shell syntax, and `git diff --check`: pass

## Live pre-state / rollback target

- Unit: active/running, main PID 3806, only daemon process `/usr/bin/ollama serve`
- Fragment: `/usr/lib/systemd/system/ollama.service`, root:root 0644, sha256 `24871ffd940212e04e9bd3c334cfd4e3c4e845b374c5d0ed369fd32496b05fdb`
- Drop-in: `/etc/systemd/system/ollama.service.d/model-store.conf`, root:root 0644, sha256 `5c3b784aa084a65783eab41f5cfb1fd50f0fdc5ba020d1675fab465024faf805`
- Effective ExecStart: `/usr/bin/ollama serve`; effective user/group: `ollama:ollama`
- Effective model store: `/mnt/zer0models/zer0-models/ollama`; size at observation: 6,613,002,108 bytes
- Listener: loopback IPv4 `127.0.0.1:11434`; API version `0.16.1`
- Rollback binary: `/usr/bin/ollama`, root:root 0755, sha256 `ab27361e1e4c70a5aed215cce0cf6033bbf61650a0eb7e4b63cf01c76a06353a`, version 0.16.1
- Proposed CUDA binary bytes match reviewed hash `d0758d38ac5882a2c68fd930d0c1220af1952469fa9f30c268746d4021709bf4`, but file and ancestors are UID 1000-owned; identity is not ceremony-safe.
- Broker install destinations/state were absent.
- Canonical DB: `/home/kvn/.hermes/kanban/boards/zer0-company/kanban.db`, uid/gid 1000, mode 0644, inode 413083864, dev 66307, point-in-time sha256 `be07de694c4358ec6df48b8346983bb8709788b39c222e20a55fc4b6b7ddd92c`.

## Unprivileged package

Built once at `/var/tmp/hermes-broker-package-t_07a52e57-run149-1787004500`.

- MANIFEST sha256: `04dd0fdc2c3d0416114fb907d0ca56361d9f19e61bfc273d1a64c1dd7d3d370f`
- All manifest members verified.
- Current package owner is UID 1000 and therefore it is **not approved or root-sealed**.
- No ownership transfer or installer execution occurred.

## Required next decision

Do not approve or run any command from this preflight. A new reviewed repair must first reconcile v1 versus v2 authority and close the listed live gates. Only after that repair is independently reviewed should a successor run generate a fresh short-lived canonical request and one interactive local approval command.

## Rollback plan for a future authorized ceremony

If a future exact request mutates and health fails: verify the sealed fragment, unrelated drop-in, model-store manifest, and original binary; remove only `/etc/systemd/system/ollama.service.d/10-hermes-cuda-runtime.conf`; fsync its parent; daemon-reload; restart `ollama.service`; verify exact old executable/hash/version/effective environment, unique loopback listener, and unchanged store. Any mismatch is `recovery_required`, never retry authority.
