# Keel v2 Captain ceremony request template — NOT A LIVE REQUEST

Status: template only. `acceptanceClaim: false`. No nonce, expiry, task/run authority, request hash, approval command, approval receipt, or mutation authority exists in this file.

```text
🔐 ROOT ACTION — APPROVE / DENY
Operator: Kevin (Captain), authenticated locally as exact configured UID
Host: groot (exact descriptor from sealed install identity)
Action: ollama-system-runtime-switch-v2
Old runtime: /usr/bin/ollama @ ab27361e1e4c70a5aed215cce0cf6033bbf61650a0eb7e4b63cf01c76a06353a
New runtime: /usr/local/lib/hermes-privileged-broker/runtimes/sha256-d0758d38ac5882a2c68fd930d0c1220af1952469fa9f30c268746d4021709bf4/ollama
New runtime hash: d0758d38ac5882a2c68fd930d0c1220af1952469fa9f30c268746d4021709bf4
Package MANIFEST: <FULL INDEPENDENTLY REVIEWED ROOT-SEALED HASH>
Board descriptor: <PATH + UID/GID + MODE + DEVICE + INODE + SHA256>
Task/run: <EXACT ACTIVE TASK>/<EXACT ACTIVE RUN>
Expires: <SHORT UTC EXPIRY>
Request: <FULL SHA-256>
Risk: brief loopback Ollama outage; fixed CUDA/model health gates; automatic bounded rollback on failure.
Rollback: remove only fixed Hermes drop-in; daemon-reload; restart and verify exact old runtime, unit/drop-ins, listener and model store.
One local action only: <GENERATED pkexec APPROVE COMMAND FOR EXACT SEALED REQUEST>
Type the FULL request hash only after matching every field. Otherwise deny/do nothing.
```

A future independently reviewed successor may generate the exact request and command. Free-form approval, this template, v1 packets, historical packets, mutable checkout/package paths, and ambient identity are invalid.
