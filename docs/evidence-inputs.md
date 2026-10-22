# Evidence: `simulation_inputs` reports the tool defaults, not the resolved inputs

AURA MCP server v2.0.0, st4pnjunction r15, 2026-10-21. The run used here is the solo 250 K run,
job `788e8f2e-1fdf-4ae4-ab7b-33403bd50f71`, submitted with
`chosen_inputs {"temperature": 250}`, squid
`st4pnjunction/r15/65bea3dd37eb0eaf511a194b47ed30c55ede70cb`.

## The three sources, side by side

| source | where it is | temperature |
|---|---|---|
| `result.simulation_inputs` (YAML string) | `studies/si-pn-diode-vs-temperature/raw/run-01-st4pnjunction.json` | `value: 300` |
| `result.simulation_summary[1]` (the `Parameters` output) | same file | `Temperature: 250K` |
| `result.inline_files["Padre Input Deck"].content` | **not in the study's raw folder** (runcard strips `inline_files`); taken from the session transcript copy of the same payload, see below | `temperature=250` |

### 1. `simulation_inputs`, temperature block, verbatim

Excerpt file: `docs/excerpts/run-250K-simulation_inputs-temperature-block.txt`

```
temperature:
    type: Number
    description: This is the temperature in the environment around the device.
    units: kelvin
    max: 500.0
    min: 77.0
    value: 300
```

### 2. `Parameters` output, verbatim

Excerpt file: `docs/excerpts/run-250K-parameters-output.txt`

```
== STRUCTURE ==
  P-region:  3 um (60 nodes) at 2000000000000000.0/cm3
  I-region:  0um (0 nodes)
  N-region:  6 um (120 nodes) at 1000000000000000.0/cm3

== MATERIALS ==
  Material: silicon
  taun = 1e-10s
  taup = 1e-10s

== ENVIRONMENT ==
  Temperature: 250K
  V bias: 0.6 V (20 points)
```

### 3. PADRE input deck, temperature line

The study's raw payload does not contain this line because `log-run` removes `inline_files`
before persisting. The line below was read from the full payload that the MCP client saved to
disk when the response exceeded its context limit (file
`mcp-claude_ai_nanoHUB-get_job_result-1792602329781.txt`, 255,868 characters, job id
`788e8f2e-...` inside it). The excerpt was extracted mechanically and is kept in
`docs/excerpts/run-250K-job-788e8f2e-inline-files.txt`.

```
deck line 40: models srh conmob fldmob impact temperature=250
```

The Output Log in the same payload repeats it (`log line 48: 25... models srh conmob fldmob impact
temperature=250`) and is stamped `Date and time = 10/21/26  17:02:19`.

## Same pattern in every payload of the session

For all 13 `get_job_result` payloads fetched on 2026-10-21 (5 study runs, 5 rerun runs, 3
mis-routed batch results) the `simulation_inputs` temperature value is `300`, while the
`Parameters` text follows the submitted value:

| job (first 8) | chosen temperature | `simulation_inputs` value | `Parameters` line |
|---|---|---|---|
| ffc7acc2 | default | 300 | Temperature: 300K |
| 53d49b6b | 250 (mis-routed) | 300 | Temperature: 300K |
| ce44d418 | 350 (mis-routed) | 300 | Temperature: 300K |
| 8386fe3b | 400 (mis-routed) | 300 | Temperature: 300K |
| 788e8f2e | 250 | 300 | Temperature: 250K |
| 7bf74c5a | 350 | 300 | Temperature: 350K |
| 63ca4d26 | 400 | 300 | Temperature: 400K |
| da1f4efe | 450 | 300 | Temperature: 450K |
| 3e32e354 | 250 (rerun) | 300 | Temperature: 250K |
| 1430d4c8 | default (rerun) | 300 | Temperature: 300K |
| b50b0df3 | 350 (rerun) | 300 | Temperature: 350K |
| 211708a1 | 400 (rerun) | 300 | Temperature: 400K |
| d3e053a2 | 450 (rerun) | 300 | Temperature: 450K |

## What is proven and what is inferred

Proven: for a run that the simulator itself reports as 250 K (Parameters output and PADRE deck),
`simulation_inputs` says 300, which is the `default` that `get_tool_metadata` lists for
`temperature`. The same holds for every non-default run of the session.

Inferred: `simulation_inputs` is rendered from the tool's input declarations rather than from the
values that were submitted. Only `temperature` was varied, so it is not proven that every input
behaves this way, but no payload showed a non-default value in that string.

Effect on runcard: `log-run` keeps the server string as `resolved_inputs`, records the chosen value
as `effective_inputs` with the server's figure under `reported`, and the card and RO-Crate say so
per run.
