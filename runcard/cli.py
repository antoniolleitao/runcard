"""Command line interface: ``python -m runcard <cmd>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .build import build
from .compare import compare
from .provenance import provenance
from .study import (DEFAULT_METRIC, add_tool, init_study, load_json, load_study, log_query, log_run,
                    save_study, slugify)


def _out(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_init(a) -> int:
    d = a.dir or Path("studies") / slugify(a.question)
    metric = load_json(a.metric) if a.metric else DEFAULT_METRIC
    study = init_study(d, a.question, client=a.client, model=a.model, author=a.author, metric=metric)
    _out({"dir": Path(d).as_posix(), "question": study["question"], "created_at": study["created_at"]})
    return 0


def cmd_add_tool(a) -> int:
    meta = load_json(a.metadata)
    entry = add_tool(a.dir, meta, name=a.tool, doi=a.doi)
    _out({"tool": entry["name"], "url": entry["url"], "doi": entry["doi"],
          "inputs": len(entry["inputs"]), "outputs": len(entry["outputs"])})
    return 0


def cmd_set(a) -> int:
    study = load_study(a.dir)
    if a.aura_trace_id is not None:
        study["aura_trace_id"] = a.aura_trace_id
    if a.model is not None:
        study.setdefault("agent", {})["model"] = a.model
    if a.author is not None:
        study["author"] = a.author
    if a.resultsdb_utc_offset_hours is not None:
        study["resultsdb_utc_offset_hours"] = a.resultsdb_utc_offset_hours
    if a.rerun_of is not None:
        study["rerun_of"] = a.rerun_of
    save_study(a.dir, study)
    _out({"aura_trace_id": study.get("aura_trace_id"), "agent": study.get("agent"), "author": study.get("author")})
    return 0


def cmd_log_run(a) -> int:
    run = log_run(a.dir, tool=a.tool, chosen_inputs=load_json(a.chosen_inputs),
                  chosen_outputs=load_json(a.chosen_outputs), requested_at=a.requested_at,
                  completed_at=a.completed_at, result_payload=load_json(a.result), result_path=a.result)
    _out({k: run[k] for k in ("index", "tool", "status", "error", "squid", "revision", "metric_value",
                              "wall_seconds", "raw_path", "inline_attachments_stripped", "input_mismatches")})
    return 0 if run["status"] == "done" else 3


def cmd_log_query(a) -> int:
    q = log_query(a.dir, tool=a.tool, filters=load_json(a.filters), csv_path=a.csv, purpose=a.purpose)
    _out({k: q[k] for k in ("index", "tool", "purpose", "row_count", "csv_path")} | {"rows": q["rows"][:10]})
    return 0


def cmd_provenance(a) -> int:
    summary = provenance(a.dir, a.original_dir)
    study = load_study(a.dir)
    _out({"summary": summary, "runs": [{"index": r["index"], "squid": r.get("squid"),
                                        "served_from_cache": r.get("served_from_cache"),
                                        "original_date": r.get("original_date")} for r in study["runs"]]})
    return 0


def cmd_build(a) -> int:
    _out(build(a.dir))
    return 0


def cmd_rerun_plan(a) -> int:
    p = Path(a.dir) / "rerun.json"
    if not p.exists():
        build(a.dir)
    _out(load_json(p)["steps"])
    return 0


def cmd_compare(a) -> int:
    s = compare(a.dir, a.new_dir, tol=a.tol)
    _out({k: s[k] for k in ("runs_compared", "reproduced_from_cache", "revision_changed", "metric_drift",
                            "missing", "compare_md")} | {"rows": [{k: r.get(k) for k in
                                                                   ("index", "old_squid", "new_squid", "metric_rel_diff", "verdict")}
                                                                  for r in s["rows"]]})
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="runcard", description="Structured, verifiable, re-executable study records "
                                                            "for nanoHUB AURA MCP sessions.")
    p.add_argument("--version", action="version", version=f"runcard {__version__}")
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("init", help="create study.json")
    s.add_argument("question")
    s.add_argument("--dir", help="study directory (default studies/<slug>)")
    s.add_argument("--client", default="Claude Code")
    s.add_argument("--model", default="unspecified", help="LLM model id driving the session")
    s.add_argument("--author", default=None)
    s.add_argument("--metric", default=None, help="JSON file overriding the default metric")
    s.set_defaults(fn=cmd_init)

    s = sp.add_parser("add-tool", help="snapshot get_tool_metadata output")
    s.add_argument("--dir", required=True)
    s.add_argument("--metadata", required=True, help="JSON file with the get_tool_metadata response")
    s.add_argument("--tool", default=None, help="tool name if not present in the metadata file")
    s.add_argument("--doi", default=None)
    s.set_defaults(fn=cmd_add_tool)

    s = sp.add_parser("set", help="set aura_trace_id, model or author")
    s.add_argument("--dir", required=True)
    s.add_argument("--aura-trace-id", default=None)
    s.add_argument("--model", default=None)
    s.add_argument("--author", default=None)
    s.add_argument("--resultsdb-utc-offset-hours", type=float, default=None,
                   help="hours to subtract from ResultsDB dates to get UTC (auto-calibrated when omitted)")
    s.add_argument("--rerun-of", default=None, help="directory (or sibling slug) of the study this one re-executes")
    s.set_defaults(fn=cmd_set)

    s = sp.add_parser("log-run", help="parse a get_job_result payload and append a run")
    s.add_argument("--dir", required=True)
    s.add_argument("--tool", required=True)
    s.add_argument("--chosen-inputs", required=True, help="JSON file")
    s.add_argument("--chosen-outputs", required=True, help="JSON file (list)")
    s.add_argument("--requested-at", required=True, help="ISO 8601 time the run was submitted")
    s.add_argument("--completed-at", default=None, help="ISO 8601 time the result was fetched (default now)")
    s.add_argument("--result", required=True, help="JSON file with the get_job_result payload")
    s.set_defaults(fn=cmd_log_run)

    s = sp.add_parser("log-query", help="record a get_data_from_nanohub query")
    s.add_argument("--dir", required=True)
    s.add_argument("--tool", required=True)
    s.add_argument("--filters", required=True, help="JSON file: the filters (or the whole query args)")
    s.add_argument("--csv", required=True, help="CSV file with the query's data text")
    s.add_argument("--purpose", required=True)
    s.set_defaults(fn=cmd_log_query)

    s = sp.add_parser("provenance", help="classify each run as cached / fresh / unverified")
    s.add_argument("--dir", required=True)
    s.add_argument("--original-dir", default=None, help="study this one re-executes (overrides rerun_of)")
    s.set_defaults(fn=cmd_provenance)

    s = sp.add_parser("build", help="write card.md, card.html, ro-crate-metadata.json, rerun.json, methods.txt")
    s.add_argument("--dir", required=True)
    s.set_defaults(fn=cmd_build)

    s = sp.add_parser("rerun-plan", help="print the ordered steps from rerun.json")
    s.add_argument("--dir", required=True)
    s.set_defaults(fn=cmd_rerun_plan)

    s = sp.add_parser("compare", help="compare a study with its re-execution")
    s.add_argument("--dir", required=True)
    s.add_argument("--new-dir", required=True)
    s.add_argument("--tol", type=float, default=1e-6, help="relative tolerance for metric drift")
    s.set_defaults(fn=cmd_compare)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (FileNotFoundError, FileExistsError, ValueError, KeyError) as exc:
        print(f"runcard: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
