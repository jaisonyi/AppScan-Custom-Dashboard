# ASOC ASPM Dashboard v1.3.1 — Backend Unit Test Plan

> **Architect:** This document defines the complete test architecture for the backend.
> **Lead Developer:** Implement each file in the priority order defined in §6.
> **QA/Guardian:** Enforce coverage gates defined in §7 before any PR merge.

---

## Table of Contents

1. [Test Architecture Overview](#1-test-architecture-overview)
2. [Test File Inventory](#2-test-file-inventory)
3. [Shared Fixtures — conftest.py](#3-shared-fixtures--conftestpy)
4. [Dependency Requirements](#4-dependency-requirements)
5. [Mocking Strategy Reference](#5-mocking-strategy-reference)
6. [Priority Order](#6-priority-order)
7. [Coverage Targets](#7-coverage-targets)

---

## 1. Test Architecture Overview

### 1.1 Directory Structure

```
backend/
├── pyproject.toml
├── tests/
│   ├── conftest.py                         ← shared fixtures (NEW)
│   ├── unit/
│   │   ├── __init__.py                     ← NEW
│   │   ├── test_read_only_policy.py        ← EXISTS (keep as-is)
│   │   ├── test_policy.py                  ← NEW
│   │   ├── test_authorization.py           ← NEW
│   │   ├── test_auth.py                    ← NEW
│   │   ├── test_dependencies.py            ← NEW
│   │   ├── test_settings.py                ← NEW
│   │   ├── test_postgres_store.py          ← NEW
│   │   ├── test_report_artifacts.py        ← NEW
│   │   ├── test_asoc_read_service.py       ← NEW
│   │   ├── test_multi_endpoint.py          ← NEW
│   │   ├── test_schedule_utils.py          ← NEW
│   │   ├── test_report_scheduler.py        ← NEW
│   │   ├── test_analytics_prewarm.py       ← NEW
│   │   └── routes/
│   │       ├── __init__.py                 ← NEW
│   │       ├── test_route_auth.py          ← NEW
│   │       ├── test_route_dashboard.py     ← NEW
│   │       ├── test_route_audit.py         ← NEW
│   │       ├── test_route_analytics.py     ← NEW
│   │       ├── test_route_reports.py       ← NEW
│   │       ├── test_route_pipeline_bom.py  ← NEW
│   │       ├── test_route_applications.py  ← NEW
│   │       ├── test_route_asset_groups.py  ← NEW
│   │       ├── test_route_issues.py        ← NEW
│   │       └── test_route_scans.py         ← NEW
│   ├── integration/                        ← empty (out of scope)
│   └── e2e/                                ← empty (out of scope)
```

### 1.2 Naming Conventions

| Convention | Rule |
|---|---|
| Test files | `test_<module_name>.py` |
| Test functions | `test_<what>_<condition>_<expected>` |
| Test classes | `TestClassName` (group related tests for a single class) |
| Fixtures | `snake_case` descriptive nouns (e.g., `admin_user`, `fake_store`) |
| Parametrize IDs | Human-readable strings (e.g., `"PlatformAdmin-allowed"`) |

### 1.3 Test Runner Configuration

Add the following to [`backend/pyproject.toml`](backend/pyproject.toml):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
markers = [
    "unit: fast unit tests with no I/O",
    "slow: tests that may take >1s",
]

[tool.coverage.run]
source = ["app"]
omit = ["app/services/mock_data.py", "migrations/*"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

---

## 2. Test File Inventory

### 2.1 `tests/unit/test_policy.py`

**Module under test:** [`backend/app/core/security/policy.py`](backend/app/core/security/policy.py)

**What to test:** The `ROLE_ACTION_POLICY` dict and `assert_action_allowed()`.

| Test function | Description |
|---|---|
| `test_all_16_actions_present` | `ROLE_ACTION_POLICY` has exactly 16 keys |
| `test_all_5_roles_covered` | Every role appears in at least one action |
| `test_assert_action_allowed_raises_403_for_wrong_role` | `Developer` calling `generate_report` raises HTTP 403 |
| `test_assert_action_allowed_raises_403_for_auditor_on_manage_schedules` | `Auditor` calling `manage_report_schedules` raises HTTP 403 |
| `test_assert_action_allowed_passes_for_valid_role` | Parametrized: all allowed role/action combos pass |
| `test_assert_action_allowed_raises_500_for_unknown_action` | Unknown action string raises HTTP 500 |
| `test_developer_cannot_create_dashboard` | `Developer` calling `create_dashboard` raises HTTP 403 |
| `test_auditor_can_view_audit_events` | `Auditor` calling `view_audit_events` raises no exception |
| `test_read_only_roles_parametrized` | All read-only actions x all 5 roles — all pass |

**Mocking strategy:** None — pure Python logic, no I/O.

---

### 2.2 `tests/unit/test_authorization.py`

**Module under test:** [`backend/app/core/security/authorization.py`](backend/app/core/security/authorization.py)

| Test function | Description |
|---|---|
| `test_assert_asset_group_access_raises_403_when_not_permitted` | Group not in permitted list raises HTTP 403 |
| `test_assert_asset_group_access_passes_when_permitted` | Group in permitted list raises no exception |
| `test_assert_role_raises_403_for_wrong_role` | Role not in required list raises HTTP 403 |
| `test_assert_role_passes_for_correct_role` | Role in required list raises no exception |
| `test_has_asset_group_access_returns_true_for_none_group` | `requested_asset_group=None` always returns True |
| `test_has_asset_group_access_admin_bypasses_check` | `PlatformAdmin` with any group returns True |
| `test_has_asset_group_access_security_manager_bypasses_check` | `SecurityManager` with any group returns True |
| `test_has_asset_group_access_non_admin_checks_list` | Non-admin with group not in list returns False |
| `test_filter_by_asset_group_admin_returns_all` | Admin role returns all items unchanged |
| `test_filter_by_asset_group_non_admin_filters_correctly` | Non-admin returns only items with matching group IDs |
| `test_filter_by_asset_group_handles_list_values` | Item with `asset_group_id` as list is correctly matched |
| `test_filter_by_asset_group_empty_list` | Empty items list returns empty result |

**Mocking strategy:** None — pure Python logic.

---

### 2.3 `tests/unit/test_auth.py`

**Module under test:** [`backend/app/core/security/auth.py`](backend/app/core/security/auth.py)

| Test function | Description |
|---|---|
| `test_create_access_token_returns_decodable_jwt` | Token created with `create_access_token()` decodes to correct claims |
| `test_create_access_token_contains_sub_role_asset_groups` | Decoded payload has `sub`, `role`, `asset_group_ids` |
| `test_create_access_token_expires_in_configured_minutes` | `exp` claim is within expected window |
| `test_decode_access_token_local_mode_valid` | Valid local JWT decodes without error |
| `test_decode_access_token_local_mode_expired_raises` | Expired JWT raises `JWTError` |
| `test_decode_access_token_local_mode_tampered_raises` | Tampered signature raises `JWTError` |
| `test_decode_access_token_async_local_mode` | `decode_access_token_async()` in local mode returns same payload |
| `test_oidc_is_configured_returns_false_when_empty` | Empty `oidc_issuer_url` returns False |
| `test_oidc_is_configured_returns_true_when_set` | Non-empty `oidc_issuer_url` returns True |
| `test_oidc_missing_fields_returns_issuer_url_when_missing` | Empty issuer returns `["OIDC_ISSUER_URL"]` |
| `test_get_jwks_keys_uses_cache_when_fresh` | Second call within TTL does not make HTTP request |
| `test_get_jwks_keys_refreshes_when_stale` | Cache expired triggers HTTP request to JWKS endpoint |
| `test_decode_oidc_token_raises_when_kid_missing` | Token without `kid` header raises `JWTError` |
| `test_decode_oidc_token_raises_when_no_matching_key` | No matching JWK for `kid` raises `JWTError` |

**Mocking strategy:**
- Patch `settings.auth_mode`, `settings.jwt_secret`, `settings.oidc_issuer_url` via `monkeypatch`
- Mock `httpx.AsyncClient.get` using `respx` for JWKS/OIDC tests
- Reset `_JWKS_CACHE` and `_JWKS_LOCK` module globals between tests using `monkeypatch.setattr`

---

### 2.4 `tests/unit/test_dependencies.py`

**Module under test:** [`backend/app/core/security/dependencies.py`](backend/app/core/security/dependencies.py)

| Test function | Description |
|---|---|
| `test_get_current_user_returns_user_context_for_valid_token` | Valid JWT returns `UserContext` with correct fields |
| `test_get_current_user_raises_401_for_invalid_token` | Malformed token raises HTTP 401 |
| `test_get_current_user_raises_401_for_expired_token` | Expired token raises HTTP 401 |
| `test_get_current_user_raises_401_for_missing_sub` | Token without `sub` raises HTTP 401 |
| `test_get_current_user_raises_401_for_missing_role` | Token without `role` raises HTTP 401 |
| `test_get_current_user_raises_401_for_non_list_asset_groups` | `asset_group_ids` not a list raises HTTP 401 |
| `test_get_current_user_raises_503_when_oidc_not_configured` | `auth_mode=oidc` but no issuer URL raises HTTP 503 |
| `test_get_current_user_normalizes_asset_group_ids` | Empty strings in list are stripped from result |
| `test_get_current_user_uses_oidc_claims_in_oidc_mode` | OIDC mode uses `oidc_role_claim` and `oidc_asset_groups_claim` |

**Mocking strategy:**
- Use `pytest-asyncio` for async tests
- Mock `decode_access_token_async` with `AsyncMock`
- Patch `settings.auth_mode` and `settings.oidc_issuer_url` via `monkeypatch`
- Construct `HTTPAuthorizationCredentials` directly (no HTTP client needed)

---

### 2.5 `tests/unit/test_settings.py`

**Module under test:** [`backend/app/core/config/settings.py`](backend/app/core/config/settings.py)

| Test function | Description |
|---|---|
| `test_settings_defaults_are_sane` | Default `auth_mode` is `"local"`, `asoc_read_only` is `True` |
| `test_all_asoc_endpoints_returns_empty_when_no_key` | No `asoc_api_key` returns empty list |
| `test_all_asoc_endpoints_returns_primary_when_key_set` | `asoc_api_key` set returns single-item list with `"Primary"` label |
| `test_all_asoc_endpoints_parses_json_array` | Valid `asoc_endpoints_json` returns list of endpoint dicts |
| `test_all_asoc_endpoints_falls_back_on_invalid_json` | Malformed JSON falls back to primary endpoint |
| `test_all_asoc_endpoints_skips_entries_without_url_or_key` | Entries missing `url` or `key` are excluded |
| `test_all_asoc_endpoints_strips_trailing_slash_from_url` | URL with trailing slash is stripped in output |
| `test_all_asoc_endpoints_uses_url_as_label_when_label_missing` | No `label` field uses URL as label |

**Mocking strategy:** Instantiate `Settings` directly with constructor kwargs; use `monkeypatch.setenv` for env var tests.

---

### 2.6 `tests/unit/test_postgres_store.py`

**Module under test:** [`backend/app/repositories/postgres_store.py`](backend/app/repositories/postgres_store.py)

**Mocking strategy:** Patch `_connect()` to return a `MagicMock` simulating `_CompatConnection`. No real PostgreSQL connection.

| Test function | Description |
|---|---|
| `test_normalize_database_url_strips_psycopg_prefix` | `postgresql+psycopg://...` becomes `postgresql://...` |
| `test_normalize_database_url_leaves_plain_url_unchanged` | `postgresql://...` is returned unchanged |
| `test_utc_now_returns_iso_string` | `_utc_now()` returns a valid ISO 8601 string |
| `test_as_driver_sql_replaces_question_marks` | `?` placeholders become `%s` |
| `test_list_dashboards_returns_parsed_rows` | Mock cursor returns rows; result is list of dicts with parsed JSON |
| `test_get_dashboard_returns_none_when_not_found` | `fetchone()` returns `None`; function returns `None` |
| `test_get_dashboard_returns_parsed_row` | `fetchone()` returns row; result is dict with parsed `widgets` and `blueprint` |
| `test_create_dashboard_inserts_and_returns_dict` | `execute()` called with INSERT; returns dict with correct fields |
| `test_update_dashboard_returns_none_when_not_found` | `get_dashboard` returns `None`; `update_dashboard` returns `None` |
| `test_update_dashboard_applies_partial_update` | Only `name` provided; widgets remain unchanged |
| `test_delete_dashboard_returns_true_on_success` | `rowcount=1` returns `True` |
| `test_delete_dashboard_returns_false_when_not_found` | `rowcount=0` returns `False` |
| `test_append_audit_event_inserts_and_returns_dict` | INSERT called; returns dict with all fields |
| `test_count_audit_events_returns_integer` | `fetchone()` returns `{"c": 42}`; result is `42` |
| `test_list_audit_events_with_limit_and_offset` | Correct SQL params passed for pagination |
| `test_upsert_analytics_snapshot_calls_upsert_sql` | ON CONFLICT DO UPDATE SQL is executed |
| `test_get_analytics_snapshot_returns_none_when_missing` | `fetchone()` returns `None`; result is `None` |
| `test_get_analytics_snapshot_parses_payload_json` | Row with `payload_json` returns dict with parsed `payload` |
| `test_purge_expired_analytics_snapshots_returns_rowcount` | `rowcount=3` returns `3` |
| `test_report_artifact_map_returns_empty_for_empty_ids` | Empty list returns `{}` without DB call |
| `test_list_due_report_schedules_filters_by_enabled_and_next_run` | SQL WHERE clause is verified |
| `test_upsert_report_artifact_calls_upsert_sql` | ON CONFLICT DO UPDATE SQL is executed |
| `test_latest_schedule_execution_map_groups_by_resource_id` | Aggregation query result is parsed correctly |
| `test_append_dashboard_version_increments_version` | `_next_dashboard_version` returns max+1 |
| `test_list_report_schedules_returns_parsed_rows` | Rows with `enabled=1` return `enabled=True` in result |

---

### 2.7 `tests/unit/test_report_artifacts.py`

**Module under test:** [`backend/app/services/report_artifacts.py`](backend/app/services/report_artifacts.py)

| Test function | Description |
|---|---|
| `test_create_report_artifact_writes_json_file` | `file_path.write_text()` called with serialized payload |
| `test_create_report_artifact_calls_upsert` | `upsert_report_artifact()` called with correct args |
| `test_create_report_artifact_returns_artifact_dict` | Return value has `report_id`, `file_name`, `mime_type` |
| `test_resolve_artifact_path_returns_path_inside_exports_dir` | Valid path inside exports dir returns `Path` object |
| `test_resolve_artifact_path_raises_for_path_traversal` | `../../etc/passwd` raises `ValueError` |
| `test_resolve_artifact_path_raises_for_absolute_outside_dir` | Absolute path outside exports raises `ValueError` |

**Mocking strategy:** Patch `EXPORTS_DIR` to a `tmp_path` fixture directory; patch `upsert_report_artifact` with `MagicMock`.

---

### 2.8 `tests/unit/test_asoc_read_service.py`

**Module under test:** [`backend/app/services/asoc_read_service.py`](backend/app/services/asoc_read_service.py)

#### Static helper functions

| Test function | Description |
|---|---|
| `test_extract_items_from_list` | List input returns same list |
| `test_extract_items_from_dict_with_Items_key` | `{"Items": [...]}` returns inner list |
| `test_extract_items_from_dict_with_value_key` | `{"value": [...]}` returns inner list |
| `test_extract_items_returns_empty_for_unknown_shape` | Unrecognized dict returns `[]` |
| `test_parse_dt_valid_iso` | Valid ISO string returns `datetime` with UTC tzinfo |
| `test_parse_dt_with_Z_suffix` | `"2025-01-01T00:00:00Z"` returns UTC datetime |
| `test_parse_dt_returns_none_for_empty` | Empty string returns `None` |
| `test_parse_dt_returns_none_for_invalid` | `"not-a-date"` returns `None` |
| `test_parse_duration_to_seconds_from_int` | `120` returns `120.0` |
| `test_parse_duration_to_seconds_from_hhmmss` | `"01:30:00"` returns `5400.0` |
| `test_parse_duration_to_seconds_from_mmss` | `"05:30"` returns `330.0` |
| `test_parse_duration_to_seconds_returns_none_for_empty` | `""` returns `None` |
| `test_normalize_scan_type_dast` | `"DYNAMIC"` returns `"DAST"` |
| `test_normalize_scan_type_sast` | `"STATIC"` returns `"SAST"` |
| `test_normalize_scan_type_sca` | `"SCA"` returns `"SCA"` |
| `test_normalize_scan_type_unknown` | `"UNKNOWN_TYPE"` returns `"OTHER"` |
| `test_normalize_scan_status_completed_variants` | `"finished"`, `"done"`, `"ready"` all return `"completed"` |
| `test_normalize_scan_status_failed_variants` | `"aborted"`, `"canceled"` return `"failed"` |
| `test_normalize_scan_status_running` | `"inprogress"` returns `"running"` |
| `test_normalize_severity_critical` | `"4"`, `"veryhigh"` return `"critical"` |
| `test_normalize_severity_high` | `"3"`, `"sev3"` return `"high"` |
| `test_normalize_severity_medium` | `"moderate"`, `"2"` return `"medium"` |
| `test_normalize_severity_low` | `"info"`, `"0"` return `"low"` |
| `test_normalize_severity_unknown` | `"garbage"` returns `"unknown"` |
| `test_is_active_issue_open` | `status="open"` returns `True` |
| `test_is_active_issue_closed` | `status="closed"` returns `False` |
| `test_period_bucket_month` | ISO date returns `"YYYY-MM"` |
| `test_period_bucket_week` | ISO date returns `"YYYY-Www"` |
| `test_period_bucket_day` | ISO date returns `"YYYY-MM-DD"` |
| `test_build_app_technology_maps_single_type` | One scan type per app; primary equals that type |
| `test_build_app_technology_maps_tie_breaker` | Equal counts; DAST wins over SAST |

#### `AsocReadService` class methods

| Test function | Description |
|---|---|
| `test_calculate_statistics_counts_by_severity` | Issues with known severities return correct counts |
| `test_calculate_statistics_active_vs_resolved` | Mix of open/closed returns correct active/resolved split |
| `test_calculate_trend_groups_by_month` | Issues with `opened_at` return monthly buckets |
| `test_calculate_trend_returns_current_month_when_empty` | No issues returns single current-month entry |
| `test_calculate_mttr_averages_by_month` | Closed issues with `mttr_days` return monthly averages |
| `test_calculate_kpi_critical_exposure_percentage` | 1 critical out of 10 returns `10.0%` |
| `test_calculate_prioritization_top_fix_groups` | Issues with fix groups return top 8 by weighted score |
| `test_calculate_prioritization_most_critical_apps` | Issues by app return top 8 hotspots |
| `test_calculate_findings_series_month_granularity` | Issues return monthly severity breakdown |
| `test_calculate_findings_series_week_granularity` | Issues return weekly severity breakdown |
| `test_calculate_scan_series_hybrid_mode` | Hybrid severity: native when available, else derived |
| `test_calculate_scan_series_native_mode` | Native severity only |
| `test_calculate_scan_series_derived_mode` | Derived severity from issues |
| `test_apply_filters_by_asset_group` | `asset_group_id` filter returns only matching scans/issues |
| `test_apply_filters_by_application_id` | `application_id` filter returns only matching items |
| `test_apply_filters_by_scan_type` | `scan_types=["DAST"]` returns only DAST scans |
| `test_apply_filters_by_date_range` | `from_date`/`to_date` returns items within range only |
| `test_apply_filters_no_filters_returns_all` | No filters returns all items |
| `test_filter_issues_by_dimensions_technology` | `issue_technologies=["DAST"]` returns only DAST issues |
| `test_filter_issues_by_dimensions_vulnerability` | `vulnerabilities=["xss"]` returns only matching issues |
| `test_build_issue_filter_options_counts_technologies` | Issues return technology counts dict |
| `test_build_portfolio_summary_counts` | Scans/issues/apps/groups return correct summary counts |
| `test_map_issue_items_extracts_severity` | Raw API item returns normalized `severity` field |
| `test_map_issue_items_infers_closed_at_from_status` | Closed issue without `closed_at` infers from `LastUpdated` |
| `test_has_credentials_false_when_no_key` | No API key; `has_credentials` is `False` |
| `test_has_credentials_true_when_all_set` | All credentials set; `has_credentials` is `True` |

**Mocking strategy:** All `AsocApiClient.get()` calls mocked with `AsyncMock`. Reset `_DAST_PAGE_CACHE` between tests via `monkeypatch.setattr`.

---

### 2.9 `tests/unit/test_multi_endpoint.py`

**Module under test:** [`backend/app/services/multi_endpoint.py`](backend/app/services/multi_endpoint.py)

| Test function | Description |
|---|---|
| `test_get_endpoint_services_returns_empty_when_no_credentials` | No endpoints configured returns `[]` |
| `test_get_endpoint_services_returns_one_per_endpoint` | 2 endpoints configured returns 2 services |
| `test_get_endpoint_labels_returns_url_and_label` | Endpoints return list of `{url, label}` dicts |
| `test_aggregate_list_returns_empty_when_no_services` | No services returns `[]` |
| `test_aggregate_list_merges_results_from_multiple_endpoints` | 2 services each returning 2 items returns 4 items merged |
| `test_aggregate_list_skips_failed_endpoints` | One service raises; other results still returned |
| `test_aggregate_list_logs_warning_on_failure` | Failed endpoint triggers warning log |
| `test_aggregate_tenant_info_returns_first_successful` | First service returns dict; that dict is returned |
| `test_aggregate_tenant_info_skips_failed_and_tries_next` | First fails; second service is used |
| `test_aggregate_tenant_info_returns_empty_when_all_fail` | All fail returns `{}` |
| `test_aggregate_base_data_returns_empty_when_no_services` | No services returns empty dict with all keys |
| `test_aggregate_base_data_merges_scans_issues_apps_groups` | 2 services return merged lists |
| `test_aggregate_base_data_uses_first_tenant_info` | First service tenant_info is used |

**Mocking strategy:** Patch `settings.all_asoc_endpoints()` to return controlled endpoint lists; mock `AsocReadService` methods with `AsyncMock`.

---

### 2.10 `tests/unit/test_schedule_utils.py`

**Module under test:** [`backend/app/workers/schedule_utils.py`](backend/app/workers/schedule_utils.py)

| Test function | Description |
|---|---|
| `test_utc_now_returns_utc_datetime` | `utc_now()` returns timezone-aware UTC datetime |
| `test_ensure_valid_cron_accepts_valid_expression` | `"0 * * * *"` raises no exception |
| `test_ensure_valid_cron_raises_for_invalid_expression` | `"not-a-cron"` raises exception |
| `test_compute_next_run_iso_returns_future_datetime` | Next run is after `base_dt` |
| `test_compute_next_run_iso_returns_utc_iso_string` | Result is valid ISO 8601 with UTC offset |
| `test_compute_next_run_iso_uses_provided_base_dt` | Custom `base_dt` returns next run relative to it |
| `test_compute_next_run_iso_hourly_cron` | `"0 * * * *"` returns next run within 1 hour |

**Mocking strategy:** None — pure Python logic using `croniter`.

---

### 2.11 `tests/unit/test_report_scheduler.py`

**Module under test:** [`backend/app/workers/report_scheduler.py`](backend/app/workers/report_scheduler.py)

| Test function | Description |
|---|---|
| `test_backoff_next_run_first_retry` | `retry_count=1` returns delay equal to `backoff_base_seconds` |
| `test_backoff_next_run_second_retry` | `retry_count=2` returns delay equal to `backoff_base_seconds * 2` |
| `test_backoff_next_run_caps_at_max` | High `retry_count` caps delay at `backoff_max_seconds` |
| `test_run_scheduler_executes_due_schedules` | Due schedule triggers `append_report_history` and `create_report_artifact` |
| `test_run_scheduler_updates_next_run_after_success` | Successful execution calls `update_report_schedule` with new `next_run_at` |
| `test_run_scheduler_increments_retry_on_failure` | `create_report_artifact` raises; `retry_count` is incremented |
| `test_run_scheduler_disables_schedule_at_max_retries` | `retry_count >= max_retries` sets `enabled=False` in update |
| `test_run_scheduler_stops_on_stop_event` | `stop_event.set()` causes loop to exit cleanly |
| `test_run_scheduler_appends_audit_event_on_success` | Success calls `append_audit_event` with `report_schedule.execute` |
| `test_run_scheduler_appends_audit_event_on_retry` | Failure calls `append_audit_event` with `report_schedule.retry` |
| `test_run_scheduler_appends_audit_event_on_disable` | Max retries calls `append_audit_event` with `report_schedule.disabled` |

**Mocking strategy:** Patch `list_due_report_schedules`, `append_report_history`, `create_report_artifact`, `update_report_schedule`, `append_audit_event` with `MagicMock`. Patch `settings.report_scheduler_interval_seconds = 0`.

---

### 2.12 `tests/unit/test_analytics_prewarm.py`

**Module under test:** [`backend/app/workers/analytics_prewarm.py`](backend/app/workers/analytics_prewarm.py)

| Test function | Description |
|---|---|
| `test_run_analytics_prewarm_calls_prewarm_on_startup` | `prewarm_base_data_cache` called once at startup |
| `test_run_analytics_prewarm_calls_prewarm_periodically` | After interval, `prewarm_base_data_cache` called again |
| `test_run_analytics_prewarm_stops_on_stop_event` | `stop_event.set()` causes loop to exit cleanly |
| `test_run_analytics_prewarm_logs_exception_on_failure` | `prewarm_base_data_cache` raises; exception logged, loop continues |

**Mocking strategy:** Patch `prewarm_base_data_cache` with `AsyncMock`. Patch `settings.analytics_prewarm_interval_seconds = 0`. Use `asyncio.Event` for `stop_event`.

---

### 2.13 Route Tests — `tests/unit/routes/`

See [`plans/PLAN_part2.md`](plans/PLAN_part2.md) §2.13 for the full route test inventory covering:
- [`test_route_auth.py`](backend/app/api/v1/routes/auth.py) — 7 tests
- [`test_route_dashboard.py`](backend/app/api/v1/routes/dashboard.py) — 19 tests
- [`test_route_audit.py`](backend/app/api/v1/routes/audit.py) — 7 tests
- [`test_route_analytics.py`](backend/app/api/v1/routes/analytics.py) — 18 tests
- [`test_route_reports.py`](backend/app/api/v1/routes/reports.py) — 23 tests
- [`test_route_pipeline_bom.py`](backend/app/api/v1/routes/pipeline_bom.py) — 4 tests
- [`test_route_applications.py`](backend/app/api/v1/routes/applications.py) — 4 tests
- [`test_route_asset_groups.py`](backend/app/api/v1/routes/asset_groups.py) — 4 tests
- [`test_route_issues.py`](backend/app/api/v1/routes/issues.py) — 4 tests
- [`test_route_scans.py`](backend/app/api/v1/routes/scans.py) — 6 tests

All route tests share the same pattern: override `get_current_user` dependency, patch store/service functions with `MagicMock`/`AsyncMock`, use `httpx.AsyncClient` with `base_url="http://test"`.

---

## 3. Shared Fixtures — `conftest.py`

**File:** [`backend/tests/conftest.py`](backend/tests/conftest.py)

See [`plans/PLAN_part2.md`](plans/PLAN_part2.md) §3 for full fixture code. Summary of fixtures to define:

| Fixture | Type | Purpose |
|---|---|---|
| `admin_user` | `UserContext` | `PlatformAdmin` with `["ag-1","ag-2"]` |
| `security_manager_user` | `UserContext` | `SecurityManager` with `["ag-1"]` |
| `app_owner_user` | `UserContext` | `AppOwner` with `["ag-1"]` |
| `developer_user` | `UserContext` | `Developer` with `["ag-1"]` |
| `auditor_user` | `UserContext` | `Auditor` with `["ag-1"]` |
| `valid_local_jwt` | `str` | Non-expired JWT signed with test secret |
| `expired_local_jwt` | `str` | JWT with `exp` in the past |
| `tampered_jwt` | `str` | JWT with corrupted signature |
| `app_client` | `AsyncClient` | No auth override — for 403 tests |
| `authed_client` | `AsyncClient` | Admin user pre-injected |
| `make_authed_client` | factory | Returns client with any user injected |
| `fake_dashboard` | `dict` | Sample dashboard row |
| `fake_audit_event` | `dict` | Sample audit event row |
| `fake_scans` | `list[dict]` | 3 scans: SAST/DAST/SCA across 2 asset groups |
| `fake_issues` | `list[dict]` | 3 issues: critical/high/medium, open/closed |
| `fake_applications` | `list[dict]` | 2 apps across 2 asset groups |
| `fake_asset_groups` | `list[dict]` | 2 groups: Production/Staging |
| `local_auth_settings` | fixture | Patches `auth_mode="local"` + test secret |
| `oidc_auth_settings` | fixture | Patches `auth_mode="oidc"` + issuer URL |

---

## 4. Dependency Requirements

Add to `[project.optional-dependencies] dev` in [`backend/pyproject.toml`](backend/pyproject.toml):

| Package | Version | Status |
|---|---|---|
| `pytest` | `>=8.3.0` | Already present |
| `pytest-asyncio` | `>=0.24.0` | Already present |
| `ruff` | `>=0.6.0` | Already present |
| `alembic` | `>=1.14.0` | Already present |
| `pytest-mock` | `>=3.14.0` | **NEW** — `mocker` fixture |
| `pytest-cov` | `>=5.0.0` | **NEW** — coverage with `fail_under` gate |
| `respx` | `>=0.21.0` | **NEW** — mock `httpx` for JWKS/OIDC tests |
| `freezegun` | `>=1.5.0` | **NEW** — freeze time for TTL/expiry tests |

```toml
[project.optional-dependencies]
dev = [
  "alembic>=1.14.0",
  "pytest>=8.3.0",
  "pytest-asyncio>=0.24.0",
  "pytest-mock>=3.14.0",
  "pytest-cov>=5.0.0",
  "respx>=0.21.0",
  "freezegun>=1.5.0",
  "ruff>=0.6.0",
]
```

---

## 5. Mocking Strategy Reference

| What to mock | How | Where used |
|---|---|---|
| `get_current_user` FastAPI dependency | `app.dependency_overrides[get_current_user] = lambda: user` | All route tests |
| `postgres_store` functions | `monkeypatch.setattr("app.repositories.postgres_store.<fn>", mock)` | Route + scheduler tests |
| `AsocApiClient.get` | `mocker.patch.object(AsocApiClient, "get", new_callable=AsyncMock)` | Service + route tests |
| `httpx.AsyncClient.get` | `respx.mock` context manager | `test_auth.py` JWKS tests |
| `settings.*` fields | `monkeypatch.setattr(settings, "auth_mode", "oidc")` | Auth + dependency tests |
| `asyncio.create_task` | `mocker.patch("asyncio.create_task")` | Analytics background task tests |
| `Path.write_text` / `Path.exists` | `mocker.patch.object(Path, "write_text")` | Report artifact tests |
| `_JWKS_CACHE` module global | `monkeypatch.setattr("app.core.security.auth._JWKS_CACHE", {...})` | JWKS cache tests |
| `_DAST_PAGE_CACHE` module global | `monkeypatch.setattr("app.services.asoc_read_service._DAST_PAGE_CACHE", {})` | DAST cache tests |
| `datetime.now()` / `time.time()` | `freezegun.freeze_time("2025-06-01T00:00:00Z")` | TTL / expiry tests |

**Key principle:** Never mock what you are testing. Mock only the **boundary** (DB, HTTP, filesystem, time).

---

## 6. Priority Order

| Priority | File | Rationale |
|---|---|---|
| **P1** | `tests/conftest.py` | Unblocks all other tests |
| **P1** | `tests/unit/test_policy.py` | Security-critical; pure logic; fast to write |
| **P1** | `tests/unit/test_authorization.py` | Security-critical; pure logic |
| **P1** | `tests/unit/test_auth.py` | JWT creation/validation is the auth boundary |
| **P1** | `tests/unit/test_dependencies.py` | `get_current_user` called on every protected route |
| **P2** | `tests/unit/test_settings.py` | `all_asoc_endpoints()` has complex branching logic |
| **P2** | `tests/unit/test_schedule_utils.py` | Pure logic; unblocks scheduler tests |
| **P2** | `tests/unit/test_postgres_store.py` | Repository layer; high coverage impact |
| **P2** | `tests/unit/test_report_artifacts.py` | Path traversal security check |
| **P3** | `tests/unit/test_asoc_read_service.py` | Largest module; highest coverage gain |
| **P3** | `tests/unit/test_multi_endpoint.py` | Aggregation logic; error resilience |
| **P3** | `tests/unit/test_report_scheduler.py` | Retry/backoff logic |
| **P3** | `tests/unit/test_analytics_prewarm.py` | Worker lifecycle |
| **P4** | `tests/unit/routes/test_route_auth.py` | Auth routes |
| **P4** | `tests/unit/routes/test_route_dashboard.py` | Most complex route; CRUD + versions |
| **P4** | `tests/unit/routes/test_route_audit.py` | Pagination contract |
| **P4** | `tests/unit/routes/test_route_reports.py` | Schedule + artifact download |
| **P4** | `tests/unit/routes/test_route_analytics.py` | Cache key + filter normalization |
| **P5** | `tests/unit/routes/test_route_applications.py` | Simple proxy route |
| **P5** | `tests/unit/routes/test_route_asset_groups.py` | Simple proxy route |
| **P5** | `tests/unit/routes/test_route_issues.py` | Simple proxy route |
| **P5** | `tests/unit/routes/test_route_scans.py` | Diagnostics endpoint |
| **P5** | `tests/unit/routes/test_route_pipeline_bom.py` | Stub endpoint; minimal logic |

---

## 7. Coverage Targets

| Module group | Target | Rationale |
|---|---|---|
| `app/core/security/` | **>= 90%** | Auth boundary — highest risk |
| `app/repositories/postgres_store.py` | **>= 85%** | All CRUD paths must be exercised |
| `app/services/asoc_read_service.py` | **>= 80%** | Complex normalization logic |
| `app/services/multi_endpoint.py` | **>= 85%** | Error resilience paths |
| `app/services/report_artifacts.py` | **>= 90%** | Path traversal security |
| `app/workers/` | **>= 80%** | Retry/backoff logic |
| `app/api/v1/routes/` | **>= 75%** | Route-level RBAC enforcement |
| `app/core/config/settings.py` | **>= 85%** | `all_asoc_endpoints()` branching |
| **Overall** | **>= 80%** | Enforced by `fail_under = 80` in `pyproject.toml` |

### Running Coverage

```bash
# From backend/ directory
pip install -e ".[dev]"
pytest --cov=app --cov-report=term-missing --cov-report=html tests/unit/
```

### CI Gate

```yaml
- name: Run unit tests with coverage
  run: |
    cd backend
    pip install -e ".[dev]"
    pytest --cov=app --cov-fail-under=80 tests/unit/
```

---

*Full fixture code and route test details are in [`plans/PLAN_part2.md`](plans/PLAN_part2.md).*