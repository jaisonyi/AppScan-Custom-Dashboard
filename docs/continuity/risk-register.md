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
| R8 | Insufficient test coverage for critical service modules | High | Medium | Engineering Lead | **PARTIALLY MITIGATED** — 518 unit tests added across 20 files (62% overall coverage); security modules at 75–100%, repository at 89%, routes at 86–93%; `asoc_read_service.py` (43%) and `analytics.py` routes (47%) remain under-covered and require integration tests for HTTP integration paths |
