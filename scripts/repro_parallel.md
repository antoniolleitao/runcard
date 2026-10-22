# Reproduction: mis-routed payloads from concurrent run_sim2l calls

Observed on 2026-10-21 against AURA MCP server v2.0.0 with the st4pnjunction Sim2L (revision r15).
This file describes the exact MCP tool calls. Nothing here runs by itself; issue the calls from an
MCP client (Claude Code, or any client that can send several tool calls in one turn).

Warning: the batch in step 3 consumes hub resources for every point that is not already in
ResultsDB. Use points that already exist if you only want to see the routing defect; the defect was
observed even though three of the four points were computed during the batch.

## 1. Metadata (once)

```
get_tool_metadata(nH_tool="st4pnjunction")
```

Confirms `tool_kind: sim2l`, `execution_tool: run_sim2l`, and the input `temperature`
(number, kelvin, min 77, max 500, default 300).

## 2. Record what ResultsDB holds before the batch

One call per point, all eight parameters required:

```
get_data_from_nanohub(nH_tool="st4pnjunction", datapoints=50,
  inputs_to_query=["temperature","Na","Nd","vsweep_high","materialp"], outputs_to_query=[],
  query_revision=true, query_squid=true,
  inputs_to_filter_by=[{"field":"temperature","operation":"==","value":T},
                       {"field":"Na","operation":"==","value":2e15},
                       {"field":"Nd","operation":"==","value":1e15},
                       {"field":"vsweep_high","operation":"==","value":0.6}],
  outputs_to_filter_by=[])
```

for T in 250, 300, 350, 400. Keep the `data` CSV of each (header `squid,revision,date,...`).

## 3. Submit four runs in the same client turn (this is the trigger)

Send these four calls together, without waiting between them:

```
run_sim2l(nH_tool="st4pnjunction", chosen_inputs={"temperature": 250}, chosen_outputs=["IV Characteristic","Parameters"])
run_sim2l(nH_tool="st4pnjunction", chosen_inputs={},                   chosen_outputs=["IV Characteristic","Parameters"])
run_sim2l(nH_tool="st4pnjunction", chosen_inputs={"temperature": 350}, chosen_outputs=["IV Characteristic","Parameters"])
run_sim2l(nH_tool="st4pnjunction", chosen_inputs={"temperature": 400}, chosen_outputs=["IV Characteristic","Parameters"])
```

Each returns `{"status": "running", "job_id": ...}`. Note the four job ids and the submission time.

## 4. Poll, then fetch each result exactly once

```
get_job_status(job_id=<id>)        # repeat until finished == true, for each id
get_job_result(job_id=<id>)        # once per id
```

## 5. What to compare

For each of the four results look at:

- `result.simulation_squidID`
- `result.simulation_summary[0].function[-1]` (current density at 0.6 V)
- the `Temperature:` line inside `result.simulation_summary[1]` (the `Parameters` output)
- the `Date and time =` line at the top of `result.inline_files["Output Log"].content`

Observed: all four carried the squid `st4pnjunction/r15/92d2225b5b290c6807945331f1d06b6f81ea8951`,
the value 14.2066, the text `Temperature: 300K` and a log stamp of 10/27/23. Only the
`chosen_inputs={}` job should have.

## 6. Show that new ResultsDB rows for the other points appeared during the batch

Repeat the step 2 queries after the batch. New rows for 250, 350 and 400 K appear with dates a few
seconds after the batch (ResultsDB clock, see `docs/evidence-dates.md`). Then submit one of the
points alone:

```
run_sim2l(nH_tool="st4pnjunction", chosen_inputs={"temperature": 250}, chosen_outputs=["IV Characteristic","Parameters"])
```

and fetch it. Observed: squid `st4pnjunction/r15/65bea3dd37eb0eaf511a194b47ed30c55ede70cb`,
value 1.74986196, `Temperature: 250K`, and an Output Log stamped with the batch time
(10/21/26 17:02:19), not the solo submission time.

The payloads from the observed session are in
`studies/si-pn-diode-vs-temperature/raw/anomaly-parallel-submission/` (inline_files removed).
