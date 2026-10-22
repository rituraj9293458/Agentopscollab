# Repository Guidance

- Preserve the boundary: models propose; deterministic PostgreSQL execution and approved invariants decide.
- Never report reproduction without a failed executable invariant from real PostgreSQL.
- Never report a verified candidate unless every named gate passed.
- Keep `src/raceproof/sample/inventory.py` as the only model-editable path unless a reviewed contract change expands it.
- Do not let generated patches alter tests, fixtures, scheduler, invariant, configuration, or Git metadata.
- Every repair attempt starts from the unchanged baseline. Instrument only a disposable run copy.
- When transaction structure changes, relocate by semantic SQL role or return `UNVERIFIABLE_SCHEDULE`; missing checkpoints are not success.
- Cap repair attempts and return exact failed evidence with `UNRESOLVED`.
- Use separate SQLAlchemy sessions for concurrent actors.
- Run unit tests, PostgreSQL integration tests, and the frontend build before claiming completion.
- Avoid em dashes in documentation and user-facing copy.

