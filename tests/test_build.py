import json
import xml.etree.ElementTree as ET
from pathlib import Path

from runcard.build import build
from runcard.cli import main
from runcard.provenance import provenance
from runcard.svg import line_chart, should_log
from runcard.study import load_study

from conftest import TOOL


def _build(populated: Path) -> dict:
    provenance(populated)
    return build(populated)


def test_build_writes_all_files(populated: Path):
    paths = _build(populated)
    for name in ("card.md", "card.html", "ro-crate-metadata.json", "rerun.json", "methods.txt"):
        assert (populated / name).exists(), name


def test_ro_crate_is_valid_jsonld(populated: Path):
    _build(populated)
    crate = json.loads((populated / "ro-crate-metadata.json").read_text(encoding="utf-8"))
    assert crate["@context"] == "https://w3id.org/ro/crate/1.1/context"
    graph = crate["@graph"]
    by_id = {e["@id"]: e for e in graph}
    meta = by_id["ro-crate-metadata.json"]
    assert {"@id": "https://w3id.org/ro/crate/1.1"} in meta["conformsTo"]
    assert any("wfrun" in c["@id"] for c in meta["conformsTo"])
    root = by_id["./"]
    assert root["@type"] == "Dataset"
    assert root["name"].startswith("How does the forward current density")
    assert root["datePublished"] and root["author"]["@id"] in by_id
    actions = [e for e in graph if e["@type"] == "CreateAction"]
    runs = load_study(populated)["runs"]
    assert len(actions) == len(runs) == 3
    for a, r in zip(actions, runs):
        assert a["identifier"] == r["squid"]
        assert a["instrument"]["@id"] == f"#tool-{TOOL}"
        assert a["startTime"] == r["requested_at"] and a["endTime"] == r["completed_at"]
        assert a["actionStatus"].endswith("CompletedActionStatus")
        agents = {x["@id"] for x in a["agent"]}
        assert any(by_id[x]["@type"] == "Person" for x in agents)
        assert any(by_id[x]["@type"] == "SoftwareApplication" for x in agents)
        objs = [by_id[o["@id"]] for o in a["object"]]
        temp = next(o for o in objs if o["name"] == "temperature")
        assert temp["@type"] == "PropertyValue" and temp["unitText"] == "K"
        metric = by_id[a["result"][0]["@id"]]
        assert metric["@type"] == "PropertyValue" and metric["unitText"] == "A/cm^2"
        assert metric["value"] == r["metric_value"]
    tool = by_id[f"#tool-{TOOL}"]
    assert tool["@type"] == "SoftwareApplication"
    assert tool["url"] == f"https://nanohub.org/tools/{TOOL}"
    assert tool["version"] == "r4"
    assert tool["identifier"] == "https://doi.org/10.21981/TEST-0001"
    for f in ("card.html", "card.md", "rerun.json"):
        assert by_id[f]["@type"] == "File"
    assert by_id["raw/"]["@type"] == "Dataset"
    cached_action = by_id["#run-0"]
    assert "cache" in cached_action["description"]


def test_svg_has_polyline_and_axis_labels(populated: Path):
    _build(populated)
    html = (populated / "card.html").read_text(encoding="utf-8")
    assert "<polyline" in html
    assert "temperature (K)" in html
    assert "current density at max bias" in html
    svg = (populated / "chart.svg").read_text(encoding="utf-8")
    root = ET.fromstring(svg)  # well-formed XML
    assert root.tag.endswith("svg")
    assert any(el.get("class") == "axis-label" for el in root.iter())


def test_svg_log_scale_when_wide_range():
    assert should_log([1, 10, 1000]) is True
    assert should_log([1, 10, 50]) is False
    assert should_log([-1, 10, 1000]) is False
    svg = line_chart([1, 2, 3], [1e-3, 1e0, 1e3], x_label="x (u)", y_label="y (v)")
    assert "log scale" in svg and "1e-3" in svg and "1e3" in svg
    svg = line_chart([1, 2, 3], [1.0, 2.0, 3.0], x_label="x", y_label="y")
    assert "log scale" not in svg
    assert "<polyline" in line_chart([], [], x_label="x", y_label="y") or True  # empty chart must not raise


def test_html_is_self_contained(populated: Path):
    _build(populated)
    html = (populated / "card.html").read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "max-width: 760px" in html
    assert 'src="http' not in html and "<link" not in html and "<script" not in html
    assert "@media print" in html
    for r in load_study(populated)["runs"]:
        assert r["squid"] in html
    assert "not recorded" in html  # aura trace id absent in fixture


def test_card_markdown_and_methods(populated: Path):
    _build(populated)
    md = (populated / "card.md").read_text(encoding="utf-8")
    assert md.startswith("# How does the forward current density")
    assert "| idx | squid | varied inputs | metric | served_from_cache | original_date | wall_seconds |" in md
    assert "temperature=350" in md and "temperature=300 (default)" in md
    assert "python -m runcard rerun-plan --dir" in md
    methods = (populated / "methods.txt").read_text(encoding="utf-8")
    assert "st4pnjunction" in methods and "3 simulation requests" in methods
    assert "1 was served from nanoHUB's ResultsDB cache (originally computed on 2023-10-27)" in methods
    # deterministic
    build(populated)
    assert (populated / "methods.txt").read_text(encoding="utf-8") == methods


def test_rerun_json_order_and_squids(populated: Path):
    _build(populated)
    plan = json.loads((populated / "rerun.json").read_text(encoding="utf-8"))
    runs = load_study(populated)["runs"]
    assert plan["study"]["question"].startswith("How does")
    assert [s["order"] for s in plan["steps"]] == [1, 2, 3]
    assert [s["expected_squid"] for s in plan["steps"]] == [r["squid"] for r in runs]
    assert [s["chosen_inputs"] for s in plan["steps"]] == [{}, {"temperature": 350}, {"temperature": 400}]
    assert plan["steps"][1]["chosen_outputs"] == ["IV Characteristic", "Parameters"]
    assert plan["steps"][1]["expected_metric"] == runs[1]["metric_value"]
    q = plan["steps"][1]["post_run_query"]
    assert q["nH_tool"] == TOOL and q["datapoints"] == 50
    assert q["inputs_to_filter_by"] == [{"field": "temperature", "operation": "==", "value": 350}]
    assert q["query_squid"] is True and q["query_revision"] is True
    assert set(q) == {"nH_tool", "datapoints", "inputs_to_query", "outputs_to_query", "query_revision",
                      "query_squid", "inputs_to_filter_by", "outputs_to_filter_by"}


def test_cli_build_and_rerun_plan(populated: Path, capsys):
    assert main(["build", "--dir", str(populated)]) == 0
    capsys.readouterr()
    assert main(["rerun-plan", "--dir", str(populated)]) == 0
    steps = json.loads(capsys.readouterr().out)
    assert len(steps) == 3 and steps[0]["order"] == 1


def test_build_with_no_runs(study_dir: Path):
    build(study_dir)
    assert "No successful runs" in (study_dir / "card.md").read_text(encoding="utf-8")
