#!/usr/bin/env python3
import json
import os
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from privileged_broker.core import OllamaBackend, canonical, digest, make_request, sealed_package

out = Path("/workspace/zer0/oss/hermes-keel/privileged_broker/requests/t_a9f17226-run181-ollama-v2.json")
if out.exists() or out.is_symlink():
    raise SystemExit("request output already exists")
out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
os.chmod(out.parent, 0o700)
pre_state = OllamaBackend().capture_pre_state(
    Path("/home/kvn/.hermes/kanban/boards/zer0-company/kanban.db"), (1000,)
)
request = make_request(
    "t_a9f17226",
    181,
    secrets.token_urlsafe(32),
    int(time.time()),
    ttl=1800,
    pre_state=pre_state,
    package=sealed_package(
        "/root/hermes-keel-staging/t_a9f17226-r181/package",
        "ed9304a597b8f2dcec127b30b9c1cd2b76d5fa2e7b3ff2038a424e212aa93e6e",
    ),
)
fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o400)
try:
    os.write(fd, canonical(request) + b"\n")
    os.fsync(fd)
finally:
    os.close(fd)
dfd = os.open(out.parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(dfd)
finally:
    os.close(dfd)
print(json.dumps({
    "request": str(out),
    "sha256": digest(request),
    "created_at": request["created_at"],
    "expires_at": request["expires_at"],
    "pre_state": pre_state,
}, sort_keys=True))
