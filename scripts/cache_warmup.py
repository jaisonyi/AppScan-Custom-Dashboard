from __future__ import annotations

import json
import time
import urllib.request

BASE_URL = "http://127.0.0.1:8000"


def _post_json(path: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(path: str, token: str, timeout: int) -> tuple[dict, float]:
    req = urllib.request.Request(
        BASE_URL + path,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    started = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    elapsed = time.time() - started
    return payload, elapsed


def main() -> None:
    login_payload = {
        "username": "admin",
        "role": "SecurityManager",
        "asset_group_ids": ["ag-1", "ag-2"],
    }
    token = _post_json("/api/v1/auth/login", login_payload).get("access_token", "")
    if not token:
        raise RuntimeError("Failed to obtain access token")

    print("warmup_start")
    warm_payload, warm_elapsed = _get_json(
        "/api/v1/analytics/portfolio-summary?refresh=true", token, timeout=1800
    )
    print(f"warmup_http=200 warmup_time={warm_elapsed:.3f}")

    print("cache_verify_start")
    cache_payload, cache_elapsed = _get_json(
        "/api/v1/analytics/portfolio-summary", token, timeout=120
    )
    print(f"cache_http=200 cache_time={cache_elapsed:.3f}")

    keys = [
        "applications_total",
        "asset_groups_total",
        "issues_total",
        "issues_active",
        "scans_total",
    ]
    warm_totals = {key: warm_payload.get(key) for key in keys}
    cache_totals = {key: cache_payload.get(key) for key in keys}

    print("warmup_totals", json.dumps(warm_totals, sort_keys=True))
    print("cache_totals", json.dumps(cache_totals, sort_keys=True))


if __name__ == "__main__":
    main()
