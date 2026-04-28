import json
import re

from .navigate import _find_must_gather_root


def search_must_gather(
    must_gather_path: str,
    pattern: str,
    file_pattern: str = "",
    max_results: int = 50,
    case_sensitive: bool = False,
) -> str:
    if not pattern:
        return json.dumps({"error": "pattern parameter is required"})

    root = _find_must_gather_root(must_gather_path)

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        compiled = re.compile(pattern, flags)
    except re.error:
        compiled = re.compile(re.escape(pattern), flags)

    if file_pattern:
        files = [f for f in root.rglob(file_pattern) if f.is_file()]
    else:
        files = [f for f in root.rglob("*") if f.is_file()]

    matches = []
    files_searched = 0
    truncated = False

    for filepath in sorted(files):
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
                    if compiled.search(line):
                        matches.append({
                            "file": str(filepath.relative_to(root)),
                            "line_number": line_number,
                            "line": line.strip(),
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
