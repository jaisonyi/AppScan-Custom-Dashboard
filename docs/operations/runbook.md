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

## Multi-Data-Source Operations

### Data Source Health Check
```bash
# List all configured data sources and their status
curl -sS http://127.0.0.1:8000/api/v1/endpoints \
  -H "Authorization: Bearer <token>" | python3 -m json.tool

# Probe a specific data source
curl -X POST http://127.0.0.1:8000/api/v1/endpoints/<id>/check-status \
  -H "Authorization: Bearer <token>"
```

### SSL Certificate Errors
- **Symptom**: `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed` for an AppScan 360 instance.
- **Cause**: Data source has `verify_ssl=true` but uses a self-signed or internal CA certificate.
- **Fix**: Update the data source to `verify_ssl=false` via the Manage UI or API:
  ```bash
  curl -X PUT http://127.0.0.1:8000/api/v1/endpoints/<id> \
    -H "Authorization: Bearer <token>" \
    -H "Content-Type: application/json" \
    -d '{"verify_ssl": false}'
  ```

### Partial Data Source Failure
- If one data source is unreachable, the dashboard shows data from remaining healthy sources.
- Check backend logs for WARNING-level messages indicating per-source failures.
- The failed source's status will show as unreachable in the Data Sources sidebar.

### "Unable to Verify Identity" in Sidebar
- **Symptom**: Data source sidebar shows "Unable to verify identity" instead of the API key owner's name and role.
- **Cause**: The identity probe failed or returned empty results. Common reasons:
  - Network/auth error during `GET /api/v4/Account/TenantInfo`.
  - The ASoC instance does not include `UserInfo` in TenantInfo and `ApiKeyLogin` did not return a `UserId` for the fallback path.
  - A previously failed probe set `last_probed_at` recently, and the 24-hour staleness TTL prevents automatic re-probing.
- **Diagnosis**:
  ```bash
  # Check current probe state in the database
  curl -sS http://127.0.0.1:8000/api/v1/endpoints/identities \
    -H "Authorization: Bearer <token>" | python3 -m json.tool
  ```
  Look for `last_probe_ok: false` with a recent `last_probed_at` timestamp.
- **Fix — Force identity refresh** (bypasses 24-hour TTL):
  ```bash
  cd backend
  PYTHONPATH=$(pwd) python3 -c "
  import asyncio
  from app.services.data_source_service import refresh_all_api_user_info
  results = asyncio.run(refresh_all_api_user_info())
  for ds in results:
      print(f'{ds[\"label\"]}: probe_ok={ds.get(\"last_probe_ok\")}, name=\"{ds.get(\"api_user_name\")}\"')
  "
  ```
- **Configuration**: The staleness TTL is controlled by `identity_probe_ttl_seconds` in settings (default: 86400 seconds / 24 hours).

## CSV Export Operations (v1.5e)

### Health Check
```bash
# Verify export endpoints return 200 with CSV content
curl -sS -o /dev/null -w "%{http_code}" \
  http://127.0.0.1:8000/api/v1/export/scans.csv \
  -H "Authorization: Bearer <token>"
# Expected: 200
```

### Large Export Timeout
- **Symptom**: CSV export hangs or times out for large datasets.
- **Cause**: Aggregation across many data sources with large issue counts.
- **Mitigation**: Use `data_source_ids` parameter to scope exports to specific sources.
- **Note**: Export endpoints use `StreamingResponse` — data is sent incrementally, not buffered in memory.

### Available Export Endpoints
| Endpoint | Content |
|---|---|
| `GET /api/v1/export/scans.csv` | Scans with severity counts |
| `GET /api/v1/export/applications.csv` | Applications with risk/issue counts |
| `GET /api/v1/export/issues.csv` | Issues with CWE/location/dates |
| `GET /api/v1/export/summary.csv` | KPI pivot table + Top 20 apps |

## Docker Deployment Operations (v1.5e)

### Container Health
```bash
# Check container status
docker compose -f infra/compose/docker-compose.yml ps

# Check app health endpoint
curl http://localhost:8000/health

# View app logs
docker compose -f infra/compose/docker-compose.yml logs dashboard --tail 100

# Restart app (preserves DB data)
docker compose -f infra/compose/docker-compose.yml restart dashboard
```

### Database Backup (Docker)
```bash
# Dump PostgreSQL data
docker compose -f infra/compose/docker-compose.yml exec db \
  pg_dump -U postgres aspm > backup_$(date +%Y%m%d).sql
```

### Image Rebuild
```bash
cd infra/compose
docker compose build --no-cache dashboard
docker compose up -d
```

## Azure Deployment Operations (v1.5e)

### Monitoring
- Application Insights is provisioned with the Bicep template.
- Use the Azure Portal → Application Insights → Live Metrics for real-time monitoring.
- Query logs via Log Analytics workspace.

### Key Vault Secret Rotation
```bash
# Update a secret
az keyvault secret set --vault-name <vault-name> --name jwt-secret --value <new-value>

# Restart App Service to pick up new secrets
az webapp restart --name <app-name> --resource-group <rg-name>
```

### Scaling
```bash
# Scale up App Service plan
az appservice plan update --name <plan-name> --resource-group <rg-name> --sku S1
```
