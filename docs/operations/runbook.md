# Operation Runbook

## Daily Operations
- Verify sync job health
- Verify dashboard API health
- Verify report queue latency

## Alerts
- Connector failure rate
- Unauthorized access spikes
- KPI compute failure

## Incident Response
1. Identify affected module.
2. Switch connector to safe mode (read-only remains enforced).
3. Re-run last successful ingestion checkpoint.
4. Communicate incident status via continuity status template.

## Targeted Playbooks
- Auth banner + frozen refresh in dashboard:
	- `docs/operations/troubleshooting-auth-refresh.md`
- Applications scope list appears empty after clear/apply:
	- `docs/operations/troubleshooting-application-filter-list.md`
- Workbench trend charts show empty buckets (scan time, size, DAST coverage):
	- `docs/operations/troubleshooting-workbench-chart-data.md`
