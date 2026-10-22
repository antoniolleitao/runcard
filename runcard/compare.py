"""Compare a study against its re-execution."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .study import fmt_num, load_study, metric_series, run_input_value, varied_inputs

REL_TOL = 1e-6


def _inputs_signature(run: dict) -> str:
    ri = run.get("effective_inputs") or run.get("resolved_inputs") or {}
    if ri:
        vals = {k: v.get("value") for k, v in ri.items()}
        vals.update(run.get("chosen_inputs", {}))
        return json.dumps(vals, sort_keys=True, default=str)
    return json.dumps(run.get("chosen_inputs", {}), sort_keys=True, default=str)


def _pair_runs(old: list[dict], new: list[dict]) -> list[tuple[dict, dict | None]]:
    """Pair by (tool, chosen_inputs); fall back to order."""
    pairs: list[tuple[dict, dict | None]] = []
    used: set[int] = set()
    for o in old:
        key = (o["tool"], json.dumps(o.get("chosen_inputs", {}), sort_keys=True))
        match = None
        for i, n in enumerate(new):
            if i in used:
                continue
            if (n["tool"], json.dumps(n.get("chosen_inputs", {}), sort_keys=True)) == key:
                match = n
                used.add(i)
                break
        pairs.append((o, match))
    return pairs


def _rel_diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    denom = max(abs(a), abs(b), 1e-300)
    return abs(a - b) / denom


def _series_diff(a_out: Any, b_out: Any) -> dict | None:
    _, ya = metric_series(a_out)
    _, yb = metric_series(b_out)
    if not ya or not yb:
        return None
    n = min(len(ya), len(yb))
    diffs = [_rel_diff(ya[i], yb[i]) for i in range(n)]
    diffs = [x for x in diffs if x is not None]
    return {"points_compared": n, "length_old": len(ya), "length_new": len(yb),
            "max_rel_diff": max(diffs) if diffs else None,
            "mean_rel_diff": (sum(diffs) / len(diffs)) if diffs else None}


def compare_runs(old: dict, new: dict | None, metric: dict, tol: float = REL_TOL) -> dict:
    entry: dict[str, Any] = {
        "index": old.get("index"),
        "tool": old.get("tool"),
        "chosen_inputs": old.get("chosen_inputs", {}),
        "old_squid": old.get("squid"),
        "new_squid": new.get("squid") if new else None,
        "old_revision": old.get("revision"),
        "new_revision": new.get("revision") if new else None,
        "old_metric": old.get("metric_value"),
        "_old_run": old,
        "new_metric": new.get("metric_value") if new else None,
    }
    if new is None:
        entry.update(verdict="missing", detail="no run with the same tool and chosen inputs in the new study")
        return entry
    if old.get("status") != "done" or new.get("status") != "done":
        entry.update(verdict="failed", detail=f"old status {old.get('status')}, new status {new.get('status')}")
        return entry
    same_squid = old.get("squid") and old.get("squid") == new.get("squid")
    same_inputs = _inputs_signature(old) == _inputs_signature(new)
    rel = _rel_diff(old.get("metric_value"), new.get("metric_value"))
    entry["metric_rel_diff"] = rel
    sd = _series_diff(old.get("outputs", {}).get(metric.get("output")),
                      new.get("outputs", {}).get(metric.get("output")))
    entry["series"] = sd
    drift = (rel is not None and rel > tol) or (sd and sd.get("max_rel_diff") is not None and sd["max_rel_diff"] > tol)
    if same_squid:
        entry["verdict"] = "reproduced from cache"
        entry["detail"] = "same ResultsDB squid; nanoHUB returned the stored result"
        if drift:
            entry["verdict"] = "same squid but values differ"
            entry["detail"] = "same squid yet the metric or series changed; inspect raw payloads"
    elif same_inputs:
        entry["verdict"] = "tool revision changed" if old.get("revision") != new.get("revision") \
            else "recomputed with same inputs"
        entry["detail"] = (f"identical resolved inputs but different squid (r{old.get('revision')} -> r{new.get('revision')})"
                           + ("; metric drifted" if drift else "; metric within tolerance"))
    else:
        entry["verdict"] = "inputs differ"
        entry["detail"] = "resolved inputs are not identical; the runs are not the same simulation"
    entry["metric_drift"] = bool(drift)
    return entry


def compare(old_dir: str | os.PathLike, new_dir: str | os.PathLike, tol: float = REL_TOL) -> dict:
    old_dir, new_dir = Path(old_dir), Path(new_dir)
    old, new = load_study(old_dir), load_study(new_dir)
    metric = old["metric"]
    rows = [compare_runs(o, n, metric, tol) for o, n in _pair_runs(old.get("runs", []), new.get("runs", []))]
    extra_new = len(new.get("runs", [])) - sum(1 for r in rows if r.get("new_squid") is not None or r.get("verdict") == "failed")
    summary = {
        "old_dir": old_dir.as_posix(), "new_dir": new_dir.as_posix(),
        "question": old["question"], "tolerance": tol,
        "runs_compared": len(rows),
        "reproduced_from_cache": sum(1 for r in rows if r["verdict"] == "reproduced from cache"),
        "revision_changed": sum(1 for r in rows if r["verdict"] == "tool revision changed"),
        "metric_drift": sum(1 for r in rows if r.get("metric_drift")),
        "missing": sum(1 for r in rows if r["verdict"] == "missing"),
        "unpaired_new_runs": max(extra_new, 0),
        "rows": rows,
    }
    md = compare_markdown(summary, old, new)
    (old_dir / "compare.md").write_text(md, encoding="utf-8")
    (new_dir / "compare.md").write_text(md, encoding="utf-8")
    summary["compare_md"] = (old_dir / "compare.md").as_posix()
    return summary


def compare_markdown(summary: dict, old: dict, new: dict) -> str:
    varied = varied_inputs(old.get("runs", []))
    L = [f"# Comparison: {summary['question']}", ""]
    L.append(f"Original study: `{summary['old_dir']}` (created {old.get('created_at')}, "
             f"AURA trace `{old.get('aura_trace_id') or 'n/a'}`)")
    L.append("")
    L.append(f"Re-execution: `{summary['new_dir']}` (created {new.get('created_at')}, "
             f"AURA trace `{new.get('aura_trace_id') or 'n/a'}`)")
    L.append("")
    L.append(f"{summary['runs_compared']} runs compared: {summary['reproduced_from_cache']} reproduced from cache, "
             f"{summary['revision_changed']} with a changed tool revision, {summary['metric_drift']} with metric drift "
             f"above {summary['tolerance']:g} relative, {summary['missing']} missing in the re-execution"
             + (f", {summary['unpaired_new_runs']} extra runs in the re-execution" if summary['unpaired_new_runs'] else "") + ".")
    L.append("")
    L.append("| idx | varied inputs | old squid | new squid | old metric | new metric | rel diff | series max rel diff | verdict |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in summary["rows"]:
        label = ", ".join(f"{k}={fmt_num(run_input_value(old, r.get('_old_run', {}), k))}" for k in varied) or "(all defaults)"
        sd = r.get("series") or {}
        L.append(f"| {r['index']} | {label} | `{r.get('old_squid') or '-'}` | `{r.get('new_squid') or '-'}` | "
                 f"{fmt_num(r.get('old_metric'))} | {fmt_num(r.get('new_metric'))} | "
                 f"{fmt_num(r.get('metric_rel_diff'), 3) if r.get('metric_rel_diff') is not None else '-'} | "
                 f"{fmt_num(sd.get('max_rel_diff'), 3) if sd.get('max_rel_diff') is not None else '-'} | "
                 f"{r['verdict']} |")
    L.append("")
    L.append("## Details")
    L.append("")
    for r in summary["rows"]:
        L.append(f"- run {r['index']}: {r['verdict']}. {r.get('detail', '')}")
    L.append("")
    L.append("Verdicts: *reproduced from cache* = same squid; *tool revision changed* = identical resolved inputs, "
             "different squid and revision; *inputs differ* = resolved inputs not identical; *missing* = no matching run.")
    L.append("")
    return "\n".join(L)
