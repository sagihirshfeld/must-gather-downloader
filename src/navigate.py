import tarfile
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=32)
def _find_must_gather_root(must_gather_path: str) -> Path:
    """Locate the root directory of a must-gather extraction.

    Searches for the ``namespaces/`` directory at increasing depth,
    handling various nesting levels from different extraction tools.
    Results are cached with ``lru_cache``.

    Args:
        must_gather_path: Path to the top-level extraction directory.

    Returns:
        Path to the directory that directly contains ``namespaces/``.

    Raises:
        ValueError: If the path doesn't exist, isn't a directory, or
            contains no recognisable must-gather structure.
    """
    path = Path(must_gather_path)
    if not path.exists():
        raise ValueError(f"Path does not exist: {must_gather_path}")
    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {must_gather_path}")

    if (path / "namespaces").is_dir():
        return path

    for child in sorted(path.iterdir()):
        if child.is_dir() and (child / "namespaces").is_dir():
            return child

    for candidate in sorted(path.rglob("namespaces"), key=lambda p: len(p.parts)):
        if candidate.is_dir():
            return candidate.parent

    subdirs = sorted(d for d in path.iterdir() if d.is_dir())
    if not subdirs:
        raise ValueError(f"No subdirectories found in: {must_gather_path}")
    if len(subdirs) == 1:
        return subdirs[0]
    preferred = [d for d in subdirs if d.name.startswith("must-gather")]
    if preferred:
        return preferred[0]
    return subdirs[0]


def _find_noobaa_dir(root: Path) -> Path:
    """Return the ``noobaa/`` subdirectory within a must-gather root.

    Raises:
        ValueError: If the noobaa directory does not exist.
    """
    noobaa_dir = root / "noobaa"
    if not noobaa_dir.is_dir():
        raise ValueError("No noobaa/ directory found in this must-gather")
    return noobaa_dir


def _ensure_noobaa_diagnostics_extracted(noobaa_dir: Path) -> Path | None:
    """Extract the NooBaa diagnostics tarball if present and not yet extracted.

    Args:
        noobaa_dir: Path to the ``noobaa/`` directory in the must-gather.

    Returns:
        Path to the extracted diagnostics directory, or None if no
        diagnostics tarball exists.
    """
    raw_output = noobaa_dir / "raw_output"
    if not raw_output.is_dir():
        return None
    tarballs = sorted(raw_output.glob("noobaa_diagnostics_*.tar.gz"))
    if not tarballs:
        return None
    tarball = tarballs[0]
    extract_dir = raw_output / ".diagnostics_extracted"
    if extract_dir.is_dir() and any(extract_dir.iterdir()):
        return extract_dir
    extract_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:*") as tar:
        tar.extractall(path=extract_dir, filter="data")
    return extract_dir


def _count_files(directory: Path) -> int:
    """Count all files recursively under the given directory."""
    return sum(1 for _ in directory.rglob("*") if _.is_file())


def _count_files_and_size(directory: Path) -> tuple[int, int]:
    """Count files and total size in bytes recursively under a directory."""
    count = 0
    total_size = 0
    for f in directory.rglob("*"):
        if f.is_file():
            count += 1
            total_size += f.stat().st_size
    return count, total_size
