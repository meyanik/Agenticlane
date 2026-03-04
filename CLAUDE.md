# AgenticLane Project Instructions

## On Session Start
1. Read `tracking/PROGRESS.md` -- understand current phase, sub-task, and status
2. Read the relevant section of `docs/planning/master_plan.md` for implementation details
3. Read the relevant section of `tracking/TESTING.md` for the test plan
4. Check `tracking/WORKLOG.md` for recent session context

## On Session End
1. Update `tracking/PROGRESS.md`: check off completed items, update "Current State" and "Next Up"
2. Append a new entry to `tracking/WORKLOG.md` with: date, what was done, files changed, decisions, issues
3. If tests were written/modified, update test status markers in `tracking/PROGRESS.md`

## Reference Documents
- `docs/spec/AgenticLane_Build_Spec_v0.6_FINAL.md` -- Source of truth for all behavior
- `docs/planning/master_plan.md` -- Build phases, sub-tasks, code examples, dependency graph
- `docs/architecture/ARCHITECTURE.md` -- Three-plane architecture, data flow, component relationships
- `docs/integration/LIBRELANE_INTEGRATION.md` -- LibreLane Python API, step mapping, config format, hooks
- `docs/architecture/SPEC_GAPS.md` -- Known spec gaps with resolutions
- `docs/architecture/TECH_DECISIONS.md` -- Technical decisions (async, LLM stack, testing, etc.)
- `tracking/TESTING.md` -- Per-feature test strategies and test case lists

## Development Rules
- Phase-by-phase: complete current phase (all tests green) before starting next
- Test-first: write/review test plan from tracking/TESTING.md before implementing each sub-task
- Every sub-task must have passing tests before marking complete in tracking/PROGRESS.md
- Use MockExecutionAdapter and MockLLMProvider for all testing (no real EDA tools needed)
- Python 3.10+, Pydantic v2, async from start, Typer CLI
- Run `ruff check`, `mypy`, `pytest` before marking any sub-task done
- Never skip updating tracking files at end of session
