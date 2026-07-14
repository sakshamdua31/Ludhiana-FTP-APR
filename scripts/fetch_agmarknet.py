"""Fetch Ludhiana mandi prices by fetching commodity-wise from Agmarknet, then filtering."""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

API_KEY  = os.environ["DATA_GOV_KEY"]
RESOURCE = "9ef84268-d588-465a-a308-a864a43d0070"
BASE_URL = f"https://api.data.gov.in/resource/{RESOURCE}"
STATE    = "Punjab"
DISTRICT = "Ludhiana"
RETENTION_DAYS = 30
FETCH_LIMIT    = 500
OUT_PATH = Path("data/mandi/ludhiana.json")

# Broad commodity list. We fetch each by name (reliable), then filter to Ludhiana.
# Add or remove commodities freely — script auto-slugs the labels.
COMMODITIES = [
    "Paddy(Dhan)(Common)", "Basmati Paddy", "Wheat", "Maize",
    "Bengal Gram(Gram)(Whole)", "Arhar (Tur/Red Gram)(Whole)",
    "Sugarcane", "Onion", "Potato", "Tomato", "Cauliflower", "Cabbage",
    "Bhindi(Ladies Finger)", "Brinjal", "Cucumbar(Kheera)", "Pumpkin",
    "Ridgeguard(Tori)", "Bottle gourd", "Green Chilli",
    "Mustard", "Soyabean", "Groundnut", "Sunflower",
    "Apple", "Banana", "Pomegranate", "Mango", "Guava",
    "Jamun(Narale Hannu)", "Papaya", "Peach", "Plum", "Pear",
    "Lemon", "Green Peas", "Cotton", "Rice",
]


def slugify(name):
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", " ", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s or "unknown"


def fetch_page(commodity, offset):
    """Fetch one page of records for a commodity."""
    params = urllib.parse.urlencode({
        "api-key": API_KEY,
        "format":  "json",
        "limit":   FETCH_LIMIT,
        "offset":  offset,
        "filters[commodity]": commodity,
    })
    url = f"{BASE_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "AgriDashboard/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_commodity_ludhiana(commodity):
    """Paginate through commodity data, keep only Ludhiana rows."""
    ludhiana_rows = []
    offset = 0
    for attempt in range(1, 5):
        try:
            while True:
                data = fetch_page(commodity, offset)
                records = data.get("records", [])
                for r in records:
                    if (r.get("state") or "").strip() == STATE and \
                       (r.get("district") or "").strip() == DISTRICT:
                        ludhiana_rows.append(r)
                total = int(data.get("total", 0))
                fetched = offset + len(records)
                if fetched >= total or not records:
                    return ludhiana_rows
                offset += FETCH_LIMIT
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            wait = 5 * attempt
            print(f"    attempt {attempt} failed ({type(e).__name__}); retrying in {wait}s…", flush=True)
            time.sleep(wait)
    return ludhiana_rows


def _to_int(x):
    try: return int(float(x))
    except (TypeError, ValueError): return None


def to_row(rec):
    date_raw = (rec.get("arrival_date") or "").strip()
    try:
        date_iso = datetime.strptime(date_raw, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None, None
    return date_iso, {
        "market":       (rec.get("market") or "").strip(),
        "state":        (rec.get("state") or "").strip(),
        "district":     (rec.get("district") or "").strip(),
        "commodity":    (rec.get("commodity") or "").strip(),
        "variety":      (rec.get("variety") or "").strip(),
        "grade":        (rec.get("grade") or "").strip(),
        "modal_price":  _to_int(rec.get("modal_price")),
        "min_price":    _to_int(rec.get("min_price")),
        "max_price":    _to_int(rec.get("max_price")),
        "arrival_date": date_iso,
    }


def merge_with_existing(new_grouped, new_labels):
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
    for crop, dates in new_grouped.items():
        existing.setdefault(crop, {})
        for date, rows in dates.items():
            existing[crop][date] = rows
        existing[crop] = {d: rows for d, rows in existing[crop].items() if d >= cutoff}
    return existing, {**existing_labels, **new_labels}


def main():
    print(f"Fetching Ludhiana data commodity-by-commodity from Agmarknet…", flush=True)

    grouped = {}
    labels  = {}
    total_rows = 0

    for commodity in COMMODITIES:
        print(f"  → {commodity}", flush=True)
        rows = fetch_commodity_ludhiana(commodity)
        if not rows:
            continue
        crop_key = slugify(commodity)
        labels[crop_key] = commodity
        for r in rows:
            date_iso, row = to_row(r)
            if date_iso:
                grouped.setdefault(crop_key, {}).setdefault(date_iso, []).append(row)
                total_rows += 1
        print(f"      kept {len(rows)} Ludhiana rows", flush=True)
        time.sleep(2)   # be nice to the API

    print(f"\nTotal Ludhiana rows: {total_rows} across {len(grouped)} commodities", flush=True)

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
    print(f"Wrote {OUT_PATH}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
