"""Minimal, dependency-free parser for the ``simulation_inputs`` YAML string
returned by AURA's ``get_job_result``.

The string is a flat mapping of blocks::

    Na:
        value: 2e15
        units: cm^-3
        min: 1e10
        max: 2e22
    materialp:
        value: Si

Only this shape is supported (top-level name, indented ``key: value`` pairs,
optionally a top-level inline scalar).  Lists written as ``- item`` lines are
collected into Python lists.  Anything else is ignored rather than raising.
"""

from __future__ import annotations

import re
from typing import Any

_KV = re.compile(r"^(\s*)([^\s#][^:]*?)\s*:\s*(.*?)\s*$")
_LIST_ITEM = re.compile(r"^(\s*)-\s*(.*?)\s*$")


def parse_scalar(text: str) -> Any:
    """Convert a YAML-ish scalar to int, float, bool, None or stripped string."""
    s = text.strip()
    if s == "" or s in ("~", "null", "Null", "NULL"):
        return None
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [parse_scalar(x) for x in inner.split(",")] if inner else []
    try:
        if re.fullmatch(r"[+-]?\d+", s):
            return int(s)
    except ValueError:
        pass
    try:
        if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s):
            return float(s)
    except ValueError:
        pass
    return s


def parse_simulation_inputs(text: str) -> dict[str, dict[str, Any]]:
    """Parse the flat YAML mapping into ``{name: {key: value, ...}}``.

    A top-level entry with an inline scalar becomes ``{"value": scalar}`` so
    every entry is a dict and callers can always read ``entry["value"]``.
    """
    result: dict[str, dict[str, Any]] = {}
    current: str | None = None
    last_key: str | None = None
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m_list = _LIST_ITEM.match(line)
        if m_list and current is not None and len(m_list.group(1)) > 0:
            if last_key is not None:
                box = result[current]
                if not isinstance(box.get(last_key), list):
                    box[last_key] = [] if box.get(last_key) in (None, "") else [box[last_key]]
                box[last_key].append(parse_scalar(m_list.group(2)))
            continue
        m = _KV.match(line)
        if not m:
            continue
        indent, key, value = m.group(1), m.group(2).strip(), m.group(3)
        if len(indent) == 0:
            current = key
            result.setdefault(current, {})
            last_key = None
            if value != "":
                result[current]["value"] = parse_scalar(value)
        elif current is not None:
            result[current][key] = parse_scalar(value)
            last_key = key
    return result


def resolved_inputs_from_yaml(text: str) -> dict[str, dict[str, Any]]:
    """Return ``{name: {"value": v, "units": u, "min": .., "max": ..}}``.

    Keys other than value/units/min/max are kept too but these four are
    always present (``None`` when the YAML did not provide them).
    """
    out: dict[str, dict[str, Any]] = {}
    for name, box in parse_simulation_inputs(text).items():
        entry = dict(box)
        for k in ("value", "units", "min", "max"):
            entry.setdefault(k, None)
        out[name] = entry
    return out
