# ADR-0002: Multi-Data-Source Architecture

## Status
Accepted

## Date
2026-04-12

## Context
Organizations may run multiple ASoC tenants (e.g. US cloud, EU cloud) or self-hosted AppScan 360 instances with separate API credentials. The dashboard previously supported only a single ASoC endpoint. Users need a unified view across all their AppScan instances from a single dashboard deployment.

## Decision
- Introduce a `data_sources` table in PostgreSQL to store multiple ASoC/AppScan 360 connection configurations, each with its own URL, API key, API secret, display label, enabled flag, and `verify_ssl` option.
- Data source management is exposed via CRUD endpoints at `/api/v1/endpoints` with role-based access control.
- A connection probe endpoint (`POST /api/v1/endpoints/{id}/check-status`) validates connectivity and authentication for each data source independently.
- The `multi_endpoint.py` service layer aggregates data from all enabled data sources:
  - `_load_sources()` reads enabled sources from the DB, with optional `data_source_ids` filtering (validated against enabled set, capped at 20).
  - `aggregate_list()` fetches items from each source in parallel, tags each item with `_data_source_id` and `_data_source_label`, and merges results.
  - `aggregate_tenant_info()` and `aggregate_base_data()` follow the same pattern.
  - Per-source failures are logged at `WARNING` level but do not block results from other sources.
- List routes (`/applications`, `/scans`, `/issues`, `/asset-groups`) and all 14 analytics endpoints accept an optional `data_source_ids` query parameter 
for scoped views.
- Analytics cache keys incorporate `data_source_ids` to maintain separate snapshots per selection.
- SSL certificate verification (`verify_ssl`) is threaded through the full chain: `data_source_store` → `multi_endpoint` → `AsocReadService.for_endpoint()` → `AsocApiClient.make()` → `httpx.AsyncClient(verify=...)`.
- The read-only ASoC policy (ADR-0001) applies uniformly to all configured data sources.

## Frontend Integration
- Data Sources sidebar panel displays each source with live connection status indicators.
- Interactive checkboxes allow users to select/deselect data sources for filtering.
- A scope chip at the top of the dashboard shows the active data source selection.
- List items display `_data_source_label` badges to indicate their origin.

## Consequences
- Each data source maintains independent authentication state (separate bearer tokens).
- Aggregated views may show partial results if one source is unreachable (graceful degradation).
- Cache storage grows proportionally with the number of distinct `data_source_ids` combinations used.
- The maximum of 20 data source IDs per request prevents abuse while accommodating realistic deployment sizes.
- Data source credentials are stored in PostgreSQL — the same credential security policies from ADR-0001 apply.
