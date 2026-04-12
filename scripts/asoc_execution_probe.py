"""
ASoC Execution Detail Probe
- Authenticates, fetches scans, probes SastExecution / DastExecution / SCAExecution endpoints
- Reports all fields relevant to: duration, SAST size, SCA size, DAST page coverage
"""
import httpx
import sys

BASE = "https://cloud.appscan.com"
KEY_ID = "6ca5b207-406b-8fd7-1b9a-a74cfd1c9deb"
KEY_SECRET = "SCLq1NYsDcG46m1cLscNcaI0YCrT0kHO6zXp6cwdpixa"


def login():
    r = httpx.post(
        f"{BASE}/api/v4/Account/ApiKeyLogin",
        json={"KeyId": KEY_ID, "KeySecret": KEY_SECRET},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("Token")


def get_scans(token, top=200):
    H = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    r = httpx.get(f"{BASE}/api/v4/Scans", params={"$top": top, "$skip": 0}, headers=H, timeout=30)
    r.raise_for_status()
    return r.json().get("Items", []), H


def classify(raw):
    by_type = {"SAST": [], "SCA": [], "DAST": []}
    for s in raw:
        st = str(s.get("Technology", "") or "").upper()
        if "SAST" in st or "STATIC" in st:
            by_type["SAST"].append(s)
        elif "SCA" in st:
            by_type["SCA"].append(s)
        elif "DAST" in st or "DYNAMIC" in st:
            by_type["DAST"].append(s)
    return by_type


def get_exec(url, H):
    try:
        r = httpx.get(url, headers=H, timeout=15)
        if r.status_code == 200:
            return r.status_code, r.json()
        return r.status_code, r.text[:300]
    except Exception as e:
        return 0, str(e)


def interesting_keys(payload, tokens):
    if not isinstance(payload, dict):
        return {}
    return {k: v for k, v in payload.items() if any(t in k.lower() for t in tokens) and v is not None}


def probe_type(label, scans, H, endpoint_fmt, field_tokens, max_scans=5):
    print(f"\n{'='*60}")
    print(f"  {endpoint_fmt}  ({label}, probing {min(max_scans, len(scans))} scans)")
    print(f"{'='*60}")
    found_any = False
    for scan in scans[:max_scans]:
        le = scan.get("LatestExecution") or {}
        exec_id = le.get("Id")
        scan_id = scan.get("Id")
        name = (scan.get("Name") or "?")[:50]
        print(f"\n  Scan: {name}")
        print(f"  ScanId={scan_id}  ExecId={exec_id}")
        # LatestExecution embedded fields
        le_interesting = interesting_keys(le, field_tokens)
        print(f"  [LatestExecution embedded] {le_interesting}")
        if not exec_id:
            print("  -- No executionId, skipping endpoint call")
            continue
        url = f"{BASE}{endpoint_fmt.replace('{executionId}', exec_id)}"
        status, payload = get_exec(url, H)
        if status != 200:
            print(f"  HTTP {status}: {str(payload)[:200]}")
            continue
        found_any = True
        all_keys = sorted(payload.keys()) if isinstance(payload, dict) else []
        if_interesting = interesting_keys(payload, field_tokens)
        print(f"  [Endpoint all keys] {all_keys}")
        print(f"  [Interesting fields] {if_interesting}")
    if not found_any:
        print("  (No successful endpoint responses)")


def sca_packages_summary(scans):
    print("\n" + "="*60)
    print("  SCA: NOpenSourcePackages in LatestExecution (package count proxy)")
    print("="*60)
    with_pkgs = []
    for s in scans:
        le = s.get("LatestExecution") or {}
        pkgs = le.get("NOpenSourcePackages")
        if pkgs is not None and pkgs > 0:
            with_pkgs.append((s.get("Name", "?")[:50], pkgs))
    print(f"  {len(with_pkgs)}/{len(scans)} SCA scans have NOpenSourcePackages > 0")
    for name, p in sorted(with_pkgs, key=lambda x: -x[1])[:10]:
        print(f"    {name}: {p}")


def duration_summary(by_type):
    print("\n" + "="*60)
    print("  Duration Summary (from LatestExecution.ExecutionDurationSec)")
    print("="*60)
    for label in ["SAST", "SCA", "DAST"]:
        scans = by_type[label]
        durs = []
        for s in scans:
            le = s.get("LatestExecution") or {}
            d = le.get("ExecutionDurationSec")
            if d and d > 0:
                durs.append(d)
        b = dict(lt5=0, m5_10=0, m10_30=0, m30_60=0, m60_120=0, m120_240=0, m240_300=0, gte300=0)
        for d in durs:
            m = d / 60
            if m < 5:
                b["lt5"] += 1
            elif m < 10:
                b["m5_10"] += 1
            elif m < 30:
                b["m10_30"] += 1
            elif m < 60:
                b["m30_60"] += 1
            elif m < 120:
                b["m60_120"] += 1
            elif m < 240:
                b["m120_240"] += 1
            elif m < 300:
                b["m240_300"] += 1
            else:
                b["gte300"] += 1
        print(f"  {label} ({len(durs)}/{len(scans)} non-zero): {b}")


def dast_scan_detail_probe(scans, H, max_scans=5):
    """Also probe /api/v4/Scans/{scan_id} and /api/v4/Scans/{scan_id}/LatestExecution for DAST."""
    print("\n" + "="*60)
    print("  DAST: /api/v4/Scans/{scan_id} and /api/v4/Scans/{scan_id}/LatestExecution")
    print("="*60)
    page_tokens = ["page", "url", "crawl", "visit", "discover", "scan", "tested", "found"]
    for scan in scans[:max_scans]:
        scan_id = scan.get("Id")
        name = (scan.get("Name") or "?")[:50]
        print(f"\n  Scan: {name}  (id={scan_id})")
        for suffix in ["", "/LatestExecution", "/Statistics"]:
            url = f"{BASE}/api/v4/Scans/{scan_id}{suffix}"
            status, payload = get_exec(url, H)
            label = "/" + suffix.lstrip("/") if suffix else "(base)"
            if status != 200:
                print(f"    {label}: HTTP {status}")
                continue
            if_interesting = interesting_keys(payload, page_tokens)
            all_k = sorted(payload.keys()) if isinstance(payload, dict) else []
            print(f"    {label}: all_keys={all_k}")
            print(f"    {label}: page-related={if_interesting}")


def main():
    print("Authenticating...")
    token = login()
    print(f"Token: {token[:15]}...")

    print("\nFetching 200 scans...")
    raw, H = get_scans(token, 200)
    print(f"Fetched: {len(raw)} scans")
    by_type = classify(raw)
    print(f"SAST={len(by_type['SAST'])} SCA={len(by_type['SCA'])} DAST={len(by_type['DAST'])}")

    # Duration summary from embedded LatestExecution
    duration_summary(by_type)

    # SCA packages
    sca_packages_summary(by_type["SCA"])

    # SAST execution endpoint
    probe_type(
        "SAST", by_type["SAST"], H,
        "/api/v4/Scans/SastExecution/{executionId}",
        ["file", "size", "lines", "loc", "source", "target", "nfiles", "duration", "sec", "minute"],
        max_scans=3,
    )

    # SCA execution endpoint
    probe_type(
        "SCA", by_type["SCA"], H,
        "/api/v4/Scans/SCAExecution/{executionId}",
        ["package", "lib", "depend", "module", "component", "artifact", "open", "duration", "sec"],
        max_scans=3,
    )

    # DAST execution endpoint
    probe_type(
        "DAST", by_type["DAST"], H,
        "/api/v4/Scans/DastExecution/{executionId}",
        ["page", "url", "crawl", "visit", "discover", "duration", "sec"],
        max_scans=5,
    )

    # DAST scan-level detail endpoints
    dast_scan_detail_probe(by_type["DAST"], H, max_scans=3)

    print("\n\nDone.")


if __name__ == "__main__":
    main()
