"""Build the study card (md + html), RO-Crate metadata, rerun plan and methods."""

from __future__ import annotations

import html as _html
import os
from pathlib import Path
from typing import Any

from . import __version__
from .study import (REDUCE_TEXT, fixed_nondefault_inputs, fmt_num, input_units, load_study,
                    normalise_units, run_input_value, varied_inputs, write_json)
from .svg import line_chart

RERUN_FILE = "rerun.json"


# --------------------------------------------------------------------------- helpers

def _run_label(run: dict, varied: list[str], study: dict | None = None) -> str:
    parts = []
    for k in varied:
        v = run_input_value(study or {}, run, k)
        parts.append(f"{k}={fmt_num(v)}" + ("" if k in run.get("chosen_inputs", {}) else " (default)"))
    return ", ".join(parts) if parts else "(all defaults)"


def _dates(runs: list[dict]) -> tuple[str | None, str | None]:
    ts = sorted(r["requested_at"] for r in runs if r.get("requested_at"))
    return (ts[0], ts[-1]) if ts else (None, None)


def _ok_runs(study: dict) -> list[dict]:
    return [r for r in study.get("runs", []) if r.get("status") == "done"]


def _mismatch_note(run: dict) -> str:
    ms = run.get("input_mismatches") or []
    if not ms:
        return ""
    return " (server reported " + "; ".join(f"{m['name']}={fmt_num(m['resolved'])}" for m in ms) + ")"


def _cache_flag(v: Any) -> str:
    return {True: "yes", False: "no"}.get(v, "unknown")


def _tool_rev(study: dict, tool: str) -> str:
    revs = sorted({r["revision"] for r in study.get("runs", []) if r.get("tool") == tool and r.get("revision") is not None})
    return ", ".join(f"r{r}" for r in revs) if revs else "-"


def metric_x_axis(study: dict) -> tuple[str | None, str | None]:
    """Pick the varied input for the chart's x axis (first numeric varied input)."""
    runs = _ok_runs(study)
    for k in varied_inputs(runs):
        if all(isinstance(run_input_value(study, r, k), (int, float)) for r in runs):
            tool = runs[0]["tool"]
            return k, input_units(study, tool, k)
    return None, None


# --------------------------------------------------------------------------- methods

def methods_text(study: dict) -> str:
    runs = study.get("runs", [])
    ok = _ok_runs(study)
    metric = study["metric"]
    tools = study.get("tools", {})
    if not runs:
        return (f"We asked: {study['question']} No simulation runs have been logged yet.")
    tool_names = []
    for t in dict.fromkeys(r["tool"] for r in runs):
        url = tools.get(t, {}).get("url", f"https://nanohub.org/tools/{t}")
        rev = _tool_rev(study, t)
        doi = tools.get(t, {}).get("doi")
        s = f"{t} (revision {rev}, {url}"
        if doi:
            s += f", DOI {doi}"
        s += ")"
        tool_names.append(s)
    varied = varied_inputs(runs)
    fixed = fixed_nondefault_inputs(runs)
    t0 = runs[0]["tool"]
    if varied:
        vparts = []
        for k in varied:
            vals = []
            for r in runs:
                v = run_input_value(study, r, k)
                if v not in vals:
                    vals.append(v)
            u = input_units(study, t0, k)
            vparts.append(f"{k} over {{{', '.join(fmt_num(v) for v in vals)}}}" + (f" {u}" if u else ""))
        varied_s = "varying " + "; ".join(vparts)
    else:
        varied_s = "with no inputs varied between runs"
    if fixed:
        fixed_s = " and holding " + ", ".join(f"{k}={fmt_num(v)}" for k, v in fixed.items()) + " fixed"
    else:
        fixed_s = ""
    outs = []
    for r in runs:
        for o in r.get("chosen_outputs", []):
            if o not in outs:
                outs.append(o)
    cached = [r for r in ok if r.get("served_from_cache") is True]
    fresh = [r for r in ok if r.get("served_from_cache") is False]
    unknown = [r for r in ok if r.get("served_from_cache") is None]
    failed = [r for r in runs if r.get("status") != "done"]
    t_first, t_last = _dates(runs)
    agent = study.get("agent", {})
    paras = [
        f"We asked: {study['question']}",
        f"Using the nanoHUB tool{'s' if len(tool_names) > 1 else ''} {'; '.join(tool_names)} through the "
        f"AURA MCP server, we submitted {len(runs)} simulation request{'s' if len(runs) != 1 else ''} "
        f"{varied_s}{fixed_s}, with all other inputs at their tool defaults. "
        f"For each run we requested the output{'s' if len(outs) != 1 else ''} {', '.join(repr(o) for o in outs)}. "
        f"The reported metric is {metric.get('label')} ({metric.get('unit')}), computed as "
        f"{REDUCE_TEXT.get(metric.get('reduce'), metric.get('reduce'))} of the {metric.get('output')!r} output.",
    ]
    prov = (f"Of the {len(ok)} successful run{'s' if len(ok) != 1 else ''}, {len(cached)} "
            f"{'was' if len(cached) == 1 else 'were'} served from nanoHUB's ResultsDB cache")
    if cached:
        dates = sorted({(r.get("original_date") or "")[:10] for r in cached})
        prov += f" (originally computed on {', '.join(d for d in dates if d)})"
    prov += f", {len(fresh)} {'was' if len(fresh) == 1 else 'were'} computed during this session"
    if unknown:
        prov += f", and {len(unknown)} could not be classified"
    prov += "."
    if failed:
        prov += f" {len(failed)} request{'s' if len(failed) != 1 else ''} failed validation or execution."
    paras.append(prov)
    paras.append(
        f"Requests were submitted between {t_first} and {t_last} by {agent.get('client', 'an agent')} "
        f"({agent.get('model', 'unspecified model')}) on behalf of {study.get('author', 'unknown')}. "
        f"Each run is identified by its ResultsDB squid; the ordered re-execution plan is in rerun.json "
        f"(runcard {__version__})."
    )
    return "\n\n".join(paras)


def summary_text(study: dict) -> str:
    ok = _ok_runs(study)
    metric = study["metric"]
    if not ok:
        return "No successful runs are recorded for this study yet."
    xk, xu = metric_x_axis(study)
    vals = [(run_input_value(study, r, xk) if xk else r["index"], r.get("metric_value")) for r in ok]
    vals = [(x, y) for x, y in vals if y is not None]
    if not vals:
        return f"{len(ok)} successful runs were logged, but the metric {metric.get('output')!r} was not present in their outputs."
    vals.sort(key=lambda t: (t[0] is None, t[0]))
    lo, hi = vals[0], vals[-1]
    ratio = (hi[1] / lo[1]) if lo[1] not in (0, None) and hi[1] is not None else None
    s = (f"Across {len(ok)} runs, {metric.get('label')} goes from {fmt_num(lo[1])} {metric.get('unit')}"
         + (f" at {xk}={fmt_num(lo[0])}{' ' + xu if xu else ''}" if xk else "")
         + f" to {fmt_num(hi[1])} {metric.get('unit')}"
         + (f" at {xk}={fmt_num(hi[0])}{' ' + xu if xu else ''}" if xk else "") + ".")
    if ratio and ratio > 0:
        s += f" That is a factor of {fmt_num(ratio, 3)} over the range."
    cached = sum(1 for r in ok if r.get("served_from_cache") is True)
    fresh = sum(1 for r in ok if r.get("served_from_cache") is False)
    s += f" {cached} result{'s' if cached != 1 else ''} came from nanoHUB's cache and {fresh} {'was' if fresh == 1 else 'were'} computed in this session."
    return s


# --------------------------------------------------------------------------- chart

def chart_svg(study: dict) -> str:
    ok = _ok_runs(study)
    metric = study["metric"]
    xk, xu = metric_x_axis(study)
    if xk:
        xs = [run_input_value(study, r, xk) for r in ok]
        x_label = f"{xk}" + (f" ({xu})" if xu else "")
    else:
        xs = [r["index"] for r in ok]
        x_label = "run index"
    ys = [r.get("metric_value") for r in ok]
    filled = [r.get("served_from_cache") is not False for r in ok]
    pairs = [(x, y, f) for x, y, f in zip(xs, ys, filled) if y is not None and x is not None]
    return line_chart([p[0] for p in pairs], [p[1] for p in pairs], x_label=x_label,
                      y_label=f"{metric.get('label')} ({metric.get('unit')})",
                      title=study["question"], filled=[p[2] for p in pairs])


# --------------------------------------------------------------------------- markdown

def card_markdown(study: dict, d: Path) -> str:
    runs = study.get("runs", [])
    varied = varied_inputs(runs)
    metric = study["metric"]
    tools = study.get("tools", {})
    L: list[str] = []
    L.append(f"# {study['question']}")
    L.append("")
    L.append(summary_text(study))
    L.append("")
    L.append("## Tools")
    L.append("")
    L.append("| name | revision | URL | DOI |")
    L.append("|---|---|---|---|")
    for t in dict.fromkeys(list(tools) + [r["tool"] for r in runs]):
        e = tools.get(t, {})
        L.append(f"| `{t}` | {_tool_rev(study, t)} | {e.get('url', 'https://nanohub.org/tools/' + t)} | {e.get('doi') or 'not known'} |")
    L.append("")
    L.append("## Runs")
    L.append("")
    L.append(f"Metric: {metric.get('label')} ({metric.get('unit')}), "
             f"{REDUCE_TEXT.get(metric.get('reduce'), metric.get('reduce'))} of `{metric.get('output')}`.")
    L.append("")
    L.append("| idx | squid | varied inputs | metric | served_from_cache | original_date | wall_seconds |")
    L.append("|---|---|---|---|---|---|---|")
    for r in runs:
        sq = f"`{r['squid']}`" if r.get("squid") else (f"failed: {r.get('error')}" if r.get("status") != "done" else "-")
        L.append(f"| {r['index']} | {sq} | {_run_label(r, varied, study)}{_mismatch_note(r)} | {fmt_num(r.get('metric_value'))} | "
                 f"{_cache_flag(r.get('served_from_cache'))} | {r.get('original_date') or '-'} | {fmt_num(r.get('wall_seconds'))} |")
    L.append("")
    L.append("## Chart")
    L.append("")
    L.append("![metric vs varied input](chart.svg)")
    L.append("")
    L.append("## Methods")
    L.append("")
    L.append(methods_text(study))
    L.append("")
    L.append("## Provenance")
    L.append("")
    prov = study.get("provenance", {})
    L.append(f"- AURA trace id: `{study.get('aura_trace_id') or 'not recorded'}`")
    L.append(f"- Study created: {study.get('created_at')}")
    t0, t1 = _dates(runs)
    L.append(f"- Runs requested: {t0 or '-'} to {t1 or '-'}")
    L.append(f"- Agent: {study.get('agent', {}).get('client')} ({study.get('agent', {}).get('model')})")
    L.append(f"- Author: {study.get('author')}")
    L.append(f"- Provenance computed: {prov.get('computed_at', 'not yet')}; cached {prov.get('cached', 0)}, "
             f"fresh {prov.get('fresh', 0)}, unverified {prov.get('unverified', 0)}")
    if "resultsdb_utc_offset_hours" in prov:
        L.append(f"- ResultsDB date offset applied: {prov['resultsdb_utc_offset_hours']:+g} h ({prov.get('offset_source')})")
    if study.get("rerun_of"):
        L.append(f"- Re-execution of study `{study['rerun_of']}`; runs whose squid appears there are marked served from cache")
    if prov.get("to_verify"):
        L.append("- To verify (squid not found in any logged query):")
        for tv in prov["to_verify"]:
            L.append(f"  - run {tv['index']}: `{tv.get('squid')}`")
    logd = [r for r in runs if r.get("simulator_log_date")]
    if logd:
        L.append("- Simulator log stamps (from returned files): " + ", ".join(f"run {r['index']}: {r['simulator_log_date']}" for r in logd))
    L.append(f"- Queries logged: {len(study.get('queries', []))}; raw payloads under `raw/`")
    L.append("")
    L.append("## How to re-run")
    L.append("")
    L.append("```")
    L.append(f"python -m runcard rerun-plan --dir {d.as_posix()}")
    L.append("```")
    L.append("")
    L.append("Execute each step through the AURA MCP server in order (see rerun.json), log the results into a "
             "new study directory, then `python -m runcard compare --dir <this> --new-dir <new>`.")
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- html

_CSS = """
:root { color-scheme: light; }
html { background: #fff; }
body { margin: 0 auto; max-width: 760px; padding: 48px 24px 72px; color: #111; background: #fff;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 16px; line-height: 1.55; }
h1 { font-size: 26px; line-height: 1.25; margin: 0 0 20px; font-weight: 650; letter-spacing: -0.01em; }
h2 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.08em; color: #555; margin: 44px 0 12px; font-weight: 600; }
p { margin: 0 0 14px; }
code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; font-size: 0.86em; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 16px; font-size: 14px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #e3e3e3; vertical-align: top; }
td .mono, td.mono { word-break: break-all; }
table { table-layout: auto; }
th { font-weight: 600; color: #333; border-bottom: 1.5px solid #bbb; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
th.num { text-align: right; }
a { color: #0b4f9c; text-decoration: none; }
a:hover { text-decoration: underline; }
figure { margin: 8px 0 16px; }
figure svg { max-width: 100%; height: auto; display: block; }
figcaption { font-size: 13px; color: #555; margin-top: 6px; }
pre { background: #f6f6f6; padding: 12px 14px; overflow-x: auto; border-radius: 4px; }
ul { padding-left: 22px; } li { margin: 4px 0; }
.meta { color: #555; font-size: 14px; }
footer { margin-top: 56px; color: #777; font-size: 13px; border-top: 1px solid #e3e3e3; padding-top: 14px; }
@media print { body { padding: 0; max-width: none; } a { color: #111; } h2 { page-break-after: avoid; }
  table, figure { page-break-inside: avoid; } }
"""


def card_html(study: dict, d: Path, svg: str) -> str:
    e = _html.escape
    runs = study.get("runs", [])
    varied = varied_inputs(runs)
    metric = study["metric"]
    tools = study.get("tools", {})
    prov = study.get("provenance", {})
    t0, t1 = _dates(runs)
    xk, xu = metric_x_axis(study)
    H: list[str] = []
    H.append("<!DOCTYPE html>")
    H.append('<html lang="en"><head><meta charset="utf-8">')
    H.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    H.append(f"<title>{e(study['question'])}</title>")
    H.append(f"<style>{_CSS}</style></head><body>")
    H.append("<main>")
    H.append(f"<h1>{e(study['question'])}</h1>")
    H.append(f'<p class="meta">Study <span class="mono">{e(study.get("slug", d.name))}</span>, created {e(str(study.get("created_at")))}. '
             f'{len(runs)} run{"s" if len(runs) != 1 else ""}, {len(study.get("queries", []))} ResultsDB queries.</p>')
    H.append(f"<p>{e(summary_text(study))}</p>")
    H.append("<h2>Tools</h2>")
    H.append("<table><thead><tr><th>name</th><th>revision</th><th>URL</th><th>DOI</th></tr></thead><tbody>")
    for t in dict.fromkeys(list(tools) + [r["tool"] for r in runs]):
        te = tools.get(t, {})
        url = te.get("url", "https://nanohub.org/tools/" + t)
        doi = te.get("doi")
        doi_html = f'<a href="https://doi.org/{e(doi)}">{e(doi)}</a>' if doi else "not known"
        H.append(f'<tr><td class="mono">{e(t)}</td><td class="mono">{e(_tool_rev(study, t))}</td>'
                 f'<td><a href="{e(url)}">{e(url)}</a></td><td>{doi_html}</td></tr>')
    H.append("</tbody></table>")
    H.append("<h2>Runs</h2>")
    H.append(f"<p>Metric: {e(metric.get('label', ''))} ({e(metric.get('unit', ''))}), "
             f"{e(REDUCE_TEXT.get(metric.get('reduce'), str(metric.get('reduce'))))} of "
             f"<code>{e(metric.get('output', ''))}</code>.</p>")
    H.append("<table><thead><tr><th>idx</th><th>squid</th><th>varied inputs</th>"
             f'<th class="num">metric ({e(metric.get("unit", ""))})</th><th>served from cache</th>'
             '<th>original date</th><th class="num">wall s</th></tr></thead><tbody>')
    for r in runs:
        if r.get("squid"):
            sq = f'<span class="mono">{e(r["squid"])}</span>'
        elif r.get("status") != "done":
            sq = f"failed: {e(str(r.get('error')))}"
        else:
            sq = "-"
        H.append(f'<tr><td>{r["index"]}</td><td>{sq}</td><td>{e(_run_label(r, varied, study))}'
                 f'{("<br><span class=\"meta\">" + e(_mismatch_note(r).strip()) + "</span>") if _mismatch_note(r) else ""}</td>'
                 f'<td class="num">{e(fmt_num(r.get("metric_value")))}</td>'
                 f'<td>{e(_cache_flag(r.get("served_from_cache")))}</td>'
                 f'<td class="mono">{e(r.get("original_date") or "-")}</td>'
                 f'<td class="num">{e(fmt_num(r.get("wall_seconds")))}</td></tr>')
    H.append("</tbody></table>")
    H.append("<h2>Chart</h2>")
    H.append(f"<figure>{svg}<figcaption>{e(metric.get('label', ''))} versus "
             f"{e(xk) if xk else 'run index'}{(' (' + e(xu) + ')') if xu else ''}. "
             "Filled markers were served from nanoHUB's ResultsDB cache; hollow markers were computed in this session."
             "</figcaption></figure>")
    H.append("<h2>Methods</h2>")
    for para in methods_text(study).split("\n\n"):
        H.append(f"<p>{e(para)}</p>")
    H.append("<h2>Provenance</h2><ul>")
    H.append(f'<li>AURA trace id: <span class="mono">{e(str(study.get("aura_trace_id") or "not recorded"))}</span></li>')
    H.append(f"<li>Study created: {e(str(study.get('created_at')))}</li>")
    H.append(f"<li>Runs requested: {e(str(t0 or '-'))} to {e(str(t1 or '-'))}</li>")
    H.append(f"<li>Agent: {e(str(study.get('agent', {}).get('client')))} "
             f"(<span class=\"mono\">{e(str(study.get('agent', {}).get('model')))}</span>)</li>")
    H.append(f"<li>Author: {e(str(study.get('author')))}</li>")
    H.append(f"<li>Provenance computed: {e(str(prov.get('computed_at', 'not yet')))}; "
             f"cached {prov.get('cached', 0)}, fresh {prov.get('fresh', 0)}, unverified {prov.get('unverified', 0)}</li>")
    if "resultsdb_utc_offset_hours" in prov:
        H.append(f"<li>ResultsDB date offset applied: {prov['resultsdb_utc_offset_hours']:+g} h ({e(str(prov.get('offset_source')))})</li>")
    if study.get("rerun_of"):
        H.append(f"<li>Re-execution of study <span class=\"mono\">{e(str(study['rerun_of']))}</span>; "
                 "runs whose squid appears there are marked served from cache</li>")
    if prov.get("to_verify"):
        items = "".join(f'<li>run {tv["index"]}: <span class="mono">{e(str(tv.get("squid")))}</span></li>'
                        for tv in prov["to_verify"])
        H.append(f"<li>To verify (squid not found in any logged query):<ul>{items}</ul></li>")
    logd = [r for r in runs if r.get("simulator_log_date")]
    if logd:
        H.append("<li>Simulator log stamps (from returned files): " + ", ".join(
            f"run {r['index']}: <span class=\"mono\">{e(r['simulator_log_date'])}</span>" for r in logd) + "</li>")
    H.append(f"<li>Raw payloads (inline files stripped) under <span class=\"mono\">raw/</span>; "
             f"machine-readable record in <span class=\"mono\">ro-crate-metadata.json</span></li>")
    H.append("</ul>")
    H.append("<h2>How to re-run</h2>")
    H.append(f"<pre><code>python -m runcard rerun-plan --dir {e(d.as_posix())}</code></pre>")
    H.append("<p>Execute each step through the AURA MCP server in order, log the results into a new study directory, "
             "then compare the two directories with <code>python -m runcard compare</code>.</p>")
    H.append("</main>")
    H.append(f"<footer>Generated by runcard {e(__version__)}. Self-contained file, no external assets.</footer>")
    H.append("</body></html>")
    return "\n".join(H)


# --------------------------------------------------------------------------- rerun plan

def post_run_query(run: dict) -> dict:
    filters = [{"field": k, "operation": "==", "value": v} for k, v in run.get("chosen_inputs", {}).items()]
    return {
        "nH_tool": run["tool"],
        "datapoints": 50,
        "inputs_to_query": list(run.get("chosen_inputs", {}).keys()),
        "outputs_to_query": [],
        "query_revision": True,
        "query_squid": True,
        "inputs_to_filter_by": filters,
        "outputs_to_filter_by": [],
    }


def rerun_plan(study: dict, d: Path) -> dict:
    steps = []
    for i, r in enumerate(study.get("runs", []), start=1):
        steps.append({
            "order": i,
            "tool": r["tool"],
            "execution_tool": study.get("tools", {}).get(r["tool"], {}).get("execution_tool", "run_sim2l"),
            "chosen_inputs": r.get("chosen_inputs", {}),
            "chosen_outputs": r.get("chosen_outputs", []),
            "expected_squid": r.get("squid"),
            "expected_revision": r.get("revision"),
            "expected_metric": r.get("metric_value"),
            "expected_status": r.get("status"),
            "pre_run_query": post_run_query(r),
            "post_run_query": post_run_query(r),
        })
    return {
        "study": {
            "question": study["question"],
            "dir": d.as_posix(),
            "created_at": study.get("created_at"),
            "metric": study["metric"],
            "aura_trace_id": study.get("aura_trace_id"),
        },
        "steps": steps,
    }


# --------------------------------------------------------------------------- RO-Crate

RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.1/context"
RO_CRATE_SPEC = "https://w3id.org/ro/crate/1.1"
PROCESS_RUN_CRATE = "https://w3id.org/ro/wfrun/process/0.1"
WORKFLOW_RUN_CRATE = "https://w3id.org/ro/wfrun/workflow/0.1"


def _pv(id_: str, name: str, value: Any, unit: str | None = None, extra: dict | None = None) -> dict:
    pv = {"@id": id_, "@type": "PropertyValue", "name": name, "value": value}
    if unit:
        pv["unitText"] = unit
    if extra:
        pv.update(extra)
    return pv


def ro_crate(study: dict, d: Path, files: list[str]) -> dict:
    runs = study.get("runs", [])
    tools = study.get("tools", {})
    metric = study["metric"]
    agent = study.get("agent", {})
    author_id = "#author"
    client_id = "#agent-client"
    graph: list[dict] = []

    graph.append({
        "@id": "ro-crate-metadata.json",
        "@type": "CreativeWork",
        "conformsTo": [{"@id": RO_CRATE_SPEC}, {"@id": PROCESS_RUN_CRATE}],
        "about": {"@id": "./"},
    })
    has_part = [{"@id": f} for f in files]
    root = {
        "@id": "./",
        "@type": "Dataset",
        "name": study["question"],
        "description": summary_text(study),
        "datePublished": study.get("created_at"),
        "dateCreated": study.get("created_at"),
        "author": {"@id": author_id},
        "license": {"@id": "https://spdx.org/licenses/MIT"},
        "conformsTo": [{"@id": PROCESS_RUN_CRATE}],
        "hasPart": has_part,
        "mentions": [{"@id": f"#run-{r['index']}"} for r in runs],
        "keywords": ["nanoHUB", "AURA", "simulation", "provenance", "runcard"],
        "identifier": study.get("slug", d.name),
    }
    if study.get("aura_trace_id"):
        root["isBasedOn"] = {"@id": f"#aura-trace-{study['aura_trace_id']}"}
        graph.append({"@id": f"#aura-trace-{study['aura_trace_id']}", "@type": "CreativeWork",
                      "name": "AURA workflow history trace", "identifier": study["aura_trace_id"]})
    graph.append(root)
    graph.append({"@id": author_id, "@type": "Person", "name": study.get("author", "unknown")})
    graph.append({"@id": client_id, "@type": "SoftwareApplication",
                  "name": agent.get("client", "unknown client"),
                  "softwareVersion": agent.get("model", "unspecified"),
                  "description": "LLM agent client that drove the simulation session through the AURA MCP server"})
    graph.append({"@id": "#runcard", "@type": "SoftwareApplication", "name": "runcard",
                  "softwareVersion": __version__, "url": "https://github.com/leitao-dev/runcard"})

    seen_tools = dict.fromkeys(list(tools) + [r["tool"] for r in runs])
    for t in seen_tools:
        te = tools.get(t, {})
        sa = {"@id": f"#tool-{t}", "@type": "SoftwareApplication", "name": t,
              "url": te.get("url", f"https://nanohub.org/tools/{t}"),
              "version": _tool_rev(study, t),
              "description": f"nanoHUB {te.get('tool_kind') or 'simulation'} tool executed via AURA MCP "
                             f"{te.get('execution_tool') or ''}".strip()}
        if te.get("doi"):
            sa["identifier"] = f"https://doi.org/{te['doi']}"
        graph.append(sa)

    for r in runs:
        rid = f"#run-{r['index']}"
        objs = []
        for name, box in (r.get("effective_inputs") or r.get("resolved_inputs") or {}).items():
            pid = f"{rid}-in-{name}"
            extra = {}
            if box.get("min") is not None:
                extra["minValue"] = box["min"]
            if box.get("max") is not None:
                extra["maxValue"] = box["max"]
            if name in r.get("chosen_inputs", {}):
                extra["description"] = "chosen by the client (differs from tool default)"
                if "reported" in box:
                    extra["description"] += f"; the server's simulation_inputs reported {box['reported']!r}"
            graph.append(_pv(pid, name, box.get("value"), normalise_units(box["units"]) if box.get("units") else None, extra))
            objs.append({"@id": pid})
        if not objs:
            for name, v in r.get("chosen_inputs", {}).items():
                pid = f"{rid}-in-{name}"
                graph.append(_pv(pid, name, v, input_units(study, r["tool"], name)))
                objs.append({"@id": pid})
        results = []
        if r.get("metric_value") is not None:
            mid = f"{rid}-metric"
            graph.append(_pv(mid, metric.get("label", "metric"), r["metric_value"], metric.get("unit"),
                             {"description": f"{REDUCE_TEXT.get(metric.get('reduce'), metric.get('reduce'))} of "
                                             f"output {metric.get('output')!r}"}))
            results.append({"@id": mid})
        if r.get("raw_path"):
            results.append({"@id": r["raw_path"]})
        action = {
            "@id": rid,
            "@type": "CreateAction",
            "name": f"run {r['index']}: {r['tool']} {_run_label(r, varied_inputs(runs), study)}",
            "identifier": r.get("squid"),
            "instrument": {"@id": f"#tool-{r['tool']}"},
            "agent": [{"@id": author_id}, {"@id": client_id}],
            "object": objs,
            "result": results,
            "startTime": r.get("requested_at"),
            "endTime": r.get("completed_at"),
            "actionStatus": "http://schema.org/CompletedActionStatus" if r.get("status") == "done"
            else "http://schema.org/FailedActionStatus",
        }
        if r.get("error"):
            action["error"] = r["error"]
        if r.get("served_from_cache") is not None:
            action["description"] = ("Result served from nanoHUB ResultsDB cache (originally computed "
                                     f"{r.get('original_date')})" if r["served_from_cache"]
                                     else "Result computed during this session")
        graph.append(action)
        if r.get("raw_path") and r["raw_path"] not in files:
            graph.append({"@id": r["raw_path"], "@type": "File", "name": f"raw get_job_result payload for run {r['index']}",
                          "encodingFormat": "application/json"})

    file_meta = {
        "card.html": ("Study card (HTML)", "text/html"),
        "card.md": ("Study card (Markdown)", "text/markdown"),
        "rerun.json": ("Ordered re-execution plan", "application/json"),
        "methods.txt": ("Methods paragraph", "text/plain"),
        "chart.svg": ("Metric chart", "image/svg+xml"),
        "study.json": ("Full study record", "application/json"),
        "compare.md": ("Comparison against a rerun", "text/markdown"),
    }
    for f in files:
        if f == "raw/":
            graph.append({"@id": "raw/", "@type": "Dataset", "name": "Raw AURA payloads",
                          "description": "get_job_result and get_data_from_nanohub payloads with inline_files removed "
                                         "and long strings truncated",
                          "hasPart": [{"@id": r["raw_path"]} for r in runs if r.get("raw_path")]
                          + [{"@id": q["csv_path"]} for q in study.get("queries", []) if q.get("csv_path")]})
            for q in study.get("queries", []):
                if q.get("csv_path"):
                    graph.append({"@id": q["csv_path"], "@type": "File", "name": f"ResultsDB query {q['index']}: {q.get('purpose')}",
                                  "encodingFormat": "text/csv"})
        else:
            name, fmt = file_meta.get(f, (f, "application/octet-stream"))
            graph.append({"@id": f, "@type": "File", "name": name, "encodingFormat": fmt})
    return {"@context": RO_CRATE_CONTEXT, "@graph": graph}


# --------------------------------------------------------------------------- entry

def build(d: str | os.PathLike) -> dict[str, str]:
    d = Path(d)
    study = load_study(d)
    svg = chart_svg(study)
    (d / "chart.svg").write_text(svg, encoding="utf-8")
    (d / "card.md").write_text(card_markdown(study, d), encoding="utf-8")
    (d / "card.html").write_text(card_html(study, d, svg), encoding="utf-8")
    (d / "methods.txt").write_text(methods_text(study) + "\n", encoding="utf-8")
    write_json(d / RERUN_FILE, rerun_plan(study, d))
    files = ["card.html", "card.md", "rerun.json", "methods.txt", "chart.svg", "study.json", "raw/"]
    if (d / "compare.md").exists():
        files.append("compare.md")
    write_json(d / "ro-crate-metadata.json", ro_crate(study, d, files))
    return {k: (d / k).as_posix() for k in
            ("card.md", "card.html", "ro-crate-metadata.json", "rerun.json", "methods.txt", "chart.svg")}
