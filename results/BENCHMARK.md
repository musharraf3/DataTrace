# Benchmark: DataTrace agent vs. no-tools baseline

Across all runs the DataTrace agent produced the correct diagnosis in **159/160** cases, the same Meta model without tools in **150/160**. When the data fits in a prompt, both are accurate, but on realistic 4k-order incidents the agent used **14× fewer input tokens** and cost **4.3× less**, without sending a single raw row. At warehouse scale (~42k orders) the raw rows exceed the model's context window: the baseline could not run (**0/10**), while the agent solved **10/10**.

| Split | System | Correct diagnosis | Verified repair when needed | Unneeded repairs | Errors / could not run | Asked for clarification | Input tokens per case | Est. cost per case | Median seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Development (20 mini cases) | DataTrace agent (tools + verifier + reviewer) | 59/60 | 36/36 | 0/24 | 1/60 | 12 | 9,710 | $0.039 | 35.578 |
| Development (20 mini cases) | Same model, no tools, raw rows in prompt | 60/60 | 36/36 | 0/24 | 0/60 | 0 | 996 | $0.008 | 10.359 |
| Stress (20 mini cases, new values) | DataTrace agent (tools + verifier + reviewer) | 60/60 | 36/36 | 0/24 | 0/60 | 12 | 10,211 | $0.042 | 37.125 |
| Stress (20 mini cases, new values) | Same model, no tools, raw rows in prompt | 60/60 | 36/36 | 0/24 | 0/60 | 0 | 1,189 | $0.009 | 12.031 |
| Realistic (10 cases, ~4k orders) | DataTrace agent (tools + verifier + reviewer) | 30/30 | 18/18 | 0/12 | 0/30 | 6 | 14,180 | $0.061 | 51.641 |
| Realistic (10 cases, ~4k orders) | Same model, no tools, raw rows in prompt | 30/30 | 18/18 | 0/12 | 0/30 | 0 | 197,902 | $0.264 | 30.875 |
| Warehouse scale (5 cases, ~42k orders) | DataTrace agent (tools + verifier + reviewer) | 10/10 | 6/6 | 0/4 | 0/10 | 2 | 14,366 | $0.061 | 61.406 |
| Warehouse scale (5 cases, ~42k orders) | Same model, no tools, raw rows in prompt | 0/10 | 0/6 | 0/4 | 10/10 | 0 | 0 | $0.000 | None |

Synthetic, author-generated incidents with hidden labels; every case was run 3× (scale split 2×) at reasoning effort 'medium'. Correctness is the final, guarded classification. 'Verified repair' means the independent per-order check passed. Costs use Meta list prices on 2026-11-03 and include the muse-wonder-1.0 reviewer for the agent. Not a production benchmark. Raw per-case reports are produced by `python -m datatrace.evaluate --mode compare`.

- Development (20 mini cases), DataTrace agent (tools + verifier + reviewer): Could not complete the Meta API request. Check connectivity and retry explicitly. (a transient network failure; automatic retries for network/429/5xx errors were added afterwards)
- Warehouse scale (5 cases, ~42k orders), Same model, no tools, raw rows in prompt: HTTP 400 context_length_exceeded on every request: the raw rows are 2,064,623 tokens and the model's context window is 1,048,576 tokens (error body confirmed directly).
