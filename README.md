# Hermes Keel

**A self-evolving, performance-based execution kernel for Hermes Agent.**

Hermes Keel makes orchestration claims mechanically testable. It governs capability boundaries and evidence requirements around Hermes Agent's existing conversation runtime and Kanban execution kernel; it does not replace either.

## North star

Maximize verified useful progress per unit of time, compute, Captain attention, and risk—within hard authority and evidence constraints.

## Boundaries

- **Hermes Agent owns:** messaging, profiles, tools, sessions, Kanban tasks/runs, and worker processes.
- **Keel owns:** role capabilities, execution invariants, evidence chains, adversarial probes, performance policy, governed evolution, and rollback.
- **Firstmate owns:** optional subordinate supervision, Second Mates, Crewmates, worktrees, validation, and PR lifecycle for an authorized Hermes task.
- **PM owns:** product, portfolio, and project intent, prioritization, acceptance criteria, and company-level semantics.
- **Paperclip, PMFE, zerOS, dashboards, and tmux are projections:** they never define execution truth.

## Constitutional rule

Keel may be self-modifiable, but never self-authorizing. A running kernel cannot approve weakened authority boundaries or evidence requirements. Changes require an isolated experiment, frozen evaluator, adversarial evidence, explicit promotion authority, and a rollbackable version.

## Levels

Exactly one invariant is introduced and proven at a time. Advancement requires runtime evidence and explicit Captain approval.

| Level | Invariant |
|---:|---|
| 0 | The Telegram-facing router cannot execute project work directly. |
| 1 | Every execution is a canonical Hermes Kanban task. |
| 2 | Every task has a distinct durable run. |
| 3 | Every successful run has durable evidence. |
| 4 | Every completion durably wakes its owner. |
| 5 | Worker crashes are detected and recoverable. |
| 6 | Review is a separate durable run. |
| 7 | Product-specific persistent profiles may be introduced. |
| 8 | Portfolio replenishment may be introduced. |
| 9 | Firstmate may become an optional subordinate execution backend. |
| 10 | External systems may become projections of execution truth. |

## Current scope

Only **Level 0** is authorized:

1. Provision exactly one disposable `canary-worker` profile without messaging ingress.
2. Remove all project-implementation capabilities from Telegram-facing `default`.
3. Prove the router cannot execute directly.
4. Stop.

A Kanban tracer and product work are not authorized until Level 1.
