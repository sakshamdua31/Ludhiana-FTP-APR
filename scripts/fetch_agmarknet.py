"""Fetch Ludhiana mandi prices by fetching commodity-wise + date-wise from Agmarknet."""
import json
import os
import re
import sys
import time
import http.client
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

API_KEY  = os.environ["DATA_GOV_KEY"]
RESOURCE = "35985678-0d79-46b4-9ed6-6f13308a1d24"
BASE_URL = f"https://api.data.gov.in/resource/{RESOURCE}"
STATE    = "Punjab"
DISTRICT = "Ludhiana"
FETCH_LIMIT    = 500
MAX_LOOKBACK   = 7      # only check last 3 days for new data
OUT_PATH = Path("data/mandi/ludhiana.json")

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


def fetch_page(commodity, arrival_date_str, offset):
    """Fetch one page of records for a commodity + specific date."""
    params = urllib.parse.urlencode({
        "api-key": API_KEY,
        "format":  "json",
        "limit":   FETCH_LIMIT,
        "offset":  offset,
        "filters[commodity]": commodity,
        "filters[arrival_date]": arrival_date_str,
    })
    url = f"{BASE_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "AgriDashboard/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def fetch_commodity_date_ludhiana(commodity, arrival_date_str):
    """Fetch all records for a commodity on a specific date, keep only Ludhiana."""
    ludhiana_rows = []
    offset = 0
    for attempt in range(1, 4):
        try:
            while True:
                data = fetch_page(commodity, arrival_date_str, offset)
                records = data.get("records", [])
                # Normalize field names to lowercase (variety-wise dataset returns
                # "State", "Market", "Arrival_Date" etc.; downstream code expects
                # "state", "market", "arrival_date").
                records = [{k.lower(): v for k, v in r.items()} for r in records]
                for r in records:
                    if (r.get("state") or "").strip() == STATE and \
                       (r.get("district") or "").strip() == DISTRICT:
                        ludhiana_rows.append(r)
                total = int(data.get("total", 0))
                fetched = offset + len(records)
                if fetched >= total or not records:
                    return ludhiana_rows
                offset += FETCH_LIMIT
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                http.client.IncompleteRead, ConnectionError, OSError) as e:
            wait = 5 * attempt
            print(f"      attempt {attempt} failed ({type(e).__name__}); retrying in {wait}s", flush=True)
            time.sleep(wait)
            offset = 0
            ludhiana_rows = []
    print(f"      giving up on {commodity} {arrival_date_str} after 3 attempts", flush=True)
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


def get_fetch_dates():
    """Always fetch the last MAX_LOOKBACK days."""
    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).date()
    dates = []
    for i in range(MAX_LOOKBACK):
        d = today - timedelta(days=i)
        dates.append(d.strftime("%d/%m/%Y"))
    return dates


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

    for crop, dates in new_grouped.items():
        existing.setdefault(crop, {})
        for dt, rows in dates.items():
            existing[crop][dt] = rows
    return existing, {**existing_labels, **new_labels}


def main():
    print("Fetching Ludhiana data (commodity + date filtered) from Agmarknet", flush=True)

    fetch_dates = get_fetch_dates()
    print(f"Fetching dates: {', '.join(fetch_dates)}", flush=True)

    grouped = {}
    labels  = {}
    total_rows = 0

    for commodity in COMMODITIES:
        print(f"[{commodity}] fetching...", flush=True)
        crop_key = slugify(commodity)
        labels[crop_key] = commodity
        crop_rows = 0

        for date_str in fetch_dates:
            rows = fetch_commodity_date_ludhiana(commodity, date_str)
            for r in rows:
                date_iso, row = to_row(r)
                if date_iso:
                    grouped.setdefault(crop_key, {}).setdefault(date_iso, []).append(row)
                    crop_rows += 1
                    total_rows += 1
            time.sleep(0.5)

        if crop_rows:
            print(f"  {commodity}: {crop_rows} rows", flush=True)
        time.sleep(1)

    print(f"\nTotal Ludhiana rows: {total_rows} across {len(grouped)} commodities", flush=True)

    merged, all_labels = merge_with_existing(grouped, labels)

    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    output = dict(merged)
    output["_labels"]   = all_labels
    output["updated"]   = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
    output["source"]    = "AGMARKNET via data.gov.in"
    output["district"]  = DISTRICT
    output["state"]     = STATE

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
