# Architecture

Keel adds governance around Hermes Agent. It does not create a second execution kernel.

## Canonical execution spine

```text
Product and portfolio intent (optional PM)
                    |
                    v
Hermes Agent -> canonical Kanban task -> durable run -> evidence -> owner wake-up
                    |
                    v
        optional subordinate executor (Firstmate)
```

The Hermes task and run remain the authoritative execution record. Optional systems may supply intent, execute authorized subordinate work, or project state, but they do not become parallel sources of execution truth.

## Boundaries

### Hermes Agent

Hermes owns messaging, profiles, tools, sessions, Kanban tasks and runs, worker dispatch, and worker processes. Its Kanban lifecycle is the canonical execution spine.

### Hermes Keel

Keel defines role capabilities, execution invariants, evidence chains, adversarial probes, performance policy, governed evolution, and rollback. Keel may constrain or evaluate execution, but it does not replace Hermes runtime ownership.

### Firstmate (optional)

[Firstmate](https://github.com/kunchenguid/firstmate) may supervise subordinate workers, worktrees, validation, and pull-request lifecycle for work already authorized by a Hermes task. It is not required at Level 0 and is not a co-equal source of truth.

### PM (optional)

[PM](https://github.com/kvnloo/_pm) may describe product, portfolio, and project intent, priorities, acceptance criteria, and company-level semantics. It does not own execution truth.

## Authority boundary

External dashboards may display or summarize canonical state. Their projections never define it. Keel may be self-modifiable, but it is never self-authorizing: weakened authority or evidence boundaries require an isolated experiment, frozen evaluator, adversarial evidence, explicit promotion authority, and a rollbackable version.
