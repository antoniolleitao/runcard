"""Fixtures shaped like the AURA MCP v2.0.0 payloads observed on 2026-10-21."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runcard.study import add_tool, init_study, log_query, log_run

TOOL = "st4pnjunction"

SIM_INPUTS_YAML = """Na:
    value: 2e15
    units: 1 / centimeter ** 3
    min: 1
    max: 2e22
Nd:
    value: 1e15
    units: 1 / centimeter ** 3
    min: 1
    max: 2e22
temperature:
    value: {temperature}
    units: kelvin
    min: 77
    max: 500
vsweep_high:
    value: 0.6
    units: volt
    min: -5
    max: 5
materialp:
    value: Si
impurity:
    value: false
n_node:
    value: 120
    min: 0
    max: 1000
"""

METADATA = {
    "success": True,
    "tool_kind": "sim2l",
    "execution_tool": "run_sim2l",
    "inputs": {
        "Na": {"type": "number", "units": "1 / centimeter ** 3", "min": 1, "max": 2e22, "default": 2e15,
               "description": "Acceptor concentration"},
        "Nd": {"type": "number", "units": "1 / centimeter ** 3", "min": 1, "max": 2e22, "default": 1e15,
               "description": "Donor concentration"},
        "temperature": {"type": "number", "units": "kelvin", "min": 77, "max": 500, "default": 300,
                        "description": "Ambient temperature"},
        "vsweep_high": {"type": "number", "units": "volt", "min": -5, "max": 5, "default": 0.6,
                        "description": "Applied voltage"},
        "materialp": {"type": "string", "default": "Si", "description": "Material"},
    },
    "outputs": {
        "IV Characteristic": {"type": "dict", "description": "voltage -> V, function -> A/cm2"},
        "Parameters": {"type": "string", "description": "Parameters"},
        "Output Log": {"type": "file", "description": "Output Log"},
    },
}


def iv_curve(temperature: float, n: int = 21) -> dict:
    """Synthetic diode curve: J = J0(T) * (exp(V/(k T)) - 1)."""
    import math
    j0 = 1e-12 * (temperature / 300.0) ** 3 * math.exp(-1.12 / (8.617e-5) * (1 / temperature - 1 / 300.0))
    vt = 8.617e-5 * temperature
    volts = [0.6 * i / (n - 1) for i in range(n)]
    return {"voltage": volts, "function": [j0 * (math.exp(v / vt) - 1) for v in volts]}


def result_payload(temperature: float, *, squid_hash: str = "abc123", revision: int = 4,
                   with_inline: bool = False, scale: float = 1.0) -> dict:
    curve = iv_curve(temperature)
    curve["function"] = [v * scale for v in curve["function"]]
    body = {
        "success": True,
        "simulation_summary": [curve, f"Na = 2e15\nNd = 1e15\nT = {temperature} K"],
        "simulation_inputs": SIM_INPUTS_YAML.format(temperature=temperature),
        "simulation_squidID": f"{TOOL}/r{revision}/{squid_hash}",
        "artifacts": [{"name": "Output Log", "path": "~/.AURA/artifacts/log.txt"}],
    }
    if with_inline:
        body["inline_files"] = {"Output Log": {"filename": "Output Log", "encoding": "utf-8",
                                               "content": "\n ********* PADRE2.4E Device Modeling Program *********\n"
                                                          "   Date and time = 10/27/23  09:21:53\n" + "x" * 300_000}}
    return {"status": "done", "result": body}


def failure_payload() -> dict:
    return {"status": "done", "result": {"success": False, "error": "Maximum value is 2e+22"}}


def query_csv(rows: list[tuple[str, int, str, float]]) -> str:
    lines = ["squid,revision,date,input.temperature"]
    for squid, rev, date, temp in rows:
        lines.append(f"{squid},{rev},{date},{temp}")
    return "\n".join(lines) + "\n"


@pytest.fixture
def study_dir(tmp_path: Path) -> Path:
    d = tmp_path / "studies" / "demo"
    init_study(d, "How does the forward current density of a Si p-n junction at 0.6 V change with temperature?",
               model="test-model", author="Tester")
    add_tool(d, METADATA, name=TOOL, doi="10.21981/TEST-0001")
    return d


@pytest.fixture
def populated(study_dir: Path, tmp_path: Path) -> Path:
    """Three runs: 300 K cached (old query date), 350 K fresh (post-run query), 400 K unverified."""
    d = study_dir
    # pre-run query for 300 K finds an old squid
    pre = tmp_path / "pre300.csv"
    pre.write_text(query_csv([(f"{TOOL}/r4/h300", 4, "2023-10-27 10:15:00", 300)]), encoding="utf-8")
    log_query(d, tool=TOOL, filters=[{"field": "temperature", "operation": "==", "value": 300}],
              csv_path=str(pre), purpose="pre-run check 300 K")
    log_run(d, tool=TOOL, chosen_inputs={}, chosen_outputs=["IV Characteristic", "Parameters"],
            requested_at="2026-10-21T14:00:00Z", completed_at="2026-10-21T14:00:12Z",
            result_payload=result_payload(300, squid_hash="h300"))
    log_run(d, tool=TOOL, chosen_inputs={"temperature": 350}, chosen_outputs=["IV Characteristic", "Parameters"],
            requested_at="2026-10-21T14:01:00Z", completed_at="2026-10-21T14:01:13Z",
            result_payload=result_payload(350, squid_hash="h350"))
    post = tmp_path / "post350.csv"
    post.write_text(query_csv([(f"{TOOL}/r4/h350", 4, "2026-10-21 14:01:10", 350)]), encoding="utf-8")
    log_query(d, tool=TOOL, filters=[{"field": "temperature", "operation": "==", "value": 350}],
              csv_path=str(post), purpose="post-run check 350 K")
    log_run(d, tool=TOOL, chosen_inputs={"temperature": 400}, chosen_outputs=["IV Characteristic", "Parameters"],
            requested_at="2026-10-21T14:02:00Z", completed_at="2026-10-21T14:02:11Z",
            result_payload=result_payload(400, squid_hash="h400"))
    return d


def write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
