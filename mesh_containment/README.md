# Disposable Mesh :8787 containment fixture

This package is a local, reversible authority-boundary fixture. It models the
Linux and mbp Mesh peers as two synthetic owners competing for the :8787 owner
lease, but deliberately opens no TCP/UDP/Unix listener and performs no service,
plugin, route, credential, or remote-machine mutation.

Mesh accepts HMAC-signed task/run/event transport envelopes only after a
read-only lookup of the exact canonical task/run. It can persist transport
receipts beneath the disposable fixture root. It cannot create, claim, or
complete Kanban tasks, and cannot append Keel acceptance. A
`completion-requested` event returns a handoff naming canonical Kanban as the
only completion authority.

The tests cover:

- exact signed-envelope and canonical board/run binding;
- flock-serialized receipts, replay idempotency, content conflicts, restart,
  and concurrent delivery;
- synthetic Linux/mbp :8787 owner exclusion and reversible handover;
- RED mutations for create/claim/direct completion, acceptance, forged board
  copy/symlink, replay conflict, stale envelope/run, bad signature, and a second
  listener;
- byte hash and SQLite logical identity of the canonical sentinel before and
  after every test.

Run only this disposable fixture:

```sh
python -m unittest -v mesh_containment.test_fixture
```
