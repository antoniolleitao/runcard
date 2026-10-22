# Evidence: concurrent run_sim2l calls returned mis-routed payloads

AURA MCP server v2.0.0, tool st4pnjunction r15, session of 2026-10-21, nanoHUB account <redacted>.
All times UTC unless marked "ResultsDB clock" (see `evidence-dates.md`: ResultsDB dates are 7 h
behind UTC). Payload files are under `studies/si-pn-diode-vs-temperature/raw/`.

## What was sent

Four `run_sim2l` calls in one client turn, all with
`chosen_outputs ["IV Characteristic", "Parameters"]`, submitted at 17:02:15 (recorded by hand
after the four acknowledgements came back together; uncertainty about 5 s).

## Per job

### Job 53d49b6b-a07e-4d53-83ed-2c37db86f92c, chosen `{"temperature": 250}`

| field | value |
|---|---|
| submitted_at | 2026-10-21T17:02:15Z (see above) |
| get_job_status finished | 2026-10-21T17:02:45Z |
| returned squid | `st4pnjunction/r15/92d2225b5b290c6807945331f1d06b6f81ea8951` |
| returned IV value at 0.6 V | 14.2066 A/cm^2 |
| returned Parameters text | `Temperature: 300K` |
| returned Output Log stamp | `Date and time = 10/27/23  16:21:35` |
| ResultsDB row matching temperature 250 (query 5, 17:10:47Z) | `st4pnjunction/r15/65bea3dd37eb0eaf511a194b47ed30c55ede70cb`, date `2026-10-21 10:02:33.434340` (ResultsDB clock, = 17:02:33Z); an older row `.../62adb25f...` dated 2026-02-04 also exists |
| payload file | `raw/anomaly-parallel-submission/job-250K-53d49b6b.json` |

### Job ffc7acc2-03b7-47ab-8906-1d2e696f57b5, chosen `{}` (temperature default 300)

| field | value |
|---|---|
| submitted_at | 2026-10-21T17:02:15Z |
| get_job_status finished | 2026-10-21T17:02:19Z |
| returned squid | `st4pnjunction/r15/92d2225b5b290c6807945331f1d06b6f81ea8951` |
| returned IV value at 0.6 V | 14.2066 A/cm^2 |
| returned Parameters text | `Temperature: 300K` |
| returned Output Log stamp | `Date and time = 10/27/23  16:21:35` |
| ResultsDB row matching temperature 300 (query 1) | `st4pnjunction/r15/92d2225b5b290c6807945331f1d06b6f81ea8951`, date `2023-10-27 09:21:53.201148` (ResultsDB clock) |
| payload file | `raw/run-00-st4pnjunction.json` |

This is the only job whose payload is consistent with its request.

### Job ce44d418-91b7-4650-9e8c-2a297bf961eb, chosen `{"temperature": 350}`

| field | value |
|---|---|
| submitted_at | 2026-10-21T17:02:15Z |
| get_job_status finished | 2026-10-21T17:02:48Z |
| returned squid | `st4pnjunction/r15/92d2225b5b290c6807945331f1d06b6f81ea8951` |
| returned IV value at 0.6 V | 14.2066 A/cm^2 |
| returned Parameters text | `Temperature: 300K` |
| returned Output Log stamp | `Date and time = 10/27/23  16:21:35` |
| ResultsDB row matching temperature 350 (query 7, 17:10:48Z) | `st4pnjunction/r15/9188c77c3908793456732a5df17320b9de0fd561`, date `2026-10-21 10:02:38.369293` (ResultsDB clock, = 17:02:38Z); an older row `.../1c8d655d...` dated 2023-10-27 also exists |
| payload file | `raw/anomaly-parallel-submission/job-350K-ce44d418.json` |

### Job 8386fe3b-f389-4b24-9cb6-1da66981c977, chosen `{"temperature": 400}`

| field | value |
|---|---|
| submitted_at | 2026-10-21T17:02:15Z |
| get_job_status finished | 2026-10-21T17:02:48Z |
| returned squid | `st4pnjunction/r15/92d2225b5b290c6807945331f1d06b6f81ea8951` |
| returned IV value at 0.6 V | 14.2066 A/cm^2 |
| returned Parameters text | `Temperature: 300K` |
| returned Output Log stamp | `Date and time = 10/27/23  16:21:35` |
| ResultsDB row matching temperature 400 (query 8, 17:11:17Z) | `st4pnjunction/r15/5fc4c128921ada38380634a248e9a38a10785bee`, date `2026-10-21 10:02:40.438749` (ResultsDB clock, = 17:02:40Z); older rows `.../1d333a7f...` (2023-10-27) and `.../e8e15c2d...` (2026-06-04) also exist |
| payload file | `raw/anomaly-parallel-submission/job-400K-8386fe3b.json` |

## Solo re-submissions of the same points (one at a time)

| job | chosen | submitted_at | finished | returned squid | IV at 0.6 V | Parameters | Output Log stamp |
|---|---|---|---|---|---|---|---|
| 788e8f2e-1fdf-4ae4-ab7b-33403bd50f71 | 250 | 17:04:44Z | 17:04:58Z | `.../65bea3dd37eb0eaf511a194b47ed30c55ede70cb` | 1.74986196 | `Temperature: 250K` | `10/21/26  17:02:19` |
| 7bf74c5a-3e3d-4202-8927-e7250d4cc028 | 350 | 17:05:38Z | 17:05:51Z | `.../9188c77c3908793456732a5df17320b9de0fd561` | 25.8425825 | `Temperature: 350K` | `10/21/26  17:02:21` |
| 63ca4d26-00b8-4bf3-a0e6-780cdb7d19d9 | 400 | 17:08:28Z | 17:08:41Z | `.../5fc4c128921ada38380634a248e9a38a10785bee` | 32.358382 | `Temperature: 400K` | `10/21/26  17:02:22` |

Payload files: `raw/run-01-st4pnjunction.json`, `raw/run-02-st4pnjunction.json`,
`raw/run-03-st4pnjunction.json`.

## What is proven (directly visible in the saved payloads and query CSVs)

1. The four concurrent jobs returned byte-identical results: the same squid, the same 21-point IV
   array (14.2066 A/cm^2 at 0.6 V), `Temperature: 300K` in the Parameters output and an Output
   Log dated 2023-10-27. Three of them contradict the `chosen_inputs` they were submitted with.
2. ResultsDB rows for temperature 250, 350 and 400 with new squids appeared with dates
   17:02:33Z, 17:02:38Z and 17:02:40Z (after the ResultsDB offset), that is during the batch.
   They were absent from the queries issued before the batch (`raw/query-00..04`) and present in
   the queries issued after it (`raw/query-05..08`).
3. Submitting each point alone afterwards returned those new squids, with Output Logs stamped
   17:02:19Z to 17:02:22Z, which is the batch window and not the solo submission time.
4. The three mis-routed payloads also carried `inline_files` and `artifacts` paths for the 300 K
   squid, so the whole result envelope, not just a scalar, was the wrong one.

## What is inferred

- The server did execute the 250, 350 and 400 K simulations during the batch (points 2 and 3),
  and stored them in ResultsDB; what was wrong was which stored result each `get_job_result`
  handed back. The likely cause is a shared per-tool working directory or job registry
  (`result.directory` was `./temporary/st4pnjunction/r15/<squid>` in every payload), but the
  server side was not inspected.
- The three jobs reported `finished` 26 to 29 s after submission, consistent with a simulation
  actually running, while the 300 K job finished in 4 s, consistent with a cache hit.
- Whether the solo re-submissions re-ran the simulation or were served from the stored results is
  not provable from the client; the unchanged log stamps point to the stored results.

## Caveats

- `submitted_at` for the batch was recorded by the client after the acknowledgements, not from a
  server timestamp.
- The pre-batch queries were issued through MCP at about 17:01 but written into `study.json` only
  at 17:03:39 to 17:03:41, after the batch, because of a scripting error in the client session;
  their `data` CSVs are unchanged and show no 2026-10-21 rows.

Reproduction steps: `scripts/repro_parallel.md`.
