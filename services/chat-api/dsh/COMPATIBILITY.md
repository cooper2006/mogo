# DSH compatibility policy

MOVO consumes agent runtimes through the versioned `AgentKernelContract`. DSH is
one runtime provider behind that contract; product services and the frontend do
not consume DSH APIs directly. DSH-specific compatibility code belongs in
`dsh/runtime-host/`, in small adapters grouped by upstream subsystem.

| Item | Active baseline | Status | Upgrade rule |
|---|---|---|---|
| Reviewed upstream source | `0a15e36e7f82b6ed45af6fa9759f29b40dcd965d` (`dsh-v0.1.6-alpha.1`) | reviewed | review the upstream diff again |
| Deployable npm train | `@deepseek-ai/dsh@0.1.6-alpha.1` | admitted, integrity pinned | pin every DSH package to one exact train |
| Source/package mapping | unavailable upstream | unverified | do not claim cryptographic correspondence |
| Node platform | `^22.19.0 || >=24.0.0` | required | test every supported deployment image |
| Host protocol | `askai.dsh-host.v1` | frozen | adapt DSH changes inside Runtime Host |
| Execution projection | `askai.execution-v3` | frozen | version the MOVO contract before changing it |
| Session persistence | upstream JSONL, opaque | V2-to-V3 migration verified | test both readability and semantic continuity |
| DSH Core fork | none | prohibited | never patch vendored or installed DSH source |

## Admitted compatibility behavior

DSH `0.1.6-alpha.1` replaces older Code runtime composition with its PTC
runtime and migrates persisted Code sessions to the native `ptc` preset. The
bridge keeps MOVO's public preset id as `code`; this preserves the existing
product contract and remounts the expected file, shell, Skill and subagent tool
surface after resume. MOVO does not expose the native preset rename.

The Session bridge also owns the upstream V3 API differences: persisted reads,
in-memory event snapshots and seeded-session lineage. Cancellation waits for the
official DSH turn and all owned background jobs to settle before it reports a
successful stop. An immediate next turn is therefore part of the admission
contract, not a UI-only check.

V3 also compacts streamed model chunks into the final assistant event and may
carry the effective system prompt as an in-history system message. Dedicated
event and model-request adapters expand those forms back into MOVO's stable
delta/error events and Model Gateway envelope. These translations stay out of
the product service and can be replaced with the DSH provider itself.

## Required automated admission

Every runtime upgrade must prove all of the following against real Host
composition, not mocks alone:

- create, execute, cancel, immediately execute again, dispose, resume and
  execute again;
- resume a session written by the previous release while preserving public
  preset, permission preset and required Code tools;
- fork a completed conversation using the stable MOVO lineage contract;
- expose every governed MOVO tool to both the model and capability inventory;
- discover and load an installed Skill package;
- delegate to a foreground subagent and return its result to the parent;
- pass Host contract, supply-chain, exact-release-train, SBOM and packaged
  smoke gates.

The isolated evaluator in `scripts/evaluate_dsh_candidate.py` installs a
candidate into a temporary workspace. It must never mutate the active runtime
in place. A candidate report can establish contract compatibility; application
regression, packaged smoke and release rollback checks remain release gates.

`0.1.2-alpha.2` remains the immediate rollback train. Roll back the complete
versioned release rather than mixing DSH package versions inside one dependency
graph. Because upstream Session migration can be one-way, preserve runtime data
and rehearse rollback against a copy before production release.
