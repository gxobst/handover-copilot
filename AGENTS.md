Commands

- `uv sync` - install dependencies
- `uv run pytest` - the whole backend test suite
- `uv run pytest backend/tests/unit` - unit tests only
- `make test` - run all unit, integration, and frontend tests
- `make run` - run local environment via docker compose

Rules

- Dependencies are added in `pyproject.toml` or `frontend/package.json`. Do not add one without asking.
- Use existing libraries/packages if possible instead of coding from scratch. Use the latest stable version.
- Never write code before the task has been groomed and acceptance criteria are understood.

Documents

- `_docs/plan.md` - canonical specification and delivery plan
- `_docs/process.md` - how agent team work is organized
- `_docs/testing-guidelines.md` - testing tiers, mock conventions, and commands
- `_docs/design-system.md` - UI components, styling, tokens, and UX rules
