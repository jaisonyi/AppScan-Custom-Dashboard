from __future__ import annotations


def scans() -> list[dict]:
    # Representative mock scans that exercise all three bucket-trend charts:
    #   • duration_seconds  → Scan Time Bucket Trends
    #   • NVisitedPages     → DAST Page Coverage Bucket Trends  (picked up by _extract_scan_page_coverage)
    #   • nFiles            → SAST target-size proxy            (picked up by _extract_sast_size_profile)
    #   • nPackages         → SCA  target-size proxy            (picked up by _extract_sca_size_profile)
    # created_at values span three months so the "month" period generates ≥1 data point per month.
    return [
        {
            "id": "s-1",
            "name": "Portal-SAST-Nightly",
            "status": "Completed",
            "ScanType": "SAST",
            "asset_group_id": "ag-1",
            "ApplicationId": "app-1",
            "ApplicationName": "Payments API",
            "CreatedAt": "2025-01-15T02:00:00Z",
            "DurationSeconds": 420,
            "nFiles": 340,
        },
        {
            "id": "s-2",
            "name": "Portal-SCA-Weekly",
            "status": "Completed",
            "ScanType": "SCA",
            "asset_group_id": "ag-1",
            "ApplicationId": "app-1",
            "ApplicationName": "Payments API",
            "CreatedAt": "2025-01-22T03:00:00Z",
            "DurationSeconds": 185,
            "nPackages": 210,
        },
        {
            "id": "s-3",
            "name": "Portal-DAST-Weekly",
            "status": "Completed",
            "ScanType": "DAST",
            "asset_group_id": "ag-1",
            "ApplicationId": "app-1",
            "ApplicationName": "Payments API",
            "CreatedAt": "2025-01-28T04:00:00Z",
            "DurationSeconds": 3600,
            "NVisitedPages": 420,
        },
        {
            "id": "s-4",
            "name": "API-SAST-Feb",
            "status": "Completed",
            "ScanType": "SAST",
            "asset_group_id": "ag-2",
            "ApplicationId": "app-2",
            "ApplicationName": "Portal Web",
            "CreatedAt": "2025-02-10T02:00:00Z",
            "ExecutionMinutes": 18,
            "nFiles": 870,
        },
        {
            "id": "s-5",
            "name": "API-DAST-Feb",
            "status": "Completed",
            "ScanType": "DAST",
            "asset_group_id": "ag-2",
            "ApplicationId": "app-2",
            "ApplicationName": "Portal Web",
            "CreatedAt": "2025-02-20T06:00:00Z",
            "DurationSeconds": 7200,
            "NVisitedPages": 1150,
        },
        {
            "id": "s-6",
            "name": "API-SCA-Mar",
            "status": "Completed",
            "ScanType": "SCA",
            "asset_group_id": "ag-2",
            "ApplicationId": "app-2",
            "ApplicationName": "Portal Web",
            "CreatedAt": "2025-03-05T02:00:00Z",
            "DurationSeconds": 95,
            "nPackages": 530,
        },
        {
            "id": "s-7",
            "name": "Payments-SAST-Mar",
            "status": "Completed",
            "ScanType": "SAST",
            "asset_group_id": "ag-1",
            "ApplicationId": "app-1",
            "ApplicationName": "Payments API",
            "CreatedAt": "2025-03-18T03:00:00Z",
            "ExecutionMinutes": 45,
            "nFiles": 1200,
        },
        {
            "id": "s-8",
            "name": "Payments-DAST-Mar",
            "status": "Completed",
            "ScanType": "DAST",
            "asset_group_id": "ag-1",
            "ApplicationId": "app-1",
            "ApplicationName": "Payments API",
            "CreatedAt": "2025-03-25T05:00:00Z",
            "DurationSeconds": 14400,
            "NVisitedPages": 87,
        },
    ]


def applications() -> list[dict]:
    return [
        {"id": "app-1", "name": "Payments API", "asset_group_id": "ag-1"},
        {"id": "app-2", "name": "Portal Web", "asset_group_id": "ag-2"},
    ]


def asset_groups() -> list[dict]:
    return [
        {"id": "ag-1", "name": "Finance"},
        {"id": "ag-2", "name": "Retail"},
    ]


def issues() -> list[dict]:
    return [
        {"id": "iss-1", "severity": "High", "mttr_days": 7, "asset_group_id": "ag-1"},
        {"id": "iss-2", "severity": "Medium", "mttr_days": 12, "asset_group_id": "ag-2"},
    ]
