# Evidence: ResultsDB `date` values are 7 hours behind the other clocks

AURA MCP server v2.0.0, st4pnjunction r15, 2026-10-21. Three clocks appear in a session:

- `requested_at` and `get_job_status.last_updated_at`: client and server timestamps carrying `Z`
  (UTC).
- the simulator's own stamp, `Date and time = MM/DD/YY HH:MM:SS` at the top of the PADRE Output
  Log inside `inline_files` (no zone given).
- `date` in the CSV returned by `get_data_from_nanohub` (no zone given).

## Three runs side by side

| run | chosen T | requested_at (UTC) | get_job_status finished (UTC) | Output Log stamp | ResultsDB date for the returned squid | ResultsDB minus log |
|---|---|---|---|---|---|---|
| 1, job 788e8f2e | 250 | 2026-10-21T17:04:44Z | 2026-10-21T17:04:58Z | 10/21/26 17:02:19 | 2026-10-21 10:02:33.434340 | -6 h 59 min 46 s |
| 2, job 7bf74c5a | 350 | 2026-10-21T17:05:38Z | 2026-10-21T17:05:51Z | 10/21/26 17:02:21 | 2026-10-21 10:02:38.369293 | -6 h 59 min 43 s |
| 4, job da1f4efe | 450 | 2026-10-21T17:11:10Z | 2026-10-21T17:11:48Z | 10/21/26 17:11:23 | 2026-10-21 10:11:36.199616 | -6 h 59 min 47 s |

Sources: `requested_at` and `completed_at` in `studies/si-pn-diode-vs-temperature/study.json`
(completed_at was set from `get_job_status.last_updated_at`); the log stamps in
`simulator_log_date` of the same runs (extracted from `inline_files` before stripping); the
ResultsDB dates in `raw/query-05-st4pnjunction.csv`, `raw/query-07-st4pnjunction.csv` and
`raw/query-09-st4pnjunction.csv`.

Run 4 is the cleanest case because it was a genuinely new point: its log stamp (17:11:23) falls
between its submission (17:11:10Z) and its completion (17:11:48Z), which ties the simulator clock
to UTC. The ResultsDB row for the same squid is dated 10:11:36, about 13 s after the log stamp
minus 7 h.

The 2023 cache hit shows the same offset: run 0's Output Log says `10/27/23 16:21:35` and
ResultsDB dates squid `92d2225b...` to `2023-10-27 09:21:53.201148` (-6 h 59 min 42 s).

## What is proven and what is inferred

Proven: ResultsDB `date` values lag the simulator log stamps by 7 h minus 13 to 18 s, consistently
across runs in 2023 and 2026, and the simulator log stamps agree with the UTC job-status
timestamps.

Inferred: ResultsDB stores timestamps in a UTC-7 local zone (Pacific Daylight Time on both dates)
without a zone marker; the 13 to 18 s residual is the time between the simulator starting and the
record being written.

Effect on runcard: read naively, every fresh run would look like a cache hit from 7 h earlier.
`provenance` calibrates the offset from runs that have both a log stamp and a query row (it found
-7 h from 6 samples in the study and 10 in the rerun) and `set --resultsdb-utc-offset-hours`
overrides it.
