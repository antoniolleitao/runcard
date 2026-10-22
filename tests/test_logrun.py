import json
from pathlib import Path

import pytest

from runcard.cli import main
from runcard.study import ARRAY_CAP, load_study, log_run

from conftest import TOOL, failure_payload, result_payload, write_json


def test_log_run_strips_inline_files(study_dir: Path, capsys):
    payload = result_payload(300, with_inline=True)
    run = log_run(study_dir, tool=TOOL, chosen_inputs={}, chosen_outputs=["IV Characteristic", "Parameters"],
                  requested_at="2026-10-21T14:00:00Z", completed_at="2026-10-21T14:00:12Z", result_payload=payload)
    assert run["inline_attachments_stripped"] is True
    assert "inline_files" in capsys.readouterr().err
    raw = json.loads((study_dir / run["raw_path"]).read_text(encoding="utf-8"))
    assert "inline_files" not in json.dumps(raw)
    assert "inline_files" not in (study_dir / "study.json").read_text(encoding="utf-8")
    assert (study_dir / run["raw_path"]).stat().st_size < 50_000


def test_log_run_rewrites_callers_file_inside_study_dir(study_dir: Path):
    raw = study_dir / "raw" / "job.json"
    write_json(raw, result_payload(300, with_inline=True))
    log_run(study_dir, tool=TOOL, chosen_inputs={}, chosen_outputs=["IV Characteristic", "Parameters"],
            requested_at="2026-10-21T14:00:00Z", result_payload=json.loads(raw.read_text()), result_path=str(raw))
    assert "inline_files" not in raw.read_text(encoding="utf-8")


def test_log_run_fields(study_dir: Path):
    run = log_run(study_dir, tool=TOOL, chosen_inputs={"temperature": 350},
                  chosen_outputs=["IV Characteristic", "Parameters"],
                  requested_at="2026-10-21T14:01:00Z", completed_at="2026-10-21T14:01:13Z",
                  result_payload=result_payload(350, squid_hash="deadbeef", revision=7))
    assert run["squid"] == f"{TOOL}/r7/deadbeef"
    assert run["revision"] == 7
    assert run["status"] == "done" and run["error"] is None
    assert run["wall_seconds"] == 13.0
    assert run["resolved_inputs"]["temperature"] == {"value": 350, "units": "kelvin", "min": 77, "max": 500}
    assert run["resolved_inputs"]["Na"]["value"] == 2e15
    assert set(run["outputs"]) == {"IV Characteristic", "Parameters"}
    assert run["outputs"]["IV Characteristic"]["function"][-1] == run["metric_value"]
    assert run["served_from_cache"] is None
    study = load_study(study_dir)
    assert study["runs"][0]["index"] == 0


def test_log_run_caps_arrays_and_strings(study_dir: Path):
    payload = result_payload(300)
    big = list(range(5000))
    payload["result"]["simulation_summary"][0] = {"voltage": big, "function": [float(x) for x in big]}
    payload["result"]["simulation_summary"][1] = "p" * 10_000
    run = log_run(study_dir, tool=TOOL, chosen_inputs={}, chosen_outputs=["IV Characteristic", "Parameters"],
                  requested_at="2026-10-21T14:00:00Z", result_payload=payload)
    f = run["outputs"]["IV Characteristic"]["function"]
    assert f["_capped"] and f["original_length"] == 5000 and len(f["values"]) == ARRAY_CAP
    assert f["values"][0] == 0 and f["values"][-1] == 4999
    assert run["metric_value"] == 4999.0  # computed before capping
    assert len(run["outputs"]["Parameters"]) < 2_200 and "truncated" in run["outputs"]["Parameters"]


def test_log_run_failure(study_dir: Path):
    run = log_run(study_dir, tool=TOOL, chosen_inputs={"Na": 5e22}, chosen_outputs=["IV Characteristic"],
                  requested_at="2026-10-21T14:00:00Z", result_payload=failure_payload())
    assert run["status"] == "failed"
    assert run["error"] == "Maximum value is 2e+22"
    assert run["squid"] is None and run["metric_value"] is None


def test_cli_roundtrip(tmp_path: Path, capsys):
    d = tmp_path / "s"
    assert main(["init", "q?", "--dir", str(d), "--model", "m"]) == 0
    meta = write_json(tmp_path / "meta.json", {"inputs": {}, "outputs": {}, "tool_kind": "sim2l", "execution_tool": "run_sim2l"})
    assert main(["add-tool", "--dir", str(d), "--metadata", str(meta), "--tool", TOOL, "--doi", "10.1/x"]) == 0
    ci = write_json(tmp_path / "ci.json", {"temperature": 350})
    co = write_json(tmp_path / "co.json", ["IV Characteristic", "Parameters"])
    res = write_json(tmp_path / "res.json", result_payload(350, with_inline=True))
    assert main(["log-run", "--dir", str(d), "--tool", TOOL, "--chosen-inputs", str(ci), "--chosen-outputs", str(co),
                 "--requested-at", "2026-10-21T14:01:00Z", "--result", str(res)]) == 0
    out = capsys.readouterr()
    assert "inline_files" in out.err
    assert "inline_attachments_stripped" in out.out
    study = load_study(d)
    assert study["tools"][TOOL]["doi"] == "10.1/x"
    assert study["tools"][TOOL]["url"] == f"https://nanohub.org/tools/{TOOL}"
    assert len(study["runs"]) == 1
    assert main(["set", "--dir", str(d), "--aura-trace-id", "trace-xyz"]) == 0
    assert load_study(d)["aura_trace_id"] == "trace-xyz"


def test_init_refuses_overwrite(tmp_path: Path):
    d = tmp_path / "s"
    assert main(["init", "q?", "--dir", str(d)]) == 0
    assert main(["init", "q?", "--dir", str(d)]) == 2


def test_log_run_flags_chosen_vs_resolved_mismatch(study_dir: Path, capsys):
    # server returns the 300 K result although 250 K was requested (observed with parallel run_sim2l calls)
    run = log_run(study_dir, tool=TOOL, chosen_inputs={"temperature": 250}, chosen_outputs=["IV Characteristic"],
                  requested_at="2026-10-21T14:00:00Z", result_payload=result_payload(300))
    assert run["input_mismatches"] == [{"name": "temperature", "chosen": 250, "resolved": 300}]
    assert "reports 300" in capsys.readouterr().err
    # the chosen value wins; the server's figure is kept as "reported"
    assert run["effective_inputs"]["temperature"]["value"] == 250
    assert run["effective_inputs"]["temperature"]["reported"] == 300
    assert run["effective_inputs"]["temperature"]["units"] == "kelvin"
    assert run["effective_inputs"]["Na"]["value"] == 2e15 and "reported" not in run["effective_inputs"]["Na"]
    ok = log_run(study_dir, tool=TOOL, chosen_inputs={"temperature": 350.0, "materialp": "Si"},
                 chosen_outputs=["IV Characteristic"], requested_at="2026-10-21T14:00:00Z",
                 result_payload=result_payload(350))
    assert ok["input_mismatches"] == []


def test_log_run_extracts_simulator_log_date(study_dir: Path):
    run = log_run(study_dir, tool=TOOL, chosen_inputs={}, chosen_outputs=["IV Characteristic", "Parameters"],
                  requested_at="2026-10-21T14:00:00Z", result_payload=result_payload(300, with_inline=True))
    assert run["simulator_log_date"] == "2023-10-27T09:21:53Z"
    run2 = log_run(study_dir, tool=TOOL, chosen_inputs={}, chosen_outputs=["IV Characteristic", "Parameters"],
                   requested_at="2026-10-21T14:00:00Z", result_payload=result_payload(300))
    assert run2["simulator_log_date"] is None
