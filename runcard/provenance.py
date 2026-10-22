"""Decide, per run, whether nanoHUB served it from the ResultsDB cache.

ResultsDB ``date`` values are not UTC (observed: 7 h behind the simulator log and
the job-status timestamps on 2026-10-21).  The offset is calibrated from runs
that carry both a simulator log stamp and a query row, or set explicitly with
``runcard set --resultsdb-utc-offset-hours``.

Rule: find the run's squid among the rows of logged queries.  If the squid was
already listed by a query logged *before* the run was requested, or if the
earliest date seen for it is more than ``CACHE_WINDOW`` before the run's
``requested_at``, the result was pre-existing (served_from_cache = true) and
that date is its ``original_date``.  If the squid is found with a recent date
it was computed in this session (false).  If it is not found at all we cannot
tell (null) and the run is listed under ``to_verify``.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from .study import iso, load_study, parse_dt, save_study, utcnow

CACHE_WINDOW = timedelta(hours=1)


def squid_dates(study: dict) -> dict[str, list[dict]]:
    """Map squid -> list of {date, query_index} occurrences across all queries."""
    found: dict[str, list[dict]] = {}
    for q in study.get("queries", []):
        for row in q.get("rows", []):
            s = row.get("squid")
            if not s:
                continue
            found.setdefault(s, []).append({"date": row.get("date"), "query_index": q.get("index"),
                                            "logged_at": q.get("logged_at")})
    return found


def calibrate_offset(study: dict) -> tuple[timedelta, dict]:
    """Offset to subtract from ResultsDB dates to get UTC.

    Explicit ``resultsdb_utc_offset_hours`` on the study wins; otherwise the
    median difference between query-row dates and the simulator log stamp of the
    same squid, rounded to 15 minutes; otherwise zero."""
    explicit = study.get("resultsdb_utc_offset_hours")
    if explicit is not None:
        return timedelta(hours=float(explicit)), {"source": "study.resultsdb_utc_offset_hours", "samples": 0}
    found = squid_dates(study)
    diffs = []
    for run in study.get("runs", []):
        log_dt = parse_dt(run.get("simulator_log_date"))
        if log_dt is None:
            continue
        for occ in found.get(run.get("squid") or "", []):
            d = parse_dt(occ.get("date"))
            if d is not None:
                diffs.append((d - log_dt).total_seconds())
    if not diffs:
        return timedelta(0), {"source": "none (assumed UTC)", "samples": 0}
    diffs.sort()
    med = diffs[len(diffs) // 2]
    off = round(med / 900.0) * 900.0
    return timedelta(seconds=off), {"source": "calibrated against simulator log stamps", "samples": len(diffs)}


def classify_run(run: dict, occurrences: list[dict] | None, offset: timedelta = timedelta(0)) -> dict:
    """Return {served_from_cache, original_date, evidence} for one run."""
    if not occurrences:
        return {"served_from_cache": None, "original_date": None, "evidence": None}
    requested = parse_dt(run.get("requested_at"))
    dated = [(parse_dt(o.get("date")), o) for o in occurrences]
    dated = [(d - offset, o) for d, o in dated if d is not None]
    if not dated:
        # squid seen but no usable date: we know it exists but not when
        return {"served_from_cache": None, "original_date": None,
                "evidence": {"query_index": occurrences[0].get("query_index"), "date": None}}
    earliest, occ = min(dated, key=lambda t: t[0])
    seen_before = [o for o in occurrences
                   if requested is not None and parse_dt(o.get("logged_at")) is not None
                   and parse_dt(o["logged_at"]) < requested]
    if seen_before:
        pre = seen_before[0]
        return {"served_from_cache": True, "original_date": iso(earliest),
                "evidence": {"query_index": pre.get("query_index"), "date": pre.get("date"),
                             "source": "squid listed by a query logged before the run"}}
    if requested is not None and earliest < requested - CACHE_WINDOW:
        return {"served_from_cache": True, "original_date": iso(earliest),
                "evidence": {"query_index": occ.get("query_index"), "date": occ.get("date")}}
    return {"served_from_cache": False, "original_date": iso(earliest),
            "evidence": {"query_index": occ.get("query_index"), "date": occ.get("date")}}


def original_squids(original: dict | None) -> dict[str, dict]:
    """squid -> run of the study this one re-executes."""
    if not original:
        return {}
    return {r["squid"]: r for r in original.get("runs", []) if r.get("squid")}


def compute_provenance(study: dict, original: dict | None = None) -> dict:
    """Annotate runs in place and return a summary dict (also stored on the study).

    ``original`` is the study this one re-executes (``rerun_of``): a run whose
    squid already appears among the original's runs was served from cache."""
    found = squid_dates(study)
    offset, offset_info = calibrate_offset(study)
    orig = original_squids(original)
    to_verify = []
    for run in study.get("runs", []):
        c = classify_run(run, found.get(run.get("squid") or ""), offset)
        if run.get("squid") in orig:
            o = orig[run["squid"]]
            c = {"served_from_cache": True,
                 "original_date": o.get("original_date") or o.get("requested_at"),
                 "evidence": {"source": "squid present in original study",
                              "original_run_index": o.get("index"),
                              "original_study": original.get("slug") if original else None}}
        if c["served_from_cache"] is None and run.get("simulator_log_date"):
            # second-best evidence: the simulator's own log stamp inside the returned files
            log_dt = parse_dt(run["simulator_log_date"])
            req = parse_dt(run.get("requested_at"))
            if log_dt is not None and req is not None:
                cached = log_dt < req - CACHE_WINDOW
                c = {"served_from_cache": cached, "original_date": iso(log_dt),
                     "evidence": {"source": "simulator_log_date", "date": run["simulator_log_date"]}}
        run["served_from_cache"] = c["served_from_cache"]
        run["original_date"] = c["original_date"]
        run["provenance_evidence"] = c["evidence"]
        if c["served_from_cache"] is None:
            to_verify.append({"index": run.get("index"), "squid": run.get("squid"),
                              "reason": "squid not found in any logged query"
                              if not found.get(run.get("squid") or "")
                              else "squid found but rows carry no parseable date"})
    summary = {
        "computed_at": iso(utcnow()),
        "rerun_of": original.get("slug") if original else None,
        "cache_window_hours": CACHE_WINDOW.total_seconds() / 3600,
        "resultsdb_utc_offset_hours": offset.total_seconds() / 3600,
        "offset_source": offset_info["source"],
        "offset_samples": offset_info["samples"],
        "cached": sum(1 for r in study.get("runs", []) if r.get("served_from_cache") is True),
        "fresh": sum(1 for r in study.get("runs", []) if r.get("served_from_cache") is False),
        "unverified": len(to_verify),
        "to_verify": to_verify,
    }
    study["provenance"] = summary
    return summary


def provenance(d: str | os.PathLike, original_dir: str | os.PathLike | None = None) -> dict:
    study = load_study(d)
    original = None
    src = original_dir or study.get("rerun_of")
    if src:
        p = Path(src)
        if not p.is_absolute() and not (p / "study.json").exists():
            p = Path(d).parent / p  # sibling directory given by slug
        original = load_study(p)
        study["rerun_of"] = study.get("rerun_of") or p.name
    summary = compute_provenance(study, original)
    save_study(d, study)
    return summary
