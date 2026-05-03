import json
import re

from .navigate import _find_must_gather_root

_MAX_LINE_LENGTH = 10_000


def search_must_gather(
    must_gather_path: str,
    pattern: str,
    file_pattern: str = "",
    max_results: int = 50,
    case_sensitive: bool = False,
) -> str:
    """Search text files in a must-gather for lines matching a pattern.

    Binary files are auto-detected and skipped. Invalid regex patterns
    are treated as literal strings. Very long lines are capped at
    ``_MAX_LINE_LENGTH`` characters.

    Args:
        must_gather_path: Path to the must-gather extraction.
        pattern: Regex or literal string to search for.
        file_pattern: Optional glob to restrict which files are searched.
        max_results: Maximum number of matches to return.
        case_sensitive: If False (default), search is case-insensitive.

    Returns:
        JSON string with matches list, files_searched count, and
        truncated flag.
    """
    if not pattern:
        return json.dumps({"error": "pattern parameter is required"})

    root = _find_must_gather_root(must_gather_path)

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        compiled = re.compile(pattern, flags)
    except re.error:
        compiled = re.compile(re.escape(pattern), flags)

    if file_pattern:
        files = (f for f in root.rglob(file_pattern) if f.is_file())
    else:
        files = (f for f in root.rglob("*") if f.is_file())

    matches = []
    files_searched = 0
    truncated = False

    for filepath in files:
        try:
            head = filepath.read_bytes()[:512]
        except OSError:
            continue
        if b"\x00" in head:
            continue

        files_searched += 1
        try:
            with open(filepath, encoding="utf-8", errors="replace") as fh:
                for line_number, line in enumerate(fh, start=1):
                    if compiled.search(line[:_MAX_LINE_LENGTH]):
                        matches.append({
                            "file": str(filepath.relative_to(root)),
                            "line_number": line_number,
                            "line": line.strip()[:_MAX_LINE_LENGTH],
                        })
                        if len(matches) >= max_results:
                            truncated = True
                            break
        except OSError:
            continue
        if truncated:
            break

    return json.dumps({
        "pattern": pattern,
        "file_pattern": file_pattern,
        "case_sensitive": case_sensitive,
        "matches": matches,
        "total_matches": len(matches),
        "files_searched": files_searched,
        "truncated": truncated,
    })
