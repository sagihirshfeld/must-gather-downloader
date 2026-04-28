import tarfile
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=32)
def _find_must_gather_root(must_gather_path: str) -> Path:
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
    noobaa_dir = root / "noobaa"
    if not noobaa_dir.is_dir():
        raise ValueError("No noobaa/ directory found in this must-gather")
    return noobaa_dir


def _ensure_noobaa_diagnostics_extracted(noobaa_dir: Path) -> Path | None:
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
    return sum(1 for _ in directory.rglob("*") if _.is_file())


def _count_files_and_size(directory: Path) -> tuple[int, int]:
    count = 0
    total_size = 0
    for f in directory.rglob("*"):
        if f.is_file():
            count += 1
            total_size += f.stat().st_size
    return count, total_size
