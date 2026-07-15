"""
Fetch PAU advisories from Google Drive links listed in links.txt,
extract text from PDFs, categorize by topic (English + Punjabi),
consolidate into one JSON file. No scraping, no AI, no Playwright.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from io import BytesIO

try:
    import pdfplumber
except ImportError:
    os.system("pip install pdfplumber --break-system-packages -q")
    import pdfplumber

# --- Config ---
LINKS_PATH = Path("data/advisory/links.txt")
OUT_PATH = Path("data/advisory/pau_advisory.json")
HEADERS = {"User-Agent": "ArcusPolicyResearch/1.0"}

CROP_KEYWORDS = [
    "rice", "paddy", "basmati", "cotton", "narma", "sugarcane",
    "maize", "corn", "moong", "mungbean", "mung", "mash", "urad", "urdbean",
    "groundnut", "peanut", "soybean", "soyabean", "bajra", "pearl millet",
    "vegetables", "vegetable crops", "fruit", "fruits", "orchard", "orchards",
    "fodder", "pulses", "oilseeds", "potato", "onion", "tomato",
    "wheat", "mustard", "rapeseed", "sunflower", "guava", "kinnow", "citrus",
    "ਝੋਨਾ", "ਧਾਨ", "ਬਾਸਮਤੀ", "ਕਣਕ", "ਨਰਮਾ", "ਕਪਾਹ", "ਗੰਨਾ", "ਮੱਕੀ",
    "ਮੂੰਗੀ", "ਮਾਂਹ", "ਮੂੰਗਫਲੀ", "ਸੋਇਆਬੀਨ", "ਬਾਜਰਾ",
    "ਸਬਜ਼ੀਆਂ", "ਸਬਜ਼ੀ", "ਫਲ", "ਚਾਰਾ", "ਦਾਲਾਂ", "ਤੇਲ ਬੀਜ",
    "ਆਲੂ", "ਪਿਆਜ਼", "ਟਮਾਟਰ", "ਸਰ੍ਹੋਂ", "ਰਾਇਆ", "ਸੂਰਜਮੁਖੀ", "ਅਮਰੂਦ", "ਕਿੰਨੂ",
]

CROP_NAME_MAP = {
    "ਝੋਨਾ": "Rice (ਝੋਨਾ)", "ਧਾਨ": "Rice (ਧਾਨ)", "ਬਾਸਮਤੀ": "Basmati (ਬਾਸਮਤੀ)",
    "ਕਣਕ": "Wheat (ਕਣਕ)", "ਨਰਮਾ": "Cotton (ਨਰਮਾ)", "ਕਪਾਹ": "Cotton (ਕਪਾਹ)",
    "ਗੰਨਾ": "Sugarcane (ਗੰਨਾ)", "ਮੱਕੀ": "Maize (ਮੱਕੀ)", "ਮੂੰਗੀ": "Moong (ਮੂੰਗੀ)",
    "ਮਾਂਹ": "Urad (ਮਾਂਹ)", "ਮੂੰਗਫਲੀ": "Groundnut (ਮੂੰਗਫਲੀ)",
    "ਸੋਇਆਬੀਨ": "Soybean (ਸੋਇਆਬੀਨ)", "ਬਾਜਰਾ": "Bajra (ਬਾਜਰਾ)",
    "ਸਬਜ਼ੀਆਂ": "Vegetables (ਸਬਜ਼ੀਆਂ)", "ਸਬਜ਼ੀ": "Vegetables (ਸਬਜ਼ੀ)",
    "ਫਲ": "Fruits (ਫਲ)", "ਚਾਰਾ": "Fodder (ਚਾਰਾ)", "ਦਾਲਾਂ": "Pulses (ਦਾਲਾਂ)",
    "ਤੇਲ ਬੀਜ": "Oilseeds (ਤੇਲ ਬੀਜ)", "ਆਲੂ": "Potato (ਆਲੂ)",
    "ਪਿਆਜ਼": "Onion (ਪਿਆਜ਼)", "ਟਮਾਟਰ": "Tomato (ਟਮਾਟਰ)",
    "ਸਰ੍ਹੋਂ": "Mustard (ਸਰ੍ਹੋਂ)", "ਰਾਇਆ": "Mustard (ਰਾਇਆ)",
    "ਸੂਰਜਮੁਖੀ": "Sunflower (ਸੂਰਜਮੁਖੀ)", "ਅਮਰੂਦ": "Guava (ਅਮਰੂਦ)",
    "ਕਿੰਨੂ": "Kinnow (ਕਿੰਨੂ)",
}


# ============================================================
# READ LINKS FILE
# ============================================================

def read_links():
    """Read links.txt and return list of link entries."""
    if not LINKS_PATH.exists():
        print(f"ERROR: {LINKS_PATH} not found.", flush=True)
        return []

    entries = []
    for line_num, line in enumerate(LINKS_PATH.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            print(f"  WARNING: line {line_num} has {len(parts)} parts, expected 4. Skipping: {line}", flush=True)
            continue

        doc_type, issue_num, date_str, drive_url = parts[0], parts[1], parts[2], parts[3]
        file_id = extract_drive_id(drive_url)
        if not file_id:
            print(f"  WARNING: line {line_num} has invalid Google Drive URL. Skipping.", flush=True)
            continue

        entries.append({
            "type": doc_type,
            "issue_number": issue_num,
            "date": date_str,
            "drive_url": drive_url,
            "drive_file_id": file_id,
            "file_id": f"{doc_type}_{issue_num}_{date_str}",
        })

    return entries


def extract_drive_id(url):
    """Extract the file ID from a Google Drive URL."""
    m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
    return m.group(1) if m else None


# ============================================================
# DOWNLOAD FROM GOOGLE DRIVE
# ============================================================

def download_from_drive(file_id):
    """Download a PDF from Google Drive using direct download URL."""
    download_url = f"https://drive.google.com/uc?id={file_id}&export=download"
    print(f"    Downloading from Google Drive: {file_id[:20]}...", flush=True)

    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(download_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                content_type = resp.headers.get("Content-Type", "")

                # Google Drive sometimes shows a confirmation page for large files
                if b"confirm=" in data or b"virus scan warning" in data.lower():
                    print(f"    Drive confirmation page detected, retrying with confirm...", flush=True)
                    confirm_match = re.search(rb'confirm=([0-9A-Za-z_-]+)', data)
                    if confirm_match:
                        confirm_url = f"{download_url}&confirm={confirm_match.group(1).decode()}"
                        req2 = urllib.request.Request(confirm_url, headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                        })
                        with urllib.request.urlopen(req2, timeout=60) as resp2:
                            data = resp2.read()

                # Verify we got a PDF
                if data[:4] == b'%PDF' or len(data) > 10000:
                    print(f"    Downloaded: {len(data):,} bytes", flush=True)
                    return data
                else:
                    print(f"    WARNING: Response doesn't look like a PDF ({len(data)} bytes, type: {content_type})", flush=True)
                    # Try alternate download method
                    alt_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download"
                    req3 = urllib.request.Request(alt_url, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    })
                    with urllib.request.urlopen(req3, timeout=60) as resp3:
                        data = resp3.read()
                        if data[:4] == b'%PDF' or len(data) > 10000:
                            print(f"    Downloaded (alt method): {len(data):,} bytes", flush=True)
                            return data

        except Exception as e:
            print(f"    download attempt {attempt} failed: {e}", flush=True)
            time.sleep(5 * attempt)

    return None


# ============================================================
# PDF TEXT EXTRACTION
# ============================================================

def extract_text_from_pdf(pdf_bytes):
    text_parts = []
    tables_found = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
                tables = page.extract_tables()
                for table in tables:
                    table_rows = []
                    for row in table:
                        if row:
                            cleaned = [str(cell).strip() for cell in row if cell]
                            if cleaned:
                                table_rows.append(cleaned)
                    if table_rows:
                        tables_found.append(table_rows)
    except Exception as e:
        print(f"    pdfplumber error: {e}", flush=True)
    return "\n\n".join(text_parts), tables_found


# ============================================================
# RULE-BASED PARSING (English + Punjabi)
# ============================================================

def parse_weather(full_text, tables):
    weather = {"outlook": "", "zone_data": [], "general_advice": ""}

    for pat in [
        r'(?:WEATHER\s*(?:CROP\s*)?OUTLOOK[:\s]*)(.*?)(?=\n\s*CROPS?[:\s]|\n\s*[A-Z][a-z]+\s*:)',
        r'(?:Weather\s*(?:Crop\s*)?Outlook[:\s]*)(.*?)(?=\n\s*Crops?[:\s]|\n\s*[A-Z][a-z]+\s*:)',
        r'(?:ਮੌਸਮ\s*(?:ਫ਼ਸਲ\s*)?ਸੰਭਾਵਨਾ[:\s]*)(.*?)(?=\n\s*ਫ਼ਸਲਾਂ[:\s])',
        r'(?:ਮੌਸਮ[:\s]*)(.*?)(?=\n\s*ਫ਼ਸਲ)',
    ]:
        m = re.search(pat, full_text, re.DOTALL | re.IGNORECASE)
        if m:
            weather["outlook"] = m.group(1).strip()
            break

    for table in tables:
        header = [str(c).lower() for c in table[0]] if table else []
        if any(w in " ".join(header) for w in ["zone", "weather", "temperature", "ਤਾਪਮਾਨ", "ਖੇਤਰ"]):
            for row in table[1:]:
                if len(row) >= 2:
                    param = row[0].strip() if row[0] else ""
                    for i, zone_name in enumerate(header[1:], 1):
                        if i < len(row) and row[i]:
                            zone_entry = next((z for z in weather["zone_data"] if z["zone"].lower() == zone_name.lower()), None)
                            if not zone_entry:
                                zone_entry = {"zone": zone_name.strip(), "max_temp": "", "min_temp": "", "morning_humidity": "", "evening_humidity": ""}
                                weather["zone_data"].append(zone_entry)
                            val = str(row[i]).strip()
                            pl = param.lower()
                            if ("max" in pl or "ਵੱਧ" in pl) and ("temp" in pl or "ਤਾਪਮਾਨ" in pl): zone_entry["max_temp"] = val
                            elif ("min" in pl or "ਘੱਟ" in pl) and ("temp" in pl or "ਤਾਪਮਾਨ" in pl): zone_entry["min_temp"] = val
                            elif ("morning" in pl or "ਸਵੇਰ" in pl) and ("humid" in pl or "ਨਮੀ" in pl): zone_entry["morning_humidity"] = val
                            elif ("evening" in pl or "ਸ਼ਾਮ" in pl) and ("humid" in pl or "ਨਮੀ" in pl): zone_entry["evening_humidity"] = val

    for pat in [
        r'((?:Farmers?\s+(?:are\s+)?advised?|Keep\s+proper\s+drainage|Remove\s+excess\s+rainwater).*?\.)',
        r'((?:ਕਿਸਾਨਾਂ\s+ਨੂੰ\s+ਸਲਾਹ|ਪਾਣੀ\s+ਦੀ\s+ਨਿਕਾਸੀ|ਬਾਰਿਸ਼\s+ਦਾ\s+ਪਾਣੀ).*?।)',
    ]:
        m = re.search(pat, full_text, re.DOTALL | re.IGNORECASE)
        if m:
            weather["general_advice"] = m.group(1).strip()
            break
    return weather


def detect_category(sentence):
    s = sentence.lower()

    irr = ["irrigation", "irrigat", "water standing", "ponded water", "drain", "waterlogg", "field capacity", "apply water",
           "ਸਿੰਚਾਈ", "ਪਾਣੀ ਲਗਾ", "ਪਾਣੀ ਦਿਓ", "ਪਾਣੀ ਖੜ੍ਹਾ", "ਨਿਕਾਸੀ", "ਪਾਣੀ ਕੱਢ", "ਪਾਣੀ ਦੇ", "ਪਾਣੀ ਨਾ ਖੜ੍ਹ"]
    if any(w in s for w in irr): return "irrigation"

    pest = ["spray", "insecticide", "pesticide", "fungicide", "whitefly", "borer", "hopper", "armyworm", "thrips",
            "aphid", "jassid", "mite", "mealy", "bollworm", "blight", "blast", "wilt", "rot", "rust", "smut",
            "mildew", "virus", "disease", "infected", "infestation", "flonicamid", "dinotefuran", "imidacloprid",
            "carbofuran", "fipronil", "chlorpyriphos", "trichoderma", "trap", "pheromone", "monitor",
            "ਛਿੜਕਾਅ", "ਕੀਟ", "ਕੀੜਾ", "ਕੀੜੇ", "ਕੀੜਿਆਂ", "ਬੀਮਾਰੀ", "ਰੋਗ", "ਬਿਮਾਰੀ",
            "ਚਿੱਟੀ ਮੱਖੀ", "ਚੇਪਾ", "ਤੇਲਾ", "ਸੁੰਡੀ", "ਗੁਲਾਬੀ ਸੁੰਡੀ", "ਅਮਰੀਕਨ ਸੁੰਡੀ",
            "ਗੋਭ ਦੀ ਸੁੰਡੀ", "ਤਣੇ ਦੀ ਸੁੰਡੀ", "ਪੱਤਾ ਲਪੇਟ", "ਫੁੱਲ ਕੀੜਾ",
            "ਫ਼ਫ਼ੂੰਦ", "ਉੱਲੀ", "ਝੁਲਸ", "ਕੁੰਗੀ", "ਕਾਂਗਿਆਰੀ", "ਗੇਰੂਈ",
            "ਦਵਾਈ", "ਸਪਰੇਅ", "ਜ਼ਹਿਰ", "ਪਾਇਰੀਲਾ", "ਮਿੱਲੀ ਬੱਗ", "ਜੜ੍ਹ ਗਲ", "ਤਣਾ ਗਲ",
            "ਅਗੇਤਾ ਝੁਲਸ", "ਪਿਛੇਤਾ ਝੁਲਸ", "ਕਾਲੀ ਕੁੰਗੀ", "ਭੂਰੀ ਕੁੰਗੀ", "ਪੀਲੀ ਕੁੰਗੀ"]
    if any(w in s for w in pest): return "pest_management"

    weed = ["weed", "herbicide", "atrazine", "butachlor", "pendimethalin", "pyrazosulfuron", "bispyribac",
            "pre-emergence", "post-emergence",
            "ਨਦੀਨ", "ਨਦੀਨਾਂ", "ਨਦੀਨ ਨਾਸ਼ਕ", "ਬੂਟੀ", "ਬੂਟੀਆਂ", "ਬੂਟੀ ਨਾਸ਼ਕ",
            "ਘਾਹ", "ਗੁੱਲੀ ਡੰਡਾ", "ਮੰਡੂਸੀ", "ਪਹਿਲਾਂ ਉੱਗਣ ਤੋਂ", "ਬਾਅਦ ਉੱਗਣ ਤੋਂ"]
    if any(w in s for w in weed): return "weed_management"

    fert = ["fertiliz", "urea", "dap", "nitrogen", "phospho", "potash", "zinc", "sulphate", "micronutrient",
            "nutrient", "deficiency", "basal dose", "top dress",
            "ਖਾਦ", "ਯੂਰੀਆ", "ਡੀ.ਏ.ਪੀ", "ਨਾਈਟ੍ਰੋਜਨ", "ਫ਼ਾਸਫ਼ੋਰਸ", "ਪੋਟਾਸ਼",
            "ਜ਼ਿੰਕ", "ਜ਼ਿੰਕ ਸਲਫ਼ੇਟ", "ਸੂਖ਼ਮ ਤੱਤ", "ਤੱਤ ਦੀ ਘਾਟ", "ਕਮੀ"]
    if any(w in s for w in fert): return "fertilizer"

    var = ["variety", "varieties", "sowing", "transplant", "nursery", "seed rate", "seed treatment",
           "pr-126", "pusa basmati", "pbw", "pb ",
           "ਕਿਸਮ", "ਕਿਸਮਾਂ", "ਬਿਜਾਈ", "ਲੁਆਈ", "ਪਨੀਰੀ", "ਬੀਜ", "ਬੀਜ ਦੀ ਮਾਤਰਾ", "ਬੀਜ ਸੋਧ", "ਰੋਪਾਈ"]
    if any(w in s for w in var): return "variety_sowing"

    harv = ["harvest", "picking", "maturity", "ripe", "ਕਟਾਈ", "ਵਾਢੀ", "ਤੁੜਾਈ", "ਪੱਕ"]
    if any(w in s for w in harv): return "harvesting"

    return "general"


def categorize_advice(text):
    advice = []
    sentences = re.split(r'(?<=[.।!])\s+', text)
    current_category = "general"
    current_detail = []
    for sent in sentences:
        sent = sent.strip()
        if not sent: continue
        cat = detect_category(sent)
        if cat != current_category and current_detail:
            advice.append({"category": current_category, "detail": " ".join(current_detail)})
            current_detail = []
        current_category = cat
        current_detail.append(sent)
    if current_detail:
        advice.append({"category": current_category, "detail": " ".join(current_detail)})
    return advice


def parse_crop_sections(full_text):
    crop_advisory = []
    crop_names_in_text = []
    for keyword in CROP_KEYWORDS:
        pattern = re.compile(r'(?:^|\n)\s*(' + re.escape(keyword) + r')\s*[:\-।]', re.IGNORECASE | re.MULTILINE)
        for m in pattern.finditer(full_text):
            crop_names_in_text.append((m.start(), m.group(1).strip()))

    crop_names_in_text.sort(key=lambda x: x[0])
    seen = set()
    unique_crops = []
    for pos, name in crop_names_in_text:
        nl = name.lower()
        if nl not in seen:
            seen.add(nl)
            unique_crops.append((pos, name))

    for i, (pos, crop_name) in enumerate(unique_crops):
        end = unique_crops[i + 1][0] if i + 1 < len(unique_crops) else len(full_text)
        section_text = full_text[pos:end].strip()
        section_text = re.sub(r'^' + re.escape(crop_name) + r'\s*[:\-।]\s*', '', section_text, flags=re.IGNORECASE).strip()
        if not section_text or len(section_text) < 20: continue
        display_name = CROP_NAME_MAP.get(crop_name, crop_name.strip().title())
        crop_advisory.append({
            "crop": display_name,
            "full_text": section_text,
            "advice": categorize_advice(section_text),
        })
    return crop_advisory


def identify_pest_name(text):
    t = text.lower()
    pests = [
        ("whitefly", "Whitefly"), ("white fly", "Whitefly"), ("jassid", "Jassid"),
        ("aphid", "Aphid"), ("thrips", "Thrips"), ("mite", "Mite"),
        ("stem borer", "Stem Borer"), ("shoot borer", "Shoot Borer"),
        ("top borer", "Top Borer"), ("pink borer", "Pink Borer"),
        ("fall armyworm", "Fall Armyworm"), ("armyworm", "Armyworm"),
        ("plant hopper", "Plant Hopper"), ("leafhopper", "Leafhopper"),
        ("mealy bug", "Mealy Bug"), ("mealybug", "Mealy Bug"),
        ("bollworm", "Bollworm"), ("leaf curl", "Leaf Curl Virus"),
        ("sheath blight", "Sheath Blight"), ("brown spot", "Brown Spot"),
        ("false smut", "False Smut"), ("bacterial blight", "Bacterial Blight"),
        ("blast", "Blast"), ("blight", "Blight"), ("wilt", "Wilt"),
        ("rot", "Rot"), ("rust", "Rust"), ("smut", "Smut"),
        ("mildew", "Mildew"), ("pyrilla", "Pyrilla"), ("leaf folder", "Leaf Folder"),
        ("parawilt", "Parawilt"),
        ("ਚਿੱਟੀ ਮੱਖੀ", "Whitefly (ਚਿੱਟੀ ਮੱਖੀ)"), ("ਚੇਪਾ", "Aphid (ਚੇਪਾ)"),
        ("ਤੇਲਾ", "Jassid (ਤੇਲਾ)"), ("ਥਰਿੱਪ", "Thrips (ਥਰਿੱਪ)"),
        ("ਗੁਲਾਬੀ ਸੁੰਡੀ", "Pink Bollworm (ਗੁਲਾਬੀ ਸੁੰਡੀ)"),
        ("ਅਮਰੀਕਨ ਸੁੰਡੀ", "American Bollworm (ਅਮਰੀਕਨ ਸੁੰਡੀ)"),
        ("ਗੋਭ ਦੀ ਸੁੰਡੀ", "Stem Borer (ਗੋਭ ਦੀ ਸੁੰਡੀ)"),
        ("ਤਣੇ ਦੀ ਸੁੰਡੀ", "Stem Borer (ਤਣੇ ਦੀ ਸੁੰਡੀ)"),
        ("ਪੱਤਾ ਲਪੇਟ", "Leaf Folder (ਪੱਤਾ ਲਪੇਟ)"),
        ("ਮਿੱਲੀ ਬੱਗ", "Mealy Bug (ਮਿੱਲੀ ਬੱਗ)"),
        ("ਪਾਇਰੀਲਾ", "Pyrilla (ਪਾਇਰੀਲਾ)"),
        ("ਝੁਲਸ", "Blight (ਝੁਲਸ)"), ("ਕੁੰਗੀ", "Rust (ਕੁੰਗੀ)"),
        ("ਕਾਂਗਿਆਰੀ", "Smut (ਕਾਂਗਿਆਰੀ)"), ("ਗੇਰੂਈ", "Rust (ਗੇਰੂਈ)"),
        ("ਜੜ੍ਹ ਗਲ", "Root Rot (ਜੜ੍ਹ ਗਲ)"), ("ਤਣਾ ਗਲ", "Stem Rot (ਤਣਾ ਗਲ)"),
        ("ਉੱਲੀ", "Fungal Disease (ਉੱਲੀ)"), ("ਫ਼ਫ਼ੂੰਦ", "Fungal Disease (ਫ਼ਫ਼ੂੰਦ)"),
    ]
    for kw, name in pests:
        if kw in t: return name
    return "General pest/disease"


def extract_pest_alerts(crop_advisory):
    alerts = []
    for ce in crop_advisory:
        for adv in ce.get("advice", []):
            if adv["category"] == "pest_management":
                severity = "monitoring"
                if any(w in adv["detail"].lower() for w in ["severe", "heavy", "serious", "major", "ਗੰਭੀਰ", "ਭਾਰੀ", "ਵੱਡਾ", "ਤੇਜ਼"]): severity = "high"
                elif any(w in adv["detail"].lower() for w in ["moderate", "regular", "ਦਰਮਿਆਨਾ", "ਲਗਾਤਾਰ"]): severity = "medium"
                alerts.append({"crop": ce["crop"], "pest_name": identify_pest_name(adv["detail"]), "severity": severity, "detail": adv["detail"]})
    return alerts


def extract_seasonal_tips(full_text):
    tips = []
    seen = set()
    patterns = [
        (r'(Keep\s+proper\s+drainage.*?\.)', "Drainage"),
        (r'(Application\s+of\s+chemicals.*?rainfall\s+in\s+the\s+area\.?)', "Chemical Application Timing"),
        (r'(Remove\s+excess\s+rainwater.*?\.)', "Rainwater Management"),
        (r'(ਪਾਣੀ\s+ਦੀ\s+ਨਿਕਾਸੀ.*?।)', "Drainage (ਪਾਣੀ ਦੀ ਨਿਕਾਸੀ)"),
        (r'(ਦਵਾਈਆਂ\s+ਦੀ\s+ਵਰਤੋਂ.*?।)', "Chemical Timing (ਦਵਾਈਆਂ ਦੀ ਵਰਤੋਂ)"),
        (r'(ਬਾਰਿਸ਼\s+ਦਾ\s+ਪਾਣੀ.*?।)', "Rainwater (ਬਾਰਿਸ਼ ਦਾ ਪਾਣੀ)"),
    ]
    for pat, topic in patterns:
        m = re.search(pat, full_text, re.DOTALL | re.IGNORECASE)
        if m:
            d = m.group(1).strip()
            if d not in seen:
                seen.add(d)
                tips.append({"topic": topic, "detail": d})
    return tips


def parse_advisory(full_text, tables):
    crop_adv = parse_crop_sections(full_text)
    return {
        "weather": parse_weather(full_text, tables),
        "crop_advisory": crop_adv,
        "pest_alerts": extract_pest_alerts(crop_adv),
        "seasonal_tips": extract_seasonal_tips(full_text),
    }


# ============================================================
# CONSOLIDATION
# ============================================================

def load_existing():
    if OUT_PATH.exists():
        try: return json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError: pass
    return {"source": "Punjab Agricultural University (PAU), Ludhiana", "website": "https://pau.edu",
            "last_updated": "", "processed_ids": [], "issues": []}


def merge_advisory(existing, new_issue):
    if new_issue["file_id"] in existing.get("processed_ids", []): return False
    existing.setdefault("issues", []).insert(0, new_issue)
    existing.setdefault("processed_ids", []).append(new_issue["file_id"])
    if len(existing["issues"]) > 30:
        removed = existing["issues"][30:]
        existing["issues"] = existing["issues"][:30]
        removed_ids = {r["file_id"] for r in removed}
        existing["processed_ids"] = [pid for pid in existing["processed_ids"] if pid not in removed_ids]
    return True


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60, flush=True)
    print("PAU Advisory Fetcher (Google Drive + English/Punjabi)", flush=True)
    print("=" * 60, flush=True)

    entries = read_links()
    print(f"\nFound {len(entries)} entries in links.txt", flush=True)

    existing = load_existing()
    processed_ids = set(existing.get("processed_ids", []))
    new_count = 0

    for entry in entries:
        fid = entry["file_id"]
        if fid in processed_ids:
            print(f"\n  SKIP (already processed): {fid}", flush=True)
            continue

        print(f"\n  Processing: {fid}", flush=True)
        print(f"    Type: {entry['type']}, Issue: {entry['issue_number']}, Date: {entry['date']}", flush=True)

        pdf_bytes = download_from_drive(entry["drive_file_id"])
        if not pdf_bytes:
            print("    FAILED to download. Skipping.", flush=True)
            continue

        raw_text, tables = extract_text_from_pdf(pdf_bytes)
        if not raw_text.strip():
            print("    WARNING: No text extracted from PDF. Skipping.", flush=True)
            continue
        print(f"    Extracted: {len(raw_text):,} chars, {len(tables)} tables", flush=True)

        parsed = parse_advisory(raw_text, tables)
        cc = len(parsed.get("crop_advisory", []))
        pc = len(parsed.get("pest_alerts", []))
        tc = len(parsed.get("seasonal_tips", []))
        print(f"    Parsed: {cc} crops, {pc} pest alerts, {tc} tips", flush=True)

        issue = {
            "file_id": fid,
            "type": entry["type"],
            "issue_number": entry["issue_number"],
            "date": entry["date"],
            "drive_url": entry["drive_url"],
            "fetched_at": datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M IST"),
            "weather": parsed["weather"],
            "crop_advisory": [{"crop": c["crop"], "advice": c["advice"]} for c in parsed["crop_advisory"]],
            "pest_alerts": parsed["pest_alerts"],
            "seasonal_tips": parsed["seasonal_tips"],
        }

        if merge_advisory(existing, issue):
            new_count += 1
            print("    Added to consolidated file.", flush=True)

        time.sleep(2)

    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    existing["last_updated"] = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
    existing["source"] = "Punjab Agricultural University (PAU), Ludhiana"
    existing["website"] = "https://pau.edu"
    existing["total_issues"] = len(existing.get("issues", []))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}", flush=True)
    print(f"Done. New issues processed: {new_count}", flush=True)
    print(f"Total issues in file: {existing['total_issues']}", flush=True)
    print(f"Wrote: {OUT_PATH}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL ERROR: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
