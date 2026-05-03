# Task 1: Add Ruff Style Enforcement

## Goal

Set up **ruff** as the linter/formatter for this project, with pre-commit git hooks for local enforcement and a GitHub Actions workflow so incoming PRs are checked.

## Current State

- No linter or formatter is configured (CLAUDE.md explicitly says "No linter is configured").
- No `.github/` directory exists — no CI workflows yet.
- Project uses `pyproject.toml` for all config (build system, pytest, etc.).
- Python source lives in `src/must_gather_downloader/` with tests in `tests/`.
- `pyproject.toml` specifies `requires-python = ">=3.12"`.

## Requirements

### 1. Ruff Configuration in `pyproject.toml`

Add `[tool.ruff]` sections to `pyproject.toml`:

- Target Python 3.12.
- Enable at minimum these rule sets: `E` (pycodestyle errors), `F` (pyflakes), `I` (isort), `D` (pydocstyle — for docstring enforcement).
- For the `D` rules, use the **google** convention (`[tool.ruff.lint.pydocstyle] convention = "google"`).
- Require docstrings on all public functions/methods/classes. This is a key requirement — the user specifically wants docstring enforcement.
- Line length: 120 (the existing code uses lines up to ~115 chars).
- Ignore rules that conflict with the existing code style if needed (e.g. `D100` for module-level docstrings may be too noisy — use judgment).

### 2. Pre-commit Hook

- Add a `.pre-commit-config.yaml` using the [pre-commit](https://pre-commit.com/) framework.
- Include a ruff hook for both linting and formatting.
- Add `pre-commit` to the project's dev/test dependencies in `pyproject.toml`.
- Document how to install hooks: `pre-commit install`.

### 3. GitHub Actions CI Workflow

- Create `.github/workflows/lint.yml` (or similar name).
- Trigger on pull requests to `master` and on pushes to `master`.
- Steps: checkout, set up Python 3.12, install ruff (via pip), run `ruff check .` and `ruff format --check .`.
- Keep it simple — a single job is fine.

### 4. Fix Existing Code

- Run `ruff check --fix .` and `ruff format .` on the existing codebase so it passes.
- **Every function and method must have a docstring.** The existing code already has docstrings on most functions (they were recently added), but verify completeness and add any that are missing.
- Do NOT change logic or behavior — only style/formatting fixes.

### 5. Update CLAUDE.md

- Replace the "No linter is configured" line with brief instructions on ruff usage.
- Mention that `pre-commit install` should be run after cloning.

### 6. Run Tests

After all changes, run `.venv/bin/pytest tests/ -v` and confirm everything still passes.

## Files You'll Touch

- `pyproject.toml` — ruff config + pre-commit dependency
- `.pre-commit-config.yaml` — new file
- `.github/workflows/lint.yml` — new file
- `src/must_gather_downloader/*.py` — formatting fixes, missing docstrings
- `tests/*.py` — formatting fixes, missing docstrings
- `CLAUDE.md` — update linter docs

## Commit

Create a single commit with a descriptive message covering all the above.
