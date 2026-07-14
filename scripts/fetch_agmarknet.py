"""Fetch ALL commodities from Ludhiana mandis via data.gov.in Agmarknet."""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

API_KEY   = os.environ["DATA_GOV_KEY"]
RESOURCE  = "9ef84268-d588-465a-a308-a864a43d0070"
BASE_URL  = f"https://api.data.gov.in/resource/{RESOURCE}"
STATE     = "Punjab"
DISTRICT  = "Ludhiana"
RETENTION_DAYS = 30
OUT_PATH  = Path("data/mandi/ludhiana.json")


def slugify(name: str) -> str:
    """Turn 'Paddy(Dhan)(Common)' into 'paddy_dhan_common'."""
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", " ", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s or "unknown"


def fetch_all():
    """Paginate through all Ludhiana rows, with retries on timeout."""
    all_records = []
    offset = 0
    limit  = 1000

    while True:
        params = {
            "api-key": API_KEY,
            "format":  "json",
            "limit":   limit,
            "offset":  offset,
            "filters[state]":    STATE,
            "filters[district]": DISTRICT,
        }

        payload = None
        for attempt in range(1, 6):
            try:
                r = requests.get(BASE_URL, params=params, timeout=90)
                r.raise_for_status()
                payload = r.json()
                break
            except (requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.HTTPError) as e:
                wait = 5 * attempt
                print(f"  attempt {attempt} failed ({type(e).__name__}: {e}); "
                      f"retrying in {wait}s…", flush=True)
                time.sleep(wait)
        if payload is None:
            raise RuntimeError(f"All 5 attempts to data.gov.in failed at offset={offset}")

        records = payload.get("records", [])
        if not records:
            break
        all_records.extend(records)
        if len(records) < limit:
            break
        offset += limit

    return all_records


def _to_int(x):
    try: return int(float(x))
    except (TypeError, ValueError): return None


def transform(records):
    """Group into {crop_slug: {date: [row, ...]}} — no commodity whitelist."""
    grouped = {}
    labels  = {}
    for rec in records:
        commodity = (rec.get("commodity") or "").strip()
        if not commodity:
            continue
        crop_key = slugify(commodity)
        labels[crop_key] = commodity

        date = (rec.get("arrival_date") or "").strip()
        try:
            date_iso = datetime.strptime(date, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue

        row = {
            "market":       (rec.get("market") or "").strip(),
            "state":        (rec.get("state") or "").strip(),
            "district":     (rec.get("district") or "").strip(),
            "commodity":    commodity,
            "variety":      (rec.get("variety") or "").strip(),
            "grade":        (rec.get("grade") or "").strip(),
            "modal_price":  _to_int(rec.get("modal_price")),
            "min_price":    _to_int(rec.get("min_price")),
            "max_price":    _to_int(rec.get("max_price")),
            "arrival_date": date_iso,
        }
        grouped.setdefault(crop_key, {}).setdefault(date_iso, []).append(row)
    return grouped, labels


def merge_with_existing(new_data, new_labels):
    """Load existing file, merge new dates in, prune old dates beyond retention."""
    existing = {}
    existing_labels = {}
    if OUT_PATH.exists():
        try:
            prev = json.loads(OUT_PATH.read_text(encoding="utf-8"))
            existing_labels = prev.get("_labels", {})
            for k, v in prev.items():
                if isinstance(v, dict) and any(isinstance(x, list) for x in v.values()):
                    existing[k] = v
        except json.JSONDecodeError:
            pass

    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).date().isoformat()
    for crop, dates in new_data.items():
        existing.setdefault(crop, {})
        for date, rows in dates.items():
            existing[crop][date] = rows
        existing[crop] = {d: rows for d, rows in existing[crop].items() if d >= cutoff}

    labels = {**existing_labels, **new_labels}
    return existing, labels


def main():
    print(f"Fetching {STATE}/{DISTRICT} from Agmarknet…", flush=True)
    records = fetch_all()
    print(f"  received {len(records)} raw records", flush=True)

    grouped, labels = transform(records)
    print(f"  commodities found: {sorted(labels.values())}", flush=True)

    merged, all_labels = merge_with_existing(grouped, labels)

    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    output = dict(merged)
    output["_labels"]        = all_labels
    output["updated"]        = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
    output["source"]         = "AGMARKNET via data.gov.in"
    output["retention_days"] = RETENTION_DAYS
    output["district"]       = DISTRICT
    output["state"]          = STATE

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote {OUT_PATH}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
