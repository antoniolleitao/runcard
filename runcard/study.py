"""Study record: creation, tool snapshots, run and query logging."""

from __future__ import annotations

import copy
import csv
import io
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION
from .yamlinputs import resolved_inputs_from_yaml

STUDY_FILE = "study.json"
RAW_DIR = "raw"
ARRAY_CAP = 2000            # numbers kept per output array
STRING_CAP = 2 * 1024       # bytes kept per output string
RAW_STRING_CAP = 20 * 1024  # bytes kept per string inside raw payloads

DEFAULT_METRIC = {
    "output": "IV Characteristic",
    "reduce": "last_of_function",
    "unit": "A/cm^2",
    "label": "current density at max bias",
}

_SQUID = re.compile(r"^(?P<tool>[^/]+)/r(?P<rev>\d+)/(?P<hash>[0-9a-zA-Z_-]+)$")


# --------------------------------------------------------------------------- time

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(text: Any) -> datetime | None:
    """Parse ISO 8601 and a few common variants. Naive values are taken as UTC."""
    if text is None:
        return None
    if isinstance(text, datetime):
        dt = text
    else:
        s = str(text).strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = None
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                        "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%d %b %Y %H:%M:%S",
                        "%a, %d %b %Y %H:%M:%S %Z", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------- io

def load_study(d: str | os.PathLike) -> dict:
    p = Path(d) / STUDY_FILE
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_study(d: str | os.PathLike, study: dict) -> Path:
    p = Path(d) / STUDY_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(study, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return p


def load_json(path: str | os.PathLike) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | os.PathLike, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def warn(msg: str) -> None:
    print(f"runcard: warning: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- init

def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "study"


def init_study(d: str | os.PathLike, question: str, *, client: str = "Claude Code",
               model: str = "unspecified", author: str | None = None,
               metric: dict | None = None, now: datetime | None = None) -> dict:
    d = Path(d)
    if (d / STUDY_FILE).exists():
        raise FileExistsError(f"{d / STUDY_FILE} already exists")
    study = {
        "schema_version": SCHEMA_VERSION,
        "question": question,
        "slug": d.name,
        "created_at": iso(now or utcnow()),
        "agent": {"client": client, "model": model},
        "author": author or os.environ.get("RUNCARD_AUTHOR") or os.environ.get("USERNAME")
        or os.environ.get("USER") or "unknown",
        "aura_trace_id": None,
        "metric": dict(metric or DEFAULT_METRIC),
        "tools": {},
        "runs": [],
        "queries": [],
    }
    (d / RAW_DIR).mkdir(parents=True, exist_ok=True)
    save_study(d, study)
    return study


# --------------------------------------------------------------------------- tools

def add_tool(d: str | os.PathLike, metadata: dict, *, name: str | None = None,
             doi: str | None = None, now: datetime | None = None) -> dict:
    study = load_study(d)
    name = name or metadata.get("name") or metadata.get("nH_tool")
    if not name:
        raise ValueError("tool name not found in metadata; pass --tool")
    entry = {
        "name": name,
        "url": f"https://nanohub.org/tools/{name}",
        "doi": doi or None,
        "tool_kind": metadata.get("tool_kind"),
        "execution_tool": metadata.get("execution_tool"),
        "inputs": metadata.get("inputs", {}),
        "outputs": metadata.get("outputs", {}),
        "snapshot_at": iso(now or utcnow()),
    }
    study["tools"][name] = entry
    save_study(d, study)
    return entry


# --------------------------------------------------------------------------- sanitising

def strip_inline_files(payload: Any) -> tuple[Any, bool]:
    """Return a deep copy with every ``inline_files`` key removed, plus a flag."""
    found = False

    def _walk(x):
        nonlocal found
        if isinstance(x, dict):
            out = {}
            for k, v in x.items():
                if k == "inline_files":
                    found = True
                    continue
                out[k] = _walk(v)
            return out
        if isinstance(x, list):
            return [_walk(v) for v in x]
        return x

    return _walk(copy.deepcopy(payload)), found


def truncate_strings(payload: Any, cap: int = RAW_STRING_CAP) -> Any:
    """Deep copy with any string longer than ``cap`` bytes cut and marked."""

    def _walk(x):
        if isinstance(x, dict):
            return {k: _walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [_walk(v) for v in x]
        if isinstance(x, str) and len(x.encode("utf-8")) > cap:
            kept = x.encode("utf-8")[:cap].decode("utf-8", errors="ignore")
            return kept + f"\n...[runcard: truncated {len(x) - len(kept)} characters]"
        return x

    return _walk(payload)


def sanitize_payload(payload: Any) -> tuple[Any, bool]:
    clean, had_inline = strip_inline_files(payload)
    return truncate_strings(clean), had_inline


def cap_output(value: Any) -> Any:
    """Cap arrays to ARRAY_CAP numbers (even subsample keeping endpoints) and
    strings to STRING_CAP bytes."""
    if isinstance(value, list):
        if len(value) > ARRAY_CAP and all(isinstance(v, (int, float)) for v in value):
            n = len(value)
            idx = [round(i * (n - 1) / (ARRAY_CAP - 1)) for i in range(ARRAY_CAP)]
            return {"_capped": True, "original_length": n, "values": [value[i] for i in idx]}
        return [cap_output(v) for v in value]
    if isinstance(value, dict):
        return {k: cap_output(v) for k, v in value.items()}
    if isinstance(value, str) and len(value.encode("utf-8")) > STRING_CAP:
        kept = value.encode("utf-8")[:STRING_CAP].decode("utf-8", errors="ignore")
        return kept + f"\n...[runcard: truncated {len(value) - len(kept)} characters]"
    return value


# --------------------------------------------------------------------------- result parsing

def unwrap_result(payload: dict) -> dict:
    """Accept either the full get_job_result envelope or its ``result`` body."""
    if isinstance(payload, dict) and isinstance(payload.get("result"), dict) and (
        "success" in payload["result"] or "simulation_summary" in payload["result"]
        or "error" in payload["result"]
    ):
        return payload["result"]
    return payload


def parse_squid(squid: str | None) -> tuple[str | None, int | None]:
    if not squid:
        return None, None
    m = _SQUID.match(str(squid))
    if not m:
        return None, None
    return m.group("tool"), int(m.group("rev"))


def outputs_from_summary(summary: Any, chosen_outputs: list[str]) -> dict[str, Any]:
    """Map simulation_summary (one entry per chosen output, same order) to names.

    Tolerates entries shaped as ``{name: value}``, ``{"name":..,"value":..}``,
    ``{"output":..,"value":..}`` or bare values.
    """
    out: dict[str, Any] = {}
    if isinstance(summary, dict):
        for k, v in summary.items():
            out[k] = v
        return out
    if not isinstance(summary, list):
        return out
    for i, entry in enumerate(summary):
        name = chosen_outputs[i] if i < len(chosen_outputs) else f"output_{i}"
        value = entry
        if isinstance(entry, dict):
            if len(entry) == 1 and next(iter(entry)) in chosen_outputs:
                name, value = next(iter(entry.items()))
            elif "name" in entry and "value" in entry:
                name, value = entry["name"], entry["value"]
            elif "output" in entry and "value" in entry:
                name, value = entry["output"], entry["value"]
            elif "label" in entry and "value" in entry:
                name, value = entry["label"], entry["value"]
        out[name] = value
    return out


# --------------------------------------------------------------------------- metric

def _series(output: Any) -> list[float] | None:
    if isinstance(output, dict):
        f = output.get("function")
        if isinstance(f, dict) and "values" in f:
            f = f["values"]
        if isinstance(f, list):
            return [float(v) for v in f if isinstance(v, (int, float))]
    if isinstance(output, list) and all(isinstance(v, (int, float)) for v in output):
        return [float(v) for v in output]
    return None


def metric_series(output: Any) -> tuple[list[float] | None, list[float] | None]:
    """Return (x, y) for an output shaped {voltage: [...], function: [...]}."""
    y = _series(output)
    x = None
    if isinstance(output, dict):
        for key in ("voltage", "x", "position", "time"):
            v = output.get(key)
            if isinstance(v, dict) and "values" in v:
                v = v["values"]
            if isinstance(v, list):
                x = [float(e) for e in v]
                break
    return x, y


def compute_metric(outputs: dict[str, Any], metric: dict) -> float | None:
    out = outputs.get(metric.get("output"))
    if out is None:
        return None
    reduce = metric.get("reduce", "last_of_function")
    if reduce == "scalar":
        return float(out) if isinstance(out, (int, float)) else None
    y = _series(out)
    if not y:
        return None
    if reduce == "last_of_function":
        return y[-1]
    if reduce == "first_of_function":
        return y[0]
    if reduce == "max_of_function":
        return max(y)
    if reduce == "min_of_function":
        return min(y)
    if reduce == "mean_of_function":
        return sum(y) / len(y)
    raise ValueError(f"unknown metric reduce: {reduce}")


REDUCE_TEXT = {
    "last_of_function": "the last value of the 'function' array",
    "first_of_function": "the first value of the 'function' array",
    "max_of_function": "the maximum of the 'function' array",
    "min_of_function": "the minimum of the 'function' array",
    "mean_of_function": "the mean of the 'function' array",
    "scalar": "the scalar value",
}


# --------------------------------------------------------------------------- simulator log date

_LOG_DATE = re.compile(r"Date and time\s*=\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s+(\d{1,2}):(\d{2}):(\d{2})")


def simulator_log_date(payload: Any) -> str | None:
    """Find the PADRE-style 'Date and time = MM/DD/YY HH:MM:SS' stamp inside
    inline_files (before they are stripped). Returned as ISO 8601, assumed UTC."""
    body = unwrap_result(payload) if isinstance(payload, dict) else {}
    files = body.get("inline_files") if isinstance(body, dict) else None
    if not isinstance(files, dict):
        return None
    for v in files.values():
        text = v.get("content") if isinstance(v, dict) else v
        if not isinstance(text, str):
            continue
        m = _LOG_DATE.search(text[:5000])
        if m:
            mo, da, yr, hh, mi, ss = (int(x) for x in m.groups())
            if yr < 100:
                yr += 2000
            try:
                return iso(datetime(yr, mo, da, hh, mi, ss, tzinfo=timezone.utc))
            except ValueError:
                return None
    return None


def effective_inputs(chosen: dict, resolved: dict) -> dict[str, dict]:
    """Server-reported inputs overlaid with the values the client actually chose.

    AURA MCP v2.0.0's simulation_inputs YAML lists the tool defaults even when a
    different value was submitted, so the chosen value wins; the server's value
    is kept under ``reported`` when it differs."""
    out: dict[str, dict] = {}
    for name, box in (resolved or {}).items():
        out[name] = dict(box)
    for name, v in (chosen or {}).items():
        box = dict(out.get(name, {"units": None, "min": None, "max": None}))
        if "value" in box and box["value"] is not None and not _same_value(v, box["value"]):
            box["reported"] = box["value"]
        box["value"] = v
        out[name] = box
    return out


# --------------------------------------------------------------------------- input check

def _same_value(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b) if isinstance(a, (bool, int, float)) and isinstance(b, (bool, int, float))             else str(a).lower() == str(b).lower()
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 1e-9 * max(abs(float(a)), abs(float(b)), 1.0)
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        try:
            return _same_value(float(a), float(b))
        except (TypeError, ValueError):
            return False
    return str(a).strip() == str(b).strip()


def input_mismatches(chosen: dict, resolved: dict) -> list[dict]:
    """Chosen inputs whose value differs from the resolved value the server reports."""
    out = []
    for name, v in (chosen or {}).items():
        box = (resolved or {}).get(name)
        if not isinstance(box, dict) or "value" not in box or box["value"] is None:
            continue
        if not _same_value(v, box["value"]):
            out.append({"name": name, "chosen": v, "resolved": box["value"]})
    return out


# --------------------------------------------------------------------------- log-run

def log_run(d: str | os.PathLike, *, tool: str, chosen_inputs: dict, chosen_outputs: list[str],
            requested_at: str, result_payload: dict, completed_at: str | None = None,
            result_path: str | None = None, raw_dir: str = RAW_DIR) -> dict:
    d = Path(d)
    study = load_study(d)
    clean, had_inline = sanitize_payload(result_payload)
    if had_inline:
        warn("result contained inline_files; stripped before persisting")
    body = unwrap_result(clean)

    idx = len(study["runs"])
    raw_rel = f"{raw_dir}/run-{idx:02d}-{tool}.json"
    write_json(d / raw_rel, clean)
    # if the caller's file lives inside the study dir, rewrite it sanitized too
    if result_path:
        rp = Path(result_path).resolve()
        try:
            rp.relative_to(d.resolve())
            if had_inline and rp != (d / raw_rel).resolve():
                write_json(rp, clean)
        except ValueError:
            pass

    if "success" in body:
        success = bool(body.get("success"))
    else:
        success = "error" not in body and "simulation_summary" in body
    squid = body.get("simulation_squidID") or body.get("squid")
    _, revision = parse_squid(squid)
    yaml_text = body.get("simulation_inputs") or ""
    resolved = resolved_inputs_from_yaml(yaml_text) if isinstance(yaml_text, str) else {}
    full_outputs = outputs_from_summary(body.get("simulation_summary"), chosen_outputs) if success else {}
    metric_value = compute_metric(full_outputs, study["metric"]) if success else None

    req = parse_dt(requested_at)
    comp = parse_dt(completed_at) if completed_at else utcnow()
    wall = round((comp - req).total_seconds(), 3) if req and comp else None
    mismatches = input_mismatches(chosen_inputs, resolved) if success else []
    for m in mismatches:
        warn(f"chosen input {m['name']}={m['chosen']!r} but the server's simulation_inputs reports "
             f"{m['resolved']!r}; recording the chosen value as effective and keeping the reported one")
    log_date = simulator_log_date(result_payload)

    run = {
        "index": idx,
        "tool": tool,
        "chosen_inputs": chosen_inputs,
        "chosen_outputs": list(chosen_outputs),
        "requested_at": iso(req) if req else requested_at,
        "completed_at": iso(comp) if comp else None,
        "wall_seconds": wall,
        "status": "done" if success else "failed",
        "error": None if success else (body.get("error") or "unknown error"),
        "squid": squid,
        "revision": revision,
        "resolved_inputs": resolved,
        "effective_inputs": effective_inputs(chosen_inputs, resolved) if success else {},
        "simulator_log_date": log_date,
        "outputs": cap_output(full_outputs),
        "metric_value": metric_value,
        "input_mismatches": mismatches,
        "artifacts": body.get("artifacts", []),
        "raw_path": raw_rel,
        "inline_attachments_stripped": had_inline,
        "served_from_cache": None,
        "original_date": None,
    }
    study["runs"].append(run)
    save_study(d, study)
    return run


# --------------------------------------------------------------------------- log-query

def parse_query_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    text = (text or "").lstrip("﻿")
    if not text.strip():
        return [], []
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(r) for r in reader]
    return list(reader.fieldnames or []), rows


def _pick(row: dict, *names: str) -> str | None:
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return None


def log_query(d: str | os.PathLike, *, tool: str, filters: dict | list, csv_path: str,
              purpose: str, raw_dir: str = RAW_DIR, now: datetime | None = None) -> dict:
    d = Path(d)
    study = load_study(d)
    idx = len(study["queries"])
    src = Path(csv_path)
    text = src.read_text(encoding="utf-8") if src.exists() else ""
    header, rows = parse_query_csv(text)
    dest_rel = f"{raw_dir}/query-{idx:02d}-{tool}.csv"
    dest = d / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        dest.write_text("", encoding="utf-8")
    elif src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)

    kept = [{
        "squid": _pick(r, "squid", "SQUID"),
        "revision": _pick(r, "revision", "REVISION"),
        "date": _pick(r, "date", "DATE", "created", "timestamp"),
    } for r in rows]
    if isinstance(filters, list):
        filters = {"inputs_to_filter_by": filters, "outputs_to_filter_by": []}
    entry = {
        "index": idx,
        "tool": tool,
        "purpose": purpose,
        "filters": filters,
        "logged_at": iso(now or utcnow()),
        "csv_path": dest_rel,
        "columns": header,
        "row_count": len(rows),
        "rows": kept,
    }
    study["queries"].append(entry)
    save_study(d, study)
    return entry


# --------------------------------------------------------------------------- helpers shared by build/compare

def varied_inputs(runs: list[dict]) -> list[str]:
    """Input names whose chosen value is not identical across all runs."""
    keys: list[str] = []
    for r in runs:
        for k in r.get("chosen_inputs", {}):
            if k not in keys:
                keys.append(k)
    if len(runs) <= 1:
        return keys
    varied = []
    for k in keys:
        vals = {json.dumps(r.get("chosen_inputs", {}).get(k), sort_keys=True) for r in runs}
        if len(vals) > 1:
            varied.append(k)
    return varied


def run_input_value(study: dict, run: dict, name: str) -> Any:
    """Effective value of an input for a run: chosen, else resolved, else tool default."""
    ci = run.get("chosen_inputs", {})
    if name in ci:
        return ci[name]
    for key in ("effective_inputs", "resolved_inputs"):
        ri = (run.get(key) or {}).get(name)
        if isinstance(ri, dict) and ri.get("value") is not None:
            return ri["value"]
    meta = study.get("tools", {}).get(run.get("tool"), {}).get("inputs", {}).get(name, {})
    return meta.get("default")


def fixed_nondefault_inputs(runs: list[dict]) -> dict[str, Any]:
    """Chosen inputs that hold the same (non-default) value across all runs."""
    if not runs:
        return {}
    v = set(varied_inputs(runs))
    out = {}
    for k, val in runs[0].get("chosen_inputs", {}).items():
        if k not in v and all(json.dumps(r.get("chosen_inputs", {}).get(k), sort_keys=True)
                              == json.dumps(val, sort_keys=True) for r in runs):
            out[k] = val
    return out


_UNIT_MAP = {
    "1 / centimeter ** 3": "cm^-3",
    "kelvin": "K",
    "volt": "V",
    "second": "s",
    "micrometer": "um",
    "ampere / centimeter ** 2": "A/cm^2",
    "dimensionless": "",
}


def normalise_units(u: Any) -> str:
    s = str(u).strip()
    return _UNIT_MAP.get(s, s)


def input_units(study: dict, tool: str, name: str) -> str | None:
    t = study.get("tools", {}).get(tool, {})
    meta = t.get("inputs", {}).get(name, {})
    u = meta.get("units")
    if u:
        return normalise_units(u)
    for r in study.get("runs", []):
        ri = r.get("resolved_inputs", {}).get(name, {})
        if ri.get("units"):
            return normalise_units(ri["units"])
    return None


def fmt_num(v: Any, sig: int = 4) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v == 0:
            return "0"
        if abs(v) >= 1e4 or abs(v) < 1e-3:
            return f"{v:.{sig - 1}e}"
        return f"{v:.{sig}g}"
    return str(v)
