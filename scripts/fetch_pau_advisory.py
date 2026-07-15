"""
Fetch PAU advisories, extract text from PDFs using pdfplumber,
categorize by topic using rule-based parsing (English + Punjabi keywords),
consolidate into one JSON file. Zero AI dependencies.
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

# --- Install pdfplumber if missing ---
try:
    import pdfplumber
except ImportError:
    os.system("pip install pdfplumber --break-system-packages -q")
    import pdfplumber

# --- Config ---
OUT_PATH = Path("data/advisory/pau_advisory.json")
MAX_ISSUES = 4

PAU_PAGES = [
    {
        "name": "Agro Advisory (Weekly)",
        "url": "https://pau.edu/index.php?_act=manageSandesh&DO=viewAdvisory",
        "type": "agro_advisory",
    },
    {
        "name": "Kheti Sandesh",
        "url": "https://pau.edu/index.php?_act=manageSandesh&DO=viewSandesh",
        "type": "kheti_sandesh",
    },
]

HEADERS = {"User-Agent": "ArcusPolicyResearch/1.0"}

# Crop names: English + Punjabi
CROP_KEYWORDS = [
    # English
    "rice", "paddy", "basmati",
    "cotton", "narma",
    "sugarcane",
    "maize", "corn",
    "moong", "mungbean", "mung",
    "mash", "urad", "urdbean",
    "groundnut", "peanut",
    "soybean", "soyabean",
    "bajra", "pearl millet",
    "vegetables", "vegetable crops",
    "fruit", "fruits", "orchard", "orchards",
    "fodder",
    "pulses",
    "oilseeds",
    "potato",
    "onion",
    "tomato",
    "wheat",
    "mustard", "rapeseed",
    "sunflower",
    "guava",
    "kinnow", "citrus",
    # Punjabi (Gurmukhi)
    "ਝੋਨਾ", "ਧਾਨ",          # rice / paddy
    "ਬਾਸਮਤੀ",               # basmati
    "ਕਣਕ",                  # wheat
    "ਨਰਮਾ", "ਕਪਾਹ",         # cotton
    "ਗੰਨਾ",                 # sugarcane
    "ਮੱਕੀ",                 # maize
    "ਮੂੰਗੀ",                # moong
    "ਮਾਂਹ",                 # mash/urad
    "ਮੂੰਗਫਲੀ",              # groundnut
    "ਸੋਇਆਬੀਨ",              # soybean
    "ਬਾਜਰਾ",                # bajra
    "ਸਬਜ਼ੀਆਂ", "ਸਬਜ਼ੀ",      # vegetables
    "ਫਲ",                   # fruit
    "ਚਾਰਾ",                 # fodder
    "ਦਾਲਾਂ",                # pulses
    "ਤੇਲ ਬੀਜ",              # oilseeds
    "ਆਲੂ",                  # potato
    "ਪਿਆਜ਼",                # onion
    "ਟਮਾਟਰ",                # tomato
    "ਸਰ੍ਹੋਂ", "ਰਾਇਆ",       # mustard
    "ਸੂਰਜਮੁਖੀ",             # sunflower
    "ਅਮਰੂਦ",                # guava
    "ਕਿੰਨੂ",                # kinnow
]

# Punjabi to English crop name mapping for display
CROP_NAME_MAP = {
    "ਝੋਨਾ": "Rice (ਝੋਨਾ)", "ਧਾਨ": "Rice (ਧਾਨ)",
    "ਬਾਸਮਤੀ": "Basmati (ਬਾਸਮਤੀ)",
    "ਕਣਕ": "Wheat (ਕਣਕ)",
    "ਨਰਮਾ": "Cotton (ਨਰਮਾ)", "ਕਪਾਹ": "Cotton (ਕਪਾਹ)",
    "ਗੰਨਾ": "Sugarcane (ਗੰਨਾ)",
    "ਮੱਕੀ": "Maize (ਮੱਕੀ)",
    "ਮੂੰਗੀ": "Moong (ਮੂੰਗੀ)",
    "ਮਾਂਹ": "Urad (ਮਾਂਹ)",
    "ਮੂੰਗਫਲੀ": "Groundnut (ਮੂੰਗਫਲੀ)",
    "ਸੋਇਆਬੀਨ": "Soybean (ਸੋਇਆਬੀਨ)",
    "ਬਾਜਰਾ": "Bajra (ਬਾਜਰਾ)",
    "ਸਬਜ਼ੀਆਂ": "Vegetables (ਸਬਜ਼ੀਆਂ)", "ਸਬਜ਼ੀ": "Vegetables (ਸਬਜ਼ੀ)",
    "ਫਲ": "Fruits (ਫਲ)",
    "ਚਾਰਾ": "Fodder (ਚਾਰਾ)",
    "ਦਾਲਾਂ": "Pulses (ਦਾਲਾਂ)",
    "ਤੇਲ ਬੀਜ": "Oilseeds (ਤੇਲ ਬੀਜ)",
    "ਆਲੂ": "Potato (ਆਲੂ)",
    "ਪਿਆਜ਼": "Onion (ਪਿਆਜ਼)",
    "ਟਮਾਟਰ": "Tomato (ਟਮਾਟਰ)",
    "ਸਰ੍ਹੋਂ": "Mustard (ਸਰ੍ਹੋਂ)", "ਰਾਇਆ": "Mustard (ਰਾਇਆ)",
    "ਸੂਰਜਮੁਖੀ": "Sunflower (ਸੂਰਜਮੁਖੀ)",
    "ਅਮਰੂਦ": "Guava (ਅਮਰੂਦ)",
    "ਕਿੰਨੂ": "Kinnow (ਕਿੰਨੂ)",
}


def fetch_page(url):
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  page fetch attempt {attempt} failed: {e}", flush=True)
            time.sleep(5 * attempt)
    return None


def extract_pdf_links(html, page_type):
    links = []
    pdf_pattern = re.compile(r'href=["\']([^"\']*?\.pdf)["\']', re.IGNORECASE)
    rows = re.split(r'<tr|<div', html)

    for row in rows:
        pdf_match = pdf_pattern.search(row)
        if not pdf_match:
            continue

        pdf_path = pdf_match.group(1)
        if not pdf_path.startswith("http"):
            if pdf_path.startswith("/"):
                pdf_url = "https://pau.edu" + pdf_path
            else:
                pdf_url = "https://pau.edu/" + pdf_path
        else:
            pdf_url = pdf_path

        date_match = re.search(r'(\d{2}-\d{2}-\d{4})', row)
        date_str = date_match.group(1) if date_match else ""

        issue_match = re.search(r'(?:Vol|ਅੰਕ)\s*(\d+)', row)
        issue_num = issue_match.group(1) if issue_match else ""

        file_id = f"{page_type}_{issue_num}_{date_str}" if (issue_num or date_str) else pdf_url

        links.append({
            "url": pdf_url,
            "date": date_str,
            "issue_number": issue_num,
            "type": page_type,
            "file_id": file_id,
        })
    return links


def download_pdf(url):
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception as e:
            print(f"    download attempt {attempt} failed: {e}", flush=True)
            time.sleep(5 * attempt)
    return None


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


def parse_weather(full_text, tables):
    weather = {
        "outlook": "",
        "zone_data": [],
        "general_advice": "",
    }

    # English weather outlook
    outlook_patterns = [
        r'(?:WEATHER\s*(?:CROP\s*)?OUTLOOK[:\s]*)(.*?)(?=\n\s*CROPS?[:\s]|\n\s*[A-Z][a-z]+\s*:)',
        r'(?:Weather\s*(?:Crop\s*)?Outlook[:\s]*)(.*?)(?=\n\s*Crops?[:\s]|\n\s*[A-Z][a-z]+\s*:)',
    ]
    # Punjabi weather outlook
    outlook_patterns += [
        r'(?:ਮੌਸਮ\s*(?:ਫ਼ਸਲ\s*)?ਸੰਭਾਵਨਾ[:\s]*)(.*?)(?=\n\s*ਫ਼ਸਲਾਂ[:\s])',
        r'(?:ਮੌਸਮ[:\s]*)(.*?)(?=\n\s*ਫ਼ਸਲ)',
    ]
    for pat in outlook_patterns:
        m = re.search(pat, full_text, re.DOTALL | re.IGNORECASE)
        if m:
            weather["outlook"] = m.group(1).strip()
            break

    # Zone data from tables
    for table in tables:
        header = [str(c).lower() for c in table[0]] if table else []
        if any(w in " ".join(header) for w in ["zone", "weather", "temperature", "ਤਾਪਮਾਨ", "ਖੇਤਰ"]):
            for row in table[1:]:
                if len(row) >= 2:
                    param = row[0].strip() if row[0] else ""
                    for i, zone_name in enumerate(header[1:], 1):
                        if i < len(row) and row[i]:
                            zone_entry = None
                            for z in weather["zone_data"]:
                                if z["zone"].lower() == zone_name.lower():
                                    zone_entry = z
                                    break
                            if not zone_entry:
                                zone_entry = {"zone": zone_name.strip(), "max_temp": "", "min_temp": "", "morning_humidity": "", "evening_humidity": ""}
                                weather["zone_data"].append(zone_entry)

                            val = str(row[i]).strip()
                            param_l = param.lower()
                            if ("max" in param_l or "ਵੱਧ" in param_l) and ("temp" in param_l or "ਤਾਪਮਾਨ" in param_l):
                                zone_entry["max_temp"] = val
                            elif ("min" in param_l or "ਘੱਟ" in param_l) and ("temp" in param_l or "ਤਾਪਮਾਨ" in param_l):
                                zone_entry["min_temp"] = val
                            elif ("morning" in param_l or "ਸਵੇਰ" in param_l) and ("humid" in param_l or "ਨਮੀ" in param_l):
                                zone_entry["morning_humidity"] = val
                            elif ("evening" in param_l or "ਸ਼ਾਮ" in param_l) and ("humid" in param_l or "ਨਮੀ" in param_l):
                                zone_entry["evening_humidity"] = val

    # General weather advice (English + Punjabi)
    advice_patterns = [
        r'((?:Farmers?\s+(?:are\s+)?advised?|Keep\s+proper\s+drainage|Remove\s+excess\s+rainwater).*?\.)',
        r'((?:ਕਿਸਾਨਾਂ\s+ਨੂੰ\s+ਸਲਾਹ|ਪਾਣੀ\s+ਦੀ\s+ਨਿਕਾਸੀ|ਬਾਰਿਸ਼\s+ਦਾ\s+ਪਾਣੀ).*?।)',
    ]
    for pat in advice_patterns:
        m = re.search(pat, full_text, re.DOTALL | re.IGNORECASE)
        if m:
            weather["general_advice"] = m.group(1).strip()
            break

    return weather


def parse_crop_sections(full_text):
    crop_advisory = []

    crop_names_in_text = []
    for keyword in CROP_KEYWORDS:
        pattern = re.compile(
            r'(?:^|\n)\s*(' + re.escape(keyword) + r')\s*[:\-।]',
            re.IGNORECASE | re.MULTILINE
        )
        for m in pattern.finditer(full_text):
            crop_names_in_text.append((m.start(), m.group(1).strip()))

    crop_names_in_text.sort(key=lambda x: x[0])

    seen = set()
    unique_crops = []
    for pos, name in crop_names_in_text:
        name_lower = name.lower()
        if name_lower not in seen:
            seen.add(name_lower)
            unique_crops.append((pos, name))

    for i, (pos, crop_name) in enumerate(unique_crops):
        start = pos
        end = unique_crops[i + 1][0] if i + 1 < len(unique_crops) else len(full_text)
        section_text = full_text[start:end].strip()

        section_text = re.sub(
            r'^' + re.escape(crop_name) + r'\s*[:\-।]\s*',
            '', section_text, flags=re.IGNORECASE
        ).strip()

        if not section_text or len(section_text) < 20:
            continue

        advice_list = categorize_advice(section_text)

        # Use English + Punjabi display name
        display_name = CROP_NAME_MAP.get(crop_name, crop_name.strip().title())

        crop_advisory.append({
            "crop": display_name,
            "full_text": section_text,
            "advice": advice_list,
        })

    return crop_advisory


def categorize_advice(text):
    advice = []
    # Split on ". " or "। " (Punjabi sentence ender)
    sentences = re.split(r'(?<=[.।!])\s+', text)

    current_category = "general"
    current_detail = []

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue

        cat = detect_category(sent)
        if cat != current_category and current_detail:
            advice.append({
                "category": current_category,
                "detail": " ".join(current_detail),
            })
            current_detail = []
        current_category = cat
        current_detail.append(sent)

    if current_detail:
        advice.append({
            "category": current_category,
            "detail": " ".join(current_detail),
        })

    return advice


def detect_category(sentence):
    s = sentence.lower()

    # --- Irrigation (English + Punjabi) ---
    irrigation_en = ["irrigation", "irrigat", "water standing", "ponded water",
                     "drain", "waterlogg", "field capacity", "apply water"]
    irrigation_pb = ["ਸਿੰਚਾਈ", "ਪਾਣੀ ਲਗਾ", "ਪਾਣੀ ਦਿਓ", "ਪਾਣੀ ਖੜ੍ਹਾ",
                     "ਨਿਕਾਸੀ", "ਪਾਣੀ ਕੱਢ", "ਪਾਣੀ ਦੇ", "ਪਾਣੀ ਨਾ ਖੜ੍ਹ"]
    if any(w in s for w in irrigation_en + irrigation_pb):
        return "irrigation"

    # --- Pest/disease management (English + Punjabi) ---
    pest_en = ["spray", "insecticide", "pesticide", "fungicide",
               "whitefly", "borer", "hopper", "armyworm", "thrips",
               "aphid", "jassid", "mite", "mealy", "bollworm",
               "blight", "blast", "wilt", "rot", "rust", "smut",
               "mildew", "virus", "disease", "infected", "infestation",
               "flonicamid", "dinotefuran", "imidacloprid", "carbofuran",
               "fipronil", "chlorpyriphos", "trichoderma",
               "trap", "pheromone", "monitor"]
    pest_pb = ["ਛਿੜਕਾਅ", "ਕੀਟ", "ਕੀੜਾ", "ਕੀੜੇ", "ਕੀੜਿਆਂ",
               "ਬੀਮਾਰੀ", "ਰੋਗ", "ਬਿਮਾਰੀ",
               "ਚਿੱਟੀ ਮੱਖੀ", "ਚੇਪਾ", "ਤੇਲਾ",
               "ਸੁੰਡੀ", "ਗੁਲਾਬੀ ਸੁੰਡੀ", "ਅਮਰੀਕਨ ਸੁੰਡੀ",
               "ਗੋਭ ਦੀ ਸੁੰਡੀ", "ਤਣੇ ਦੀ ਸੁੰਡੀ",
               "ਪੱਤਾ ਲਪੇਟ", "ਫੁੱਲ ਕੀੜਾ",
               "ਫ਼ਫ਼ੂੰਦ", "ਉੱਲੀ", "ਝੁਲਸ", "ਕੁੰਗੀ",
               "ਕਾਂਗਿਆਰੀ", "ਗੇਰੂਈ",
               "ਦਵਾਈ", "ਸਪਰੇਅ", "ਜ਼ਹਿਰ",
               "ਪਾਇਰੀਲਾ", "ਮਿੱਲੀ ਬੱਗ",
               "ਜੜ੍ਹ ਗਲ", "ਤਣਾ ਗਲ",
               "ਅਗੇਤਾ ਝੁਲਸ", "ਪਿਛੇਤਾ ਝੁਲਸ",
               "ਕਾਲੀ ਕੁੰਗੀ", "ਭੂਰੀ ਕੁੰਗੀ", "ਪੀਲੀ ਕੁੰਗੀ"]
    if any(w in s for w in pest_en + pest_pb):
        return "pest_management"

    # --- Weed management (English + Punjabi) ---
    weed_en = ["weed", "herbicide", "atrazine", "butachlor",
               "pendimethalin", "pyrazosulfuron", "bispyribac",
               "pre-emergence", "post-emergence"]
    weed_pb = ["ਨਦੀਨ", "ਨਦੀਨਾਂ", "ਨਦੀਨ ਨਾਸ਼ਕ",
               "ਬੂਟੀ", "ਬੂਟੀਆਂ", "ਬੂਟੀ ਨਾਸ਼ਕ",
               "ਘਾਹ", "ਗੁੱਲੀ ਡੰਡਾ", "ਮੰਡੂਸੀ",
               "ਪਹਿਲਾਂ ਉੱਗਣ ਤੋਂ", "ਬਾਅਦ ਉੱਗਣ ਤੋਂ"]
    if any(w in s for w in weed_en + weed_pb):
        return "weed_management"

    # --- Fertilizer/nutrition (English + Punjabi) ---
    fert_en = ["fertiliz", "urea", "dap", "nitrogen", "phospho",
               "potash", "zinc", "sulphate", "micronutrient",
               "nutrient", "deficiency", "basal dose", "top dress"]
    fert_pb = ["ਖਾਦ", "ਯੂਰੀਆ", "ਡੀ.ਏ.ਪੀ", "ਨਾਈਟ੍ਰੋਜਨ",
               "ਫ਼ਾਸਫ਼ੋਰਸ", "ਪੋਟਾਸ਼", "ਜ਼ਿੰਕ", "ਜ਼ਿੰਕ ਸਲਫ਼ੇਟ",
               "ਸੂਖ਼ਮ ਤੱਤ", "ਤੱਤ ਦੀ ਘਾਟ", "ਕਮੀ"]
    if any(w in s for w in fert_en + fert_pb):
        return "fertilizer"

    # --- Variety/sowing (English + Punjabi) ---
    var_en = ["variety", "varieties", "sowing", "transplant",
              "nursery", "seed rate", "seed treatment",
              "pr-126", "pusa basmati", "pbw", "pb "]
    var_pb = ["ਕਿਸਮ", "ਕਿਸਮਾਂ", "ਬਿਜਾਈ", "ਲੁਆਈ",
              "ਪਨੀਰੀ", "ਬੀਜ", "ਬੀਜ ਦੀ ਮਾਤਰਾ",
              "ਬੀਜ ਸੋਧ", "ਰੋਪਾਈ"]
    if any(w in s for w in var_en + var_pb):
        return "variety_sowing"

    # --- Harvesting (English + Punjabi) ---
    harv_en = ["harvest", "picking", "maturity", "ripe"]
    harv_pb = ["ਕਟਾਈ", "ਵਾਢੀ", "ਤੁੜਾਈ", "ਪੱਕ"]
    if any(w in s for w in harv_en + harv_pb):
        return "harvesting"

    return "general"


def extract_pest_alerts(crop_advisory):
    alerts = []
    for crop_entry in crop_advisory:
        crop_name = crop_entry["crop"]
        for adv in crop_entry.get("advice", []):
            if adv["category"] == "pest_management":
                text = adv["detail"]
                pest_name = identify_pest_name(text)
                severity = "monitoring"
                if any(w in text.lower() for w in ["severe", "heavy", "serious", "major",
                                                    "ਗੰਭੀਰ", "ਭਾਰੀ", "ਵੱਡਾ", "ਤੇਜ਼"]):
                    severity = "high"
                elif any(w in text.lower() for w in ["moderate", "regular",
                                                      "ਦਰਮਿਆਨਾ", "ਲਗਾਤਾਰ"]):
                    severity = "medium"
                alerts.append({
                    "crop": crop_name,
                    "pest_name": pest_name,
                    "severity": severity,
                    "detail": text,
                })
    return alerts


def identify_pest_name(text):
    t = text.lower()
    pest_names = [
        # English
        ("whitefly", "Whitefly"), ("white fly", "Whitefly"),
        ("jassid", "Jassid"), ("aphid", "Aphid"),
        ("thrips", "Thrips"), ("mite", "Mite"),
        ("stem borer", "Stem Borer"), ("shoot borer", "Shoot Borer"),
        ("top borer", "Top Borer"), ("pink borer", "Pink Borer"),
        ("fall armyworm", "Fall Armyworm"), ("armyworm", "Armyworm"),
        ("plant hopper", "Plant Hopper"), ("leafhopper", "Leafhopper"),
        ("mealy bug", "Mealy Bug"), ("mealybug", "Mealy Bug"),
        ("bollworm", "Bollworm"), ("boll worm", "Bollworm"),
        ("leaf curl", "Leaf Curl Virus"), ("curl virus", "Leaf Curl Virus"),
        ("sheath blight", "Sheath Blight"), ("brown spot", "Brown Spot"),
        ("false smut", "False Smut"), ("bacterial blight", "Bacterial Blight"),
        ("blast", "Blast"), ("blight", "Blight"),
        ("wilt", "Wilt"), ("rot", "Rot"),
        ("rust", "Rust"), ("smut", "Smut"),
        ("mildew", "Mildew"), ("pyrilla", "Pyrilla"),
        ("leaf folder", "Leaf Folder"),
        ("parawilt", "Parawilt"),
        # Punjabi
        ("ਚਿੱਟੀ ਮੱਖੀ", "Whitefly (ਚਿੱਟੀ ਮੱਖੀ)"),
        ("ਚੇਪਾ", "Aphid (ਚੇਪਾ)"),
        ("ਤੇਲਾ", "Jassid (ਤੇਲਾ)"),
        ("ਥਰਿੱਪ", "Thrips (ਥਰਿੱਪ)"),
        ("ਗੁਲਾਬੀ ਸੁੰਡੀ", "Pink Bollworm (ਗੁਲਾਬੀ ਸੁੰਡੀ)"),
        ("ਅਮਰੀਕਨ ਸੁੰਡੀ", "American Bollworm (ਅਮਰੀਕਨ ਸੁੰਡੀ)"),
        ("ਤੇਲੇ ਦਾ ਸੁੰਡੀ", "Spotted Bollworm"),
        ("ਗੋਭ ਦੀ ਸੁੰਡੀ", "Stem Borer (ਗੋਭ ਦੀ ਸੁੰਡੀ)"),
        ("ਤਣੇ ਦੀ ਸੁੰਡੀ", "Stem Borer (ਤਣੇ ਦੀ ਸੁੰਡੀ)"),
        ("ਪੱਤਾ ਲਪੇਟ", "Leaf Folder (ਪੱਤਾ ਲਪੇਟ)"),
        ("ਮਿੱਲੀ ਬੱਗ", "Mealy Bug (ਮਿੱਲੀ ਬੱਗ)"),
        ("ਪਾਇਰੀਲਾ", "Pyrilla (ਪਾਇਰੀਲਾ)"),
        ("ਝੁਲਸ", "Blight (ਝੁਲਸ)"),
        ("ਕੁੰਗੀ", "Rust (ਕੁੰਗੀ)"),
        ("ਕਾਂਗਿਆਰੀ", "Smut (ਕਾਂਗਿਆਰੀ)"),
        ("ਗੇਰੂਈ", "Rust (ਗੇਰੂਈ)"),
        ("ਜੜ੍ਹ ਗਲ", "Root Rot (ਜੜ੍ਹ ਗਲ)"),
        ("ਤਣਾ ਗਲ", "Stem Rot (ਤਣਾ ਗਲ)"),
        ("ਉੱਲੀ", "Fungal Disease (ਉੱਲੀ)"),
        ("ਫ਼ਫ਼ੂੰਦ", "Fungal Disease (ਫ਼ਫ਼ੂੰਦ)"),
    ]
    for keyword, name in pest_names:
        if keyword in t:
            return name
    return "General pest/disease"


def extract_seasonal_tips(full_text):
    tips = []

    patterns = [
        # English
        (r'(Keep\s+proper\s+drainage.*?\.)', "Drainage"),
        (r'(Application\s+of\s+chemicals.*?rainfall\s+in\s+the\s+area\.?)', "Chemical Application Timing"),
        (r'(Remove\s+excess\s+rainwater.*?\.)', "Rainwater Management"),
        # Punjabi
        (r'(ਪਾਣੀ\s+ਦੀ\s+ਨਿਕਾਸੀ.*?।)', "Drainage (ਪਾਣੀ ਦੀ ਨਿਕਾਸੀ)"),
        (r'(ਦਵਾਈਆਂ\s+ਦੀ\s+ਵਰਤੋਂ.*?।)', "Chemical Application Timing (ਦਵਾਈਆਂ ਦੀ ਵਰਤੋਂ)"),
        (r'(ਬਾਰਿਸ਼\s+ਦਾ\s+ਪਾਣੀ.*?।)', "Rainwater Management (ਬਾਰਿਸ਼ ਦਾ ਪਾਣੀ)"),
    ]

    seen = set()
    for pat, topic in patterns:
        m = re.search(pat, full_text, re.DOTALL | re.IGNORECASE)
        if m:
            detail = m.group(1).strip()
            if detail not in seen:
                seen.add(detail)
                tips.append({"topic": topic, "detail": detail})
    return tips


def parse_advisory(full_text, tables):
    weather = parse_weather(full_text, tables)
    crop_advisory = parse_crop_sections(full_text)
    pest_alerts = extract_pest_alerts(crop_advisory)
    seasonal_tips = extract_seasonal_tips(full_text)

    return {
        "weather": weather,
        "crop_advisory": crop_advisory,
        "pest_alerts": pest_alerts,
        "seasonal_tips": seasonal_tips,
    }


def load_existing():
    if OUT_PATH.exists():
        try:
            return json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "source": "Punjab Agricultural University (PAU), Ludhiana",
        "website": "https://pau.edu",
        "last_updated": "",
        "processed_ids": [],
        "issues": [],
    }


def merge_advisory(existing, new_issue):
    if new_issue["file_id"] in existing.get("processed_ids", []):
        return False

    existing.setdefault("issues", []).insert(0, new_issue)
    existing.setdefault("processed_ids", []).append(new_issue["file_id"])

    if len(existing["issues"]) > 30:
        removed = existing["issues"][30:]
        existing["issues"] = existing["issues"][:30]
        removed_ids = {r["file_id"] for r in removed}
        existing["processed_ids"] = [
            pid for pid in existing["processed_ids"] if pid not in removed_ids
        ]
    return True


def main():
    print("=" * 60, flush=True)
    print("PAU Advisory Fetcher (English + Punjabi keywords)", flush=True)
    print("=" * 60, flush=True)

    existing = load_existing()
    processed_ids = set(existing.get("processed_ids", []))
    new_count = 0

    for page in PAU_PAGES:
        print(f"\n--- {page['name']} ---", flush=True)
        print(f"  Fetching: {page['url']}", flush=True)

        html = fetch_page(page["url"])
        if not html:
            print("  FAILED to fetch page. Skipping.", flush=True)
            continue

        links = extract_pdf_links(html, page["type"])
        print(f"  Found {len(links)} PDF links", flush=True)

        new_links = [l for l in links if l["file_id"] not in processed_ids]
        print(f"  New (unprocessed): {len(new_links)}", flush=True)

        for link in new_links[:MAX_ISSUES]:
            print(f"\n  Processing: {link['url']}", flush=True)
            print(f"    Issue: {link['issue_number']}, Date: {link['date']}", flush=True)

            pdf_bytes = download_pdf(link["url"])
            if not pdf_bytes:
                print("    FAILED to download. Skipping.", flush=True)
                continue
            print(f"    Downloaded: {len(pdf_bytes):,} bytes", flush=True)

            raw_text, tables = extract_text_from_pdf(pdf_bytes)
            if not raw_text.strip():
                print("    WARNING: No text extracted (may be image-based). Skipping.", flush=True)
                continue
            print(f"    Extracted: {len(raw_text):,} chars, {len(tables)} tables", flush=True)

            parsed = parse_advisory(raw_text, tables)
            crop_count = len(parsed.get("crop_advisory", []))
            pest_count = len(parsed.get("pest_alerts", []))
            tip_count = len(parsed.get("seasonal_tips", []))
            print(f"    Parsed: {crop_count} crops, {pest_count} pest alerts, {tip_count} tips", flush=True)

            issue = {
                "file_id": link["file_id"],
                "type": link["type"],
                "issue_number": link["issue_number"],
                "date": link["date"],
                "pdf_url": link["url"],
                "fetched_at": datetime.now(
                    timezone(timedelta(hours=5, minutes=30))
                ).strftime("%Y-%m-%d %H:%M IST"),
                "weather": parsed["weather"],
                "crop_advisory": [
                    {"crop": c["crop"], "advice": c["advice"]}
                    for c in parsed["crop_advisory"]
                ],
                "pest_alerts": parsed["pest_alerts"],
                "seasonal_tips": parsed["seasonal_tips"],
            }

            if merge_advisory(existing, issue):
                new_count += 1
                print(f"    Added to consolidated file.", flush=True)

            time.sleep(3)

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
