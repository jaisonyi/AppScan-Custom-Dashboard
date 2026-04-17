# Risk Register

| ID | Risk | Impact | Likelihood | Owner | Mitigation |
|---|---|---|---|---|---|
| R1 | Credential delivery delay | Medium | Medium | PM | Use mock mode until credentials are provided; pipeline BOM stub endpoint now explicitly marked with `_stub: true` response field and `X-Stub-Data: true` header |
| R2 | Incorrect asset-group mapping | High | Medium | Security Lead | Add matrix tests and review checkpoints |
| R3 | KPI formula drift | Medium | Medium | Data Lead | Version formula catalog and test baseline |
| R4 | Connector API changes | High | Medium | Integration Lead | Introduce adapter versioning |
| R5 | ASoC field name inconsistency across scan types/versions | High | Medium | Integration Lead | Maintain wide key-list in each extractor (`_extract_scan_duration_seconds`, `_extract_sast_size_profile`, `_extract_sca_size_profile`); add extractor unit tests for all known field name variants; log unmapped fields for discovery |
| R6 | JWT secret not configured in production | Critical | Medium | Security Lead | Startup warning log emitted when `JWT_SECRET` env var is absent; a secure random secret is auto-generated so the service starts safely, but tokens are invalidated on restart — set `JWT_SECRET` explicitly for production |
| R7 | Unbounded cache lock growth (`_CACHE_LOCKS`) | Medium | Low | Engineering Lead | **RESOLVED** — bounded to 500 entries; LRU eviction removes oldest 100 entries when limit is reached |
| R8 | Insufficient test coverage for critical service modules | High | Medium | Engineering Lead | **PARTIALLY MITIGATED** — 577 unit tests across 26 files (~62% overall coverage); security modules at 75–100%, repository at 89%, routes at 86–93%; `asoc_read_service.py` (43%) and `analytics.py` routes (47%) remain under-covered and require integration tests for HTTP integration paths |
| R9 | Multi-source credential sprawl | Medium | Medium | Security Lead | Each data source stores independent API key/secret in PostgreSQL; `api_secret` is write-only (never returned in API responses); credentials follow same rotation policy as environment-level keys |
| R10 | Partial data source failure degrades dashboard | Medium | Medium | Engineering Lead | `multi_endpoint.py` aggregates results from healthy sources and logs WARNING for failures; Data Sources sidebar shows per-source connectivity status; partial results are clearly indicated |
| R11 | Cache key explosion from `data_source_ids` combinations | Low | Medium | Engineering Lead | `_load_sources()` validates IDs against enabled sources and caps at 20; cache key v18 includes sorted `data_source_ids` for deterministic keys; LRU eviction (R7) bounds memory growth |
| R12 | CSV export timeout on large datasets | Medium | Medium | Engineering Lead | Export endpoints use `StreamingResponse` for incremental delivery; `data_source_ids` parameter allows scoping exports to specific sources; no full-dataset buffering in memory |
| R13 | Docker image supply-chain vulnerability | Medium | Low | Security Lead | Multi-stage build uses official `node:20-alpine` and `python:3.12-slim` base images; non-root user enforced; `--no-cache-dir` reduces attack surface; periodic base image rebuild recommended |
| R14 | Azure Key Vault secret rotation disruption | Medium | Low | Security Lead | App Service must be restarted after Key Vault secret updates; documented in runbook; consider Key Vault reference auto-refresh in future |
