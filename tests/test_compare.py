from pathlib import Path

from runcard.cli import main
from runcard.compare import compare
from runcard.study import add_tool, init_study, log_run

from conftest import METADATA, TOOL, result_payload


def _study(tmp_path: Path, name: str, specs: list[tuple[float, str, int, float]]) -> Path:
    d = tmp_path / name
    init_study(d, "q?", model="m")
    add_tool(d, METADATA, name=TOOL)
    for i, (temp, h, rev, scale) in enumerate(specs):
        log_run(d, tool=TOOL, chosen_inputs={"temperature": temp} if temp != 300 else {},
                chosen_outputs=["IV Characteristic", "Parameters"],
                requested_at=f"2026-10-21T14:0{i}:00Z", completed_at=f"2026-10-21T14:0{i}:12Z",
                result_payload=result_payload(temp, squid_hash=h, revision=rev, scale=scale))
    return d


def test_compare_verdicts(tmp_path: Path):
    old = _study(tmp_path, "old", [(300, "h300", 4, 1.0), (350, "h350", 4, 1.0), (400, "h400", 4, 1.0), (450, "h450", 4, 1.0)])
    new = _study(tmp_path, "new", [
        (300, "h300", 4, 1.0),     # same squid -> reproduced from cache
        (350, "h350b", 5, 1.0),    # same inputs, new revision, same values
        (400, "h400b", 5, 1.02),   # same inputs, new revision, metric drift 2 %
    ])
    s = compare(old, new)
    rows = {r["index"]: r for r in s["rows"]}
    assert rows[0]["verdict"] == "reproduced from cache" and rows[0]["metric_drift"] is False
    assert rows[1]["verdict"] == "tool revision changed" and rows[1]["metric_drift"] is False
    assert rows[1]["old_revision"] == 4 and rows[1]["new_revision"] == 5
    assert rows[2]["verdict"] == "tool revision changed" and rows[2]["metric_drift"] is True
    assert abs(rows[2]["metric_rel_diff"] - 0.02 / 1.02) < 1e-9
    assert rows[2]["series"]["max_rel_diff"] > 0.01
    assert rows[3]["verdict"] == "missing"
    assert s["reproduced_from_cache"] == 1 and s["revision_changed"] == 2 and s["metric_drift"] == 1 and s["missing"] == 1
    md = (old / "compare.md").read_text(encoding="utf-8")
    assert (new / "compare.md").exists()
    assert "reproduced from cache" in md and "tool revision changed" in md and "missing" in md
    assert f"{TOOL}/r5/h400b" in md


def test_compare_inputs_differ(tmp_path: Path):
    old = _study(tmp_path, "old", [(350, "h350", 4, 1.0)])
    new = _study(tmp_path, "new", [(350, "h351", 4, 1.0)])
    # tamper with resolved inputs so signatures differ despite identical chosen inputs
    from runcard.study import load_study, save_study
    st = load_study(new)
    st["runs"][0]["effective_inputs"]["Na"]["value"] = 3e15
    save_study(new, st)
    s = compare(old, new)
    assert s["rows"][0]["verdict"] == "inputs differ"


def test_cli_compare(tmp_path: Path, capsys):
    old = _study(tmp_path, "old", [(300, "h300", 4, 1.0)])
    new = _study(tmp_path, "new", [(300, "h300", 4, 1.0)])
    assert main(["compare", "--dir", str(old), "--new-dir", str(new)]) == 0
    assert "reproduced from cache" in capsys.readouterr().out


def test_compare_uses_chosen_values_when_server_reports_defaults(tmp_path: Path):
    """AURA's YAML lists defaults, so two runs at different chosen temperatures must not look identical."""
    from runcard.study import load_study, save_study
    old = _study(tmp_path, "old", [(350, "h350", 4, 1.0)])
    new = _study(tmp_path, "new", [(350, "h351", 4, 1.0)])
    for d in (old, new):
        st = load_study(d)
        st["runs"][0]["resolved_inputs"]["temperature"]["value"] = 300  # server reported the default
        save_study(d, st)
    s = compare(old, new)
    assert s["rows"][0]["verdict"] == "recomputed with same inputs"
    st = load_study(new)
    st["runs"][0]["chosen_inputs"] = {"temperature": 360}
    st["runs"][0]["effective_inputs"]["temperature"]["value"] = 360
    save_study(new, st)
    s = compare(old, new)
    assert s["rows"][0]["verdict"] == "missing"  # pairing is by chosen inputs
