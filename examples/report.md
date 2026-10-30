# DataTrace investigation

Mode: offline_scripted
Generated: 2026-10-30T06:04:35.393065+00:00
Input SHA-256: 01252ba748d0a8f3d2beddc9068bb475211dd33e6aa4caf966910fe427aff6ca

## Finding

Calculation Defect

The current calculation violates the metric contract. Inspect the replay and per-order differences.

## SQL and data replay

| SQL version | Snapshot | Revenue (USD) | Rows | Evidence |
| --- | --- | ---: | ---: | --- |
| previous | previous | 600.00 | 3 | E1 |
| previous | current | 600.00 | 3 | E2 |
| current | previous | 600.00 | 3 | E3 |
| current | current | 800.00 | 4 | E4 |

## Candidate SQL

```sql
SELECT order_id, revenue_cents FROM orders WHERE status = 'paid' AND order_date >= '2026-10-01' AND order_date < '2026-11-01' AND kind <> 'refund'
```

## Independent check

Verified: True

Complete order/value multiset matches the metric contract.

## Usage

```json
{}
```

## Limits

Deterministic contract diagnostics; no AI or production accuracy claim.

The JSON report contains executed SQL, evidence rows, and tool traces.
