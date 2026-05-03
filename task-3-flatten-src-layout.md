# Task 3: Flatten Package — Move `src/must_gather_downloader/` to `src/`

## Goal

Currently the package lives at `src/must_gather_downloader/*.py`. Move all the Python modules up one level so they live directly under `src/` (i.e. `src/server.py`, `src/cache.py`, etc.) and remove the `must_gather_downloader` subdirectory.

## Current Structure

```
src/
  must_gather_downloader/
    __init__.py
    server.py
    config.py
    cache.py
    download.py
    navigate.py
    pod_logs.py
    search.py
    text.py
    resources.py
    resource_maps.py
    noobaa.py
    noobaa_resource_maps.py
    reportportal.py
```

## Target Structure

```
src/
  __init__.py
  server.py
  config.py
  cache.py
  download.py
  navigate.py
  pod_logs.py
  search.py
  text.py
  resources.py
  resource_maps.py
  noobaa.py
  noobaa_resource_maps.py
  reportportal.py
```

## Requirements

### 1. Move Files

Move all `.py` files from `src/must_gather_downloader/` to `src/`. Remove the now-empty `must_gather_downloader/` directory.

### 2. Fix All Imports

All intra-package imports currently use relative imports like `from .navigate import ...`. After flattening, these still work since the files remain siblings — but verify every import in every file. The package root is now `src/` itself.

### 3. Update `pyproject.toml`

The current config:

```toml
[project.scripts]
must-gather-downloader = "must_gather_downloader.server:main"

[tool.setuptools.packages.find]
where = ["src"]
```

After flattening, the package is no longer `must_gather_downloader` — it's just the modules in `src/`. You need to update:

- The `[project.scripts]` entry point. Since there's no longer a `must_gather_downloader` package, you'll need an alternative approach. One option is to make `src` itself a package (it already will have `__init__.py`), but that's unusual. A better approach: keep a top-level package name by renaming the directory. **Actually, reconsider**: the user said "move content of `src/must_gather_downloader` to just be under `src`" — this likely means they want `src/` to directly contain the modules without a package subdirectory. The cleanest way:
  - Use `[tool.setuptools] py-modules = [...]` or `packages = [""]` with `package-dir = {"": "src"}` — but this gets tricky.
  - **Recommended**: Instead of a flat collection of modules, make `src` itself the implicit package root by keeping `__init__.py` there and using `package-dir = {"must_gather_downloader" = "src"}` so setuptools treats `src/` as the `must_gather_downloader` package. This way the entry point `must_gather_downloader.server:main` still works, and `pip install -e .` still works.

Update `pyproject.toml` accordingly. The key constraint: `pip install -e .` and `must-gather-downloader` CLI entry point must still work after the change.

### 4. Update `CLAUDE.md`

Update the Architecture section to reflect the new layout (modules directly in `src/`, no `must_gather_downloader` subdirectory).

### 5. Run Tests

Run `.venv/bin/pytest tests/ -v` and confirm everything passes. Tests import from `must_gather_downloader.*` — make sure those imports still resolve correctly with the new layout. You may need to reinstall with `pip install -e .` first.

## Files You'll Touch

- `src/must_gather_downloader/*.py` — move to `src/`
- `src/must_gather_downloader/` — delete directory
- `pyproject.toml` — update package discovery and entry point
- `CLAUDE.md` — update architecture docs
- Possibly `tests/*.py` — if import paths change

## Commit

Create a single commit with a descriptive message.
