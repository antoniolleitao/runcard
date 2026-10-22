from pathlib import Path

from runcard.cli import main
from runcard.provenance import classify_run, provenance
from runcard.study import load_study


def test_three_states(populated: Path):
    summary = provenance(populated)
    runs = load_study(populated)["runs"]
    cached, fresh, unknown = runs
    assert cached["served_from_cache"] is True
    assert cached["original_date"] == "2023-10-27T10:15:00Z"
    assert fresh["served_from_cache"] is False
    assert fresh["original_date"] == "2026-10-21T14:01:10Z"
    assert unknown["served_from_cache"] is None
    assert unknown["original_date"] is None
    assert summary["cached"] == 1 and summary["fresh"] == 1 and summary["unverified"] == 1
    assert [t["index"] for t in summary["to_verify"]] == [2]
    assert summary["to_verify"][0]["squid"] == unknown["squid"]


def test_window_boundary():
    run = {"requested_at": "2026-10-21T14:00:00Z", "squid": "t/r1/a"}
    # 59 minutes earlier: recent -> fresh
    c = classify_run(run, [{"date": "2026-10-21T13:01:00Z", "query_index": 0}])
    assert c["served_from_cache"] is False
    # 61 minutes earlier: cached
    c = classify_run(run, [{"date": "2026-10-21T12:59:00Z", "query_index": 0}])
    assert c["served_from_cache"] is True and c["original_date"] == "2026-10-21T12:59:00Z"
    # found both pre and post: earliest wins
    c = classify_run(run, [{"date": "2026-10-21T14:00:30Z", "query_index": 1},
                           {"date": "2024-01-01T00:00:00Z", "query_index": 0}])
    assert c["served_from_cache"] is True and c["original_date"] == "2024-01-01T00:00:00Z"
    # no occurrences
    assert classify_run(run, None)["served_from_cache"] is None
    # occurrence without a date
    assert classify_run(run, [{"date": "", "query_index": 0}])["served_from_cache"] is None


def test_cli_provenance(populated: Path, capsys):
    assert main(["provenance", "--dir", str(populated)]) == 0
    out = capsys.readouterr().out
    assert '"served_from_cache": true' in out and '"served_from_cache": null' in out


def test_simulator_log_date_fallback(study_dir: Path):
    from runcard.study import log_run
    from conftest import TOOL, result_payload
    # no query logged, but the returned Output Log is stamped three years ago -> cached
    log_run(study_dir, tool=TOOL, chosen_inputs={}, chosen_outputs=["IV Characteristic", "Parameters"],
            requested_at="2026-10-21T14:00:00Z", result_payload=result_payload(300, with_inline=True))
    summary = provenance(study_dir)
    run = load_study(study_dir)["runs"][0]
    assert run["served_from_cache"] is True
    assert run["original_date"] == "2023-10-27T09:21:53Z"
    assert run["provenance_evidence"]["source"] == "simulator_log_date"
    assert summary["unverified"] == 0


def test_resultsdb_offset_calibration(study_dir: Path, tmp_path: Path):
    """ResultsDB dates were observed 7 h behind UTC: a fresh run's row must not look cached."""
    from runcard.study import log_query, log_run
    from conftest import TOOL, query_csv, result_payload
    payload = result_payload(350, squid_hash="fresh", with_inline=True)
    payload["result"]["inline_files"]["Output Log"]["content"] = "Date and time = 10/21/26  17:02:21\n"
    log_run(study_dir, tool=TOOL, chosen_inputs={"temperature": 350}, chosen_outputs=["IV Characteristic", "Parameters"],
            requested_at="2026-10-21T17:05:38Z", completed_at="2026-10-21T17:05:51Z", result_payload=payload)
    csv_path = tmp_path / "post.csv"
    csv_path.write_text(query_csv([(f"{TOOL}/r4/fresh", 4, "2026-10-21 10:02:38.369293", 350)]), encoding="utf-8")
    log_query(study_dir, tool=TOOL, filters=[], csv_path=str(csv_path), purpose="post-run")
    summary = provenance(study_dir)
    run = load_study(study_dir)["runs"][0]
    assert summary["resultsdb_utc_offset_hours"] == -7.0
    assert summary["offset_samples"] == 1
    assert run["served_from_cache"] is False
    assert run["original_date"] == "2026-10-21T17:02:38Z"
    # explicit override wins
    st = load_study(study_dir)
    st["resultsdb_utc_offset_hours"] = 0
    from runcard.study import save_study
    save_study(study_dir, st)
    summary = provenance(study_dir)
    assert summary["offset_source"].startswith("study.")
    assert load_study(study_dir)["runs"][0]["served_from_cache"] is True  # naive reading looks cached


def test_pre_run_query_listing_is_proof_of_cache():
    """A squid already listed by a query logged before the run is cached even if recent."""
    run = {"requested_at": "2026-10-21T17:12:32Z", "squid": "t/r1/a"}
    occ = [{"date": "2026-10-21T17:02:33Z", "query_index": 0, "logged_at": "2026-10-21T17:12:30Z"}]
    c = classify_run(run, occ)
    assert c["served_from_cache"] is True and c["original_date"] == "2026-10-21T17:02:33Z"
    # the same row seen only by a post-run query stays "fresh"
    occ = [{"date": "2026-10-21T17:02:33Z", "query_index": 1, "logged_at": "2026-10-21T17:13:00Z"}]
    assert classify_run(run, occ)["served_from_cache"] is False


def test_rerun_squid_present_in_original_study(tmp_path: Path):
    """A rerun run whose squid is among the original study's runs is cached, whatever the dates say."""
    from runcard.cli import main
    from runcard.study import add_tool, init_study, log_run
    from conftest import METADATA, TOOL, result_payload
    orig = tmp_path / "orig"
    init_study(orig, "q?"); add_tool(orig, METADATA, name=TOOL)
    log_run(orig, tool=TOOL, chosen_inputs={"temperature": 350}, chosen_outputs=["IV Characteristic"],
            requested_at="2026-10-21T17:05:38Z", completed_at="2026-10-21T17:05:51Z",
            result_payload=result_payload(350, squid_hash="same"))
    provenance(orig)
    rerun = tmp_path / "orig-rerun"
    init_study(rerun, "q?"); add_tool(rerun, METADATA, name=TOOL)
    log_run(rerun, tool=TOOL, chosen_inputs={"temperature": 350}, chosen_outputs=["IV Characteristic"],
            requested_at="2026-10-21T17:13:28Z", completed_at="2026-10-21T17:13:40Z",
            result_payload=result_payload(350, squid_hash="same"))
    log_run(rerun, tool=TOOL, chosen_inputs={"temperature": 360}, chosen_outputs=["IV Characteristic"],
            requested_at="2026-10-21T17:14:00Z", result_payload=result_payload(360, squid_hash="new"))
    # without the link: unverified (no queries logged)
    assert provenance(rerun)["unverified"] == 2
    assert main(["set", "--dir", str(rerun), "--rerun-of", "orig"]) == 0   # sibling slug
    summary = provenance(rerun)
    runs = load_study(rerun)["runs"]
    assert summary["rerun_of"] == "orig"
    assert runs[0]["served_from_cache"] is True
    assert runs[0]["provenance_evidence"]["source"] == "squid present in original study"
    assert runs[0]["provenance_evidence"]["original_run_index"] == 0
    assert runs[0]["original_date"] == "2026-10-21T17:05:38Z"  # original's requested_at (it had no query evidence)
    assert runs[1]["served_from_cache"] is None
    assert summary["cached"] == 1 and summary["unverified"] == 1
