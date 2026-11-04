# Benchmark: DataTrace agent vs. no-tools baseline

Across all runs the DataTrace agent produced the correct diagnosis in **179/180** cases, the same Meta model without tools in **168/180**. When the data fits in a prompt, both are accurate, but on realistic 4k-order incidents the agent used **14× fewer input tokens** and cost **4.3× less**, without sending a single raw row. The baseline usually names the right category but not the right numbers: on realistic incidents it put correct dollar amounts on real change and reporting error in **12/24** runs, the agent in **24/24**. On the CMS DE-SynPUF claims incidents the gap widens: correct dollar split in **16/16** runs for the agent versus **4/16** for the baseline. At warehouse scale (~42k orders) the raw rows exceed the model's context window: the baseline could not run (**0/10**), while the agent solved **10/10**.

| Split | System | Correct diagnosis | Root cause named | Dollar split correct | Verified repair when needed | Unneeded repairs | Errors / could not run | Asked for clarification | Input tokens per case | Est. cost per case | Median seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Development (20 mini cases) | DataTrace agent (tools + verifier + reviewer) | 59/60 | 59/60 | 47/47 | 36/36 | 0/24 | 1/60 | 12 | 9,710 | $0.039 | 35.578 |
| Development (20 mini cases) | Same model, no tools, raw rows in prompt | 60/60 | 60/60 | 48/48 | 36/36 | 0/24 | 0/60 | 0 | 996 | $0.008 | 10.359 |
| Stress (20 mini cases, new values) | DataTrace agent (tools + verifier + reviewer) | 60/60 | 60/60 | 48/48 | 36/36 | 0/24 | 0/60 | 12 | 10,211 | $0.042 | 37.125 |
| Stress (20 mini cases, new values) | Same model, no tools, raw rows in prompt | 60/60 | 60/60 | 48/48 | 36/36 | 0/24 | 0/60 | 0 | 1,189 | $0.009 | 12.031 |
| Realistic (10 cases, ~4k orders) | DataTrace agent (tools + verifier + reviewer) | 30/30 | 30/30 | 24/24 | 18/18 | 0/12 | 0/30 | 6 | 14,180 | $0.061 | 51.641 |
| Realistic (10 cases, ~4k orders) | Same model, no tools, raw rows in prompt | 30/30 | 30/30 | 12/24 | 18/18 | 0/12 | 0/30 | 0 | 197,902 | $0.264 | 30.875 |
| Warehouse scale (5 cases, ~42k orders) | DataTrace agent (tools + verifier + reviewer) | 10/10 | 10/10 | 8/8 | 6/6 | 0/4 | 0/10 | 2 | 14,366 | $0.061 | 61.406 |
| Warehouse scale (5 cases, ~42k orders) | Same model, no tools, raw rows in prompt | 0/10 | 0/10 | n/a | 0/6 | 0/4 | 10/10 | 0 | 0 | $0.000 | None |
| Healthcare claims (10 cases, CMS DE-SynPUF) | DataTrace agent (tools + verifier + reviewer) | 20/20 | 20/20 | 16/16 | 12/12 | 0/8 | 0/20 | 4 | 22,990 | $0.084 | 74.187 |
| Healthcare claims (10 cases, CMS DE-SynPUF) | Same model, no tools, raw rows in prompt | 18/20 | 18/20 | 4/16 | 12/12 | 0/8 | 2/20 | 0 | 183,044 | $0.246 | 40.813 |

Synthetic, author-generated incidents with hidden labels; every case was run 3× (scale split 2×) at reasoning effort 'medium'. Correctness is the final, guarded classification. 'Verified repair' means the independent per-order check passed. Costs use Meta list prices on 2026-11-03 and include the muse-wonder-1.0 reviewer for the agent. 'Root cause named' uses a keyword rubric per incident family; 'Dollar split correct' requires both the real change and the reporting error to appear in the explanation within 1% of the deterministic reconciliation. Not a production benchmark. Raw per-case reports are produced by `python -m datatrace.evaluate --mode compare`.

- Development (20 mini cases), DataTrace agent (tools + verifier + reviewer): Could not complete the Meta API request. Check connectivity and retry explicitly. (a transient network failure; automatic retries for network/429/5xx errors were added afterwards)
- Warehouse scale (5 cases, ~42k orders), Same model, no tools, raw rows in prompt: HTTP 400 context_length_exceeded on every request: the raw rows are 2,064,623 tokens and the model's context window is 1,048,576 tokens (error body confirmed directly).
- Healthcare claims (10 cases, CMS DE-SynPUF), Same model, no tools, raw rows in prompt: Baseline response did not complete. (the provider returned an incomplete response, typically the output budget spent on reasoning over the raw rows)
