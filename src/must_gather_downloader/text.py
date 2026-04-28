import re

MAX_LOG_SIZE = 200 * 1024

_TIMESTAMP_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"
    r"|([A-Z]\d{4}\s+\d{2}:\d{2}:\d{2})"
    r"|^(\d{2}:\d{2}:\d{2})"
)


def _strip_yaml_keys(content: str, keys: list[str]) -> str:
    triggers = tuple(k + ":" for k in keys)
    lines = content.split("\n")
    result = []
    skip = False
    base_indent = 0
    for line in lines:
        if not line.strip():
            if not skip:
                result.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.lstrip()
        if any(stripped.startswith(t) for t in triggers):
            skip = True
            base_indent = indent
            continue
        if skip:
            if indent > base_indent or (
                indent == base_indent and stripped.startswith("- ")
            ):
                continue
            skip = False
        result.append(line)
    return "\n".join(result)


def _strip_managed_fields(content: str) -> str:
    return _strip_yaml_keys(content, ["managedFields"])


def _tail_yaml_list(content: str, count: int) -> tuple[str, int]:
    parts = re.split(r"(?=^- )", content, flags=re.MULTILINE)
    header = parts[0]
    items = parts[1:]
    total = len(items)
    if count and len(items) > count:
        items = items[-count:]
    return header + "".join(items), total


def _extract_time_str(line: str) -> str | None:
    m = _TIMESTAMP_RE.search(line[:50])
    if not m:
        return None
    if m.group(1):
        return m.group(1).split("T")[-1].split(" ")[-1][:8]
    if m.group(2):
        return m.group(2).split()[-1][:8]
    if m.group(3):
        return m.group(3)[:8]
    return None


def _normalize_time(t: str) -> str:
    t = t.strip()
    if "T" in t or " " in t:
        t = t.replace("T", " ").split(" ")[-1]
    t = t[:8]
    if len(t) == 5:
        t += ":00"
    return t


def _filter_log_by_time(
    content: str, time_from: str = "", time_to: str = ""
) -> tuple[str, int, int]:
    lines = content.splitlines()
    total = len(lines)
    t_from = _normalize_time(time_from) if time_from else None
    t_to = _normalize_time(time_to) if time_to else None
    in_range = t_from is None
    kept = []
    for line in lines:
        ts = _extract_time_str(line)
        if ts is not None:
            if t_from and t_to:
                in_range = t_from <= ts <= t_to
            elif t_from:
                in_range = ts >= t_from
            elif t_to:
                in_range = ts <= t_to
        if in_range:
            kept.append(line)
    result = "\n".join(kept)
    if kept:
        result += "\n"
    return result, total, len(kept)
