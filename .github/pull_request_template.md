## Summary

Describe the user-visible or operator-visible outcome.

## Scope and compatibility

- [ ] The change is modular and does not add unrelated code to a large file.
- [ ] Public API, stored-data and configuration changes are documented.
- [ ] The change contains no credentials, private deployment data or proprietary source.
- [ ] New source and assets may be contributed under the terms in LICENSE.

## Verification

List the exact checks run and their results.

## Deployment impact

Describe required migration, rebuild, restart or rollback steps. Write “None” if
there is no deployment impact.

## IaC change log (required when `docker-compose*.yml`, `deploy/**`, `infra/**` or `.github/workflows/**` change)

Infrastructure-as-code gate (024 T028 / FR-006, QF-822/QF-823): this section is
checked by the `iac-gate` workflow. Keep the plan-output / actual-change table
accurate; the gate rejects PRs that touch IaC without declaring it.

| Planned output | Actual change | Reason for deviation |
| --- | --- | --- |
| e.g. add `read_only: true` to mongo | as planned | — |
| e.g. pin redis image digest | did not change | out of scope, follows-up as #123 |

- [ ] I ran the IaC checks locally and attach their output below (`./mogo config --env all`, `./mogo drift --service <name>`, `docker compose config --quiet`).
