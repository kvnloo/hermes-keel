# LF-006 gateway restart persistence probe

Verdict: PASS (mechanical evidence; no acceptance claim)

- Canonical authority: task `t_235ade89`; Captain-authorized gateway restart only.
- Supervisor request/result: 2026-08-16 16:01:35–16:01:37 CDT; exit 0; `restart-complete`.
- Gateway: active/running; main PID changed `1452955` → `3696175`; `NRestarts=0`; one gateway main process.
- Telegram: adapter reconnect attempt logged and the new gateway PID owned two established TLS connections to Telegram address `2001:67c:4e8:f004::9`.
- Default Telegram router: 15 resolved tools; prohibited terminal/shell, file/project RW, execution, browser/computer, MCP, delegation, Git/deploy, and subprocess/background classes absent. Kanban routing remained available.
- Config: gateway config, environment file, and user unit hashes/mtimes unchanged. No configuration mutation was performed.
- Logs: pre-existing global MCP parking warnings were observed, but no MCP tool entered the default Telegram router. No duplicate gateway main process or message replay was observed.
- Scope: LF-006 only. LF-007 remains skipped. Level 1 was not advanced.

The immutable supervisor receipt is copied as `restart-result.json`; `probe.json` binds the post-restart observations. This packet has `acceptance_claim: false`.
