# Narrow LF-006 external supervisor

This user service exists only to bridge an already-authorized active Kanban task to the fixed operation `systemctl --user restart hermes-gateway.service`. It is not a generic service manager.

The installed unit name is intentionally neutral (`hermes-keel-lf006-supervisor.service`) so gateway-scoped workers can manage the supervisor without tripping the gateway process's own restart-safety hook.

## Security contract

- one AF_UNIX socket, mode 0600, under `%t/hermes-keel/lf006.sock`
- peer UID/PID comes from `SO_PEERCRED`, never request data
- exact JSON fields, canonical `t_########`, 32-128 character nonce, board slug, 120-second age, and fixed service
- pinned Kanban SQLite database; the unique task must be `running`, incomplete, and explicitly authorize a Hermes/Telegram gateway restart
- dry-run is allowed for authorized restart-related tasks, including the supervisor-build task
- execute (`dry_run=false`) additionally requires an explicit live-restart authorization marker and rejects supervisor-only / "do not perform the actual gateway restart" wording
- append-only mode-0600 receipts contain only nonce SHA-256, task/caller identity, fixed service, timestamps, pre/post systemd state, and status
- a malformed receipt log fails closed; nonce replay fails; requests serialize in one process
- the only mutation subprocess has the literal argv `systemctl --user restart hermes-gateway.service`, with a 45-second timeout
- no root, sudo, Docker socket, arbitrary DB writes, or generic systemctl passthrough

## Install

Substitute the `@...@` values in `hermes-keel-lf006-supervisor.service.in` with absolute Python/source/database paths, the board directory for SQLite WAL coordination, and the exact board slug. Write the rendered unit to:

`~/.config/systemd/user/hermes-keel-lf006-supervisor.service`

Then:

```sh
install -d -m 700 "$XDG_RUNTIME_DIR/hermes-keel" "$HOME/.local/state/hermes-keel"
systemctl --user daemon-reload
systemctl --user enable --now hermes-keel-lf006-supervisor.service
```

## Invocation contract for t_235ade89

Dry-run (default):

```sh
python supervisor/gateway_restart_client.py t_235ade89 \
  --board zer0-company \
  --socket "$XDG_RUNTIME_DIR/hermes-keel/lf006.sock"
```

Execute (only when the task is `running` and its body contains an explicit Captain live-restart authorization):

```sh
python supervisor/gateway_restart_client.py t_235ade89 \
  --board zer0-company \
  --socket "$XDG_RUNTIME_DIR/hermes-keel/lf006.sock" \
  --execute
```

No caller may select a service or command. The request body is fixed-shape JSON:

```json
{
  "version": 1,
  "task_id": "t_235ade89",
  "nonce": "<32-128 url-safe chars>",
  "service": "hermes-gateway.service",
  "board": "zer0-company",
  "created_at": 0,
  "dry_run": false
}
```

## Rollback / uninstall

Rollback test without affecting the live gateway:

```sh
GW_PID=$(systemctl --user show -p MainPID --value hermes-gateway.service)
GW_N=$(systemctl --user show -p NRestarts --value hermes-gateway.service)
systemctl --user stop hermes-keel-lf006-supervisor.service
test ! -e "$XDG_RUNTIME_DIR/hermes-keel/lf006.sock"
test "$(systemctl --user show -p MainPID --value hermes-gateway.service)" = "$GW_PID"
test "$(systemctl --user show -p NRestarts --value hermes-gateway.service)" = "$GW_N"
systemctl --user start hermes-keel-lf006-supervisor.service
```

Uninstall:

```sh
systemctl --user disable --now hermes-keel-lf006-supervisor.service
rm -f ~/.config/systemd/user/hermes-keel-lf006-supervisor.service
systemctl --user daemon-reload
# optionally archive, never delete to permit replay:
# ~/.local/state/hermes-keel/lf006-receipts.jsonl
```

## Outside-workspace paths

- installed unit: `~/.config/systemd/user/hermes-keel-lf006-supervisor.service`
- socket: `%t/hermes-keel/lf006.sock`
- receipts: `~/.local/state/hermes-keel/lf006-receipts.jsonl`
- board DB path is host-local and must be substituted at install time

## Tests

```sh
python -m unittest discover -s supervisor -v
```
