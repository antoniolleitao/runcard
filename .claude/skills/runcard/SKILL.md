---
name: runcard
description: Record every nanoHUB AURA MCP simulation session as a structured, verifiable, re-executable study (study.json, card.html, RO-Crate, rerun.json). Use whenever the user asks to run, sweep, reproduce or compare nanoHUB simulations through the AURA MCP server, or says "runcard", "study card", "rerun" or "provenance".
---

# runcard: study records for AURA MCP sessions

Every simulation session ends with a study directory the user can read (card.html), a machine can
verify (ro-crate-metadata.json, study.json) and an agent can re-execute (rerun.json). The CLI is
stdlib Python: `python -m runcard <cmd>` from the repository root. All raw AURA payloads are kept
under `studies/<slug>/raw/` with `inline_files` removed.

Hard rules, in priority order:

1. Never queue a simulation that is not already in ResultsDB without the user's explicit approval,
   naming the tool and the exact inputs. Never have more than 5 unapproved runs pending.
2. Never put file-type outputs ("Output Log", "Padre Input Deck", any output whose metadata type is
   `file`) in `chosen_outputs`.
3. If any response contains `inline_files`, never print it. Drop the key before writing the payload.
   `log-run` strips it again and warns, but do not rely on that for what you print to the user.
4. Call `get_job_result` exactly once per job, only after `get_job_status` reports `finished: true`.
5. Do not use `find_novel_datapoints` (it returns output that violates its own schema). Use
   `get_data_from_nanohub` with exact-match filters instead.

## Procedure

Use `$STUDY` for `studies/<slug>` and `$TMP` for a scratch directory outside the repo.

### (a) init

```
python -m runcard init "<question>" --dir studies/<slug> --model <your model id> --author "<user name>"
```

`<slug>` is short kebab-case derived from the question. The default metric is the last value of the
`IV Characteristic` function (current density at the highest bias, A/cm^2); pass `--metric metric.json`
to change `{"output","reduce","unit","label"}` when the study is about another quantity
(`reduce` is one of last_of_function, first_of_function, max_of_function, min_of_function,
mean_of_function, scalar).

### (b) tool discovery and snapshot

1. `search_nanohub_tools(keywords=[...], limit=5, workflow_label="<question>")` once (first call may take ~60 s).
2. `get_tool_metadata(nH_tool=<name>)` once. Write the full response to `$STUDY/raw/metadata-<name>.json`.
3. DOI: `WebFetch https://nanohub.org/resources/<name>/about` and read the `citation_doi` meta tag or a
   "DOI:" line. If none is found, use `null` (omit `--doi`).
4. `python -m runcard add-tool --dir $STUDY --metadata $STUDY/raw/metadata-<name>.json --tool <name> [--doi <doi>]`
5. `get_aura_dashboard_state(trace_id="latest")` and store `selected_trace_id`:
   `python -m runcard set --dir $STUDY --aura-trace-id <id>`. Repeat at the end of the session in case
   the trace changed.

### (c) BEFORE each run: the cache check and approval gate

For the point you are about to simulate, with `chosen_inputs` = only the values that differ from
defaults:

```
get_data_from_nanohub(nH_tool=<name>, datapoints=50,
  inputs_to_query=[<keys of chosen_inputs>], outputs_to_query=[],
  query_revision=true, query_squid=true,
  inputs_to_filter_by=[{"field": k, "operation": "==", "value": v} for each chosen input],
  outputs_to_filter_by=[])
```

If `chosen_inputs` is empty (all defaults) filter on one default value instead, for example
`temperature == 300`, so the query is not empty. Save the `data` CSV text to `$TMP/pre-<i>.csv`
and the filters to `$TMP/pre-<i>-filters.json`, then:

```
python -m runcard log-query --dir $STUDY --tool <name> --filters $TMP/pre-<i>-filters.json --csv $TMP/pre-<i>.csv --purpose "pre-run check <inputs>"
```

- Rows exist: tell the user "this point exists, result will come from cache (first run <earliest date>)"
  and proceed to (d) without asking.
- No rows: STOP. Ask for explicit approval with the tool name and the full `chosen_inputs`. Do not
  submit until the user says yes. You may list up to 5 points in one approval request; never more.

### (d) run, poll, fetch once, log

1. Note `requested_at` (UTC ISO 8601) immediately before calling
   `run_sim2l(nH_tool, chosen_inputs, chosen_outputs)` (or `run_rappture_tool` when the metadata
   says so). Keep the `job_id`.
2. Poll `get_job_status(job_id)` until `finished == true` (a st4pnjunction run takes ~12 s).
3. Call `get_job_result(job_id)` once. Note `completed_at`.
4. Drop `inline_files` if present and write the payload to `$STUDY/raw/job-<i>.json`. Write
   `chosen_inputs` and `chosen_outputs` to `$TMP/ci-<i>.json` and `$TMP/co-<i>.json`.
5. ```
   python -m runcard log-run --dir $STUDY --tool <name> --chosen-inputs $TMP/ci-<i>.json \
     --chosen-outputs $TMP/co-<i>.json --requested-at <requested_at> --completed-at <completed_at> \
     --result $STUDY/raw/job-<i>.json
   ```
   The command prints the squid, revision and metric value. On `success: false` it records the error
   and exits 3; report the error to the user and do not retry with the same inputs.

### (e) AFTER each run: query again so provenance can find the new squid

Repeat the exact-match query from (c) with `datapoints=50`, save the CSV to `$TMP/post-<i>.csv`, and

```
python -m runcard log-query --dir $STUDY --tool <name> --filters $TMP/post-<i>-filters.json --csv $TMP/post-<i>.csv --purpose "post-run check <inputs>"
```

The run's squid must appear in the rows; if it does not, say so (the run will be listed under
"to verify").

### (f) provenance and card

```
python -m runcard set --dir $STUDY --aura-trace-id <selected_trace_id from get_aura_dashboard_state>
python -m runcard provenance --dir $STUDY
python -m runcard build --dir $STUDY
```

Show the user the path to `card.html` and the runs table (idx, squid, varied inputs, metric,
served_from_cache, original_date, wall_seconds) from `card.md`. Mention any run under "to verify".

### (g) rerun

When the user says "rerun" (or asks to reproduce / verify the study):

1. `python -m runcard rerun-plan --dir $STUDY` prints the ordered steps.
2. `python -m runcard init "<same question>" --dir studies/<slug>-rerun ...`,
   `python -m runcard set --dir studies/<slug>-rerun --rerun-of <slug>` (so provenance marks every
   squid already present in the original study as served from cache), `add-tool` again from the
   saved metadata, then execute each step in order exactly as in (c), (d), (e): pre-run query
   (now expected to find the point), run, fetch once, log-run, post-run query. Submit one run at a
   time: concurrent `run_sim2l` calls were observed to return each other's payloads.
3. `provenance`, `build`, then
   `python -m runcard compare --dir $STUDY --new-dir studies/<slug>-rerun`
   and show `compare.md`. Same squid means nanoHUB served the stored result; a different squid with
   identical resolved inputs means the tool revision changed; the relative difference column shows
   metric drift.

## Payload notes (AURA MCP v2.0.0)

- `get_job_result` success body: `success`, `simulation_summary` (one entry per chosen output, same
  order), `simulation_inputs` (YAML string listing every input with value/units/min/max),
  `simulation_squidID` (`tool/rN/<hash>`), `artifacts`, sometimes `inline_files`.
  Validation failure: `{"success": false, "error": "..."}`.
- `get_data_from_nanohub` returns `data` as CSV text with header `squid,revision,date,input.<field>,...`.
  All eight parameters are required; pass `[]` for empty lists and booleans for
  `query_revision`/`query_squid`.
- A result served from the cache looks identical to a fresh one. Only the pre-run query's `date`
  column tells you when it was first computed, which is why (c) and (e) are mandatory.
