import os
import re
import sys
import html
import json
import time
import random
import requests

# Credenciales desde GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

SEEN_FILE = "seen_jobs.json"
CONFIG_FILE = "config.json"

# Límites conservadores para acecho continuo cada 30 minutos sin bloqueos de IP
MAX_JOBS_PER_RUN = 12
QUERIES_PER_RUN = 3

# 1. ROTACIÓN DE NAVEGADORES REALES (Evita huella digital de bot)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"
]

# 2. PALABRAS CLAVE PARA RECIÉN LLEGADOS (Se consultan en turnos rotativos continuos)
JOB_KEYWORDS = [
    "General Labourer White Card",
    "Trade Assistant",
    "FIFO Utility",
    "Solar Farm Labourer",
    "Warehouse Pick Packer",
    "Container Unloader General Hand",
    "Kitchen Hand Housekeeping",
    "Civil Construction Labourer",
    "Farm Hand",
    "Factory Hand Process Worker"
]

# 3. DICCIONARIO DE CIUDADES AUSTRALIANAS
AUSTRALIAN_CITIES = {
    "perth": "Perth WA", "fremantle": "Fremantle WA", "mandurah": "Mandurah WA",
    "bunbury": "Bunbury WA", "busselton": "Busselton WA", "margaret river": "Margaret River WA",
    "albany": "Albany WA", "esperance": "Esperance WA", "kalgoorlie": "Kalgoorlie WA",
    "geraldton": "Geraldton WA", "exmouth": "Exmouth WA", "carnarvon": "Carnarvon WA",
    "karratha": "Karratha WA", "port hedland": "Port Hedland WA", "newman": "Newman WA",
    "tom price": "Tom Price WA", "broome": "Broome WA", "kununurra": "Kununurra WA",
    "sydney": "Sydney NSW", "newcastle": "Newcastle NSW", "wollongong": "Wollongong NSW",
    "byron bay": "Byron Bay NSW", "melbourne": "Melbourne VIC", "geelong": "Geelong VIC",
    "brisbane": "Brisbane QLD", "gold coast": "Gold Coast QLD", "sunshine coast": "Sunshine Coast QLD",
    "cairns": "Cairns QLD", "townsville": "Townsville QLD", "mackay": "Mackay QLD",
    "rockhampton": "Rockhampton QLD", "gladstone": "Gladstone QLD", "toowoomba": "Toowoomba QLD",
    "darwin": "Darwin NT", "alice springs": "Alice Springs NT", "adelaide": "Adelaide SA",
    "hobart": "Hobart TAS", "canberra": "Canberra ACT"
}

# 4. AGENCIAS Y EMPRESAS TIER 1
SERIOUS_ORGS = [
    "programmed", "workpac", "hays", "chandler macleod", "adecco", "randstad",
    "monadelphous", "ventia", "downer", "bhp", "rio tinto", "fortescue", "fmg",
    "mineral resources", "minres", "macmahon", "perenti", "sodexo", "compass group",
    "iss facility", "civeo", "acciona", "lendlease", "cpb contractors", "bmd",
    "corestaff", "techforce", "linkforce", "agrifood", "costa group", "action workforce",
    "hoban", "persolkelly", "labourpower", "skout", "awx", "recruitwest"
]

# 5. FILTRO ESTRICTO: Excluye puestos con título universitario, cargos ejecutivos y requisitos de ciudadanía
BLACKLIST_WORDS = [
    "engineer", "engineering", "doctor", "medical", "physician", "surgeon",
    "registered nurse", "nursing", "clinical", "pharmacist", "dentist", "psychologist",
    "physiotherapist", "occupational therapist", "veterinarian", "vet ", "radiographer",
    "architect", "architecture", "draftsperson", "lawyer", "solicitor", "legal counsel",
    "accountant", "accounting", "auditor", "actuary", "geologist", "geophysicist",
    "metallurgist", "surveyor", "quantity surveyor", "agronomist", "teacher", "lecturer",
    "bachelor", "master's", "phd", "tertiary qualification", "university degree",
    "senior manager", "general manager", "director", "principal", "head of",
    "lead ", "superintendent", "project manager", "supervisor", "coordinator",
    "australian citizen", "citizens only", "pr only", "permanent resident only",
    "nv1", "nv2", "baseline clearance", "unpaid", "commission only", "survey",
    "au pair", "mystery shopper", "mlm", "crypto", "volunteer"
]

# 6. MAPA DE CÓDIGOS POSTALES DE REFERENCIA
POSTCODE_MAP = {
    "perth": "6000 (WA)", "fremantle": "6160 (WA)", "rockingham": "6168 (WA)",
    "mandurah": "6210 (WA)", "bunbury": "6230 (WA)", "busselton": "6280 (WA)",
    "margaret river": "6285 (WA)", "albany": "6330 (WA)", "esperance": "6450 (WA)",
    "kalgoorlie": "6430 (WA)", "geraldton": "6530 (WA)", "carnarvon": "6701 (WA)",
    "exmouth": "6707 (WA)", "karratha": "6714 (WA)", "port hedland": "6721 (WA)",
    "newman": "6753 (WA)", "tom price": "6751 (WA)", "broome": "6725 (WA)",
    "kununurra": "6743 (WA)", "darwin": "0800 (NT)", "alice springs": "0870 (NT)",
    "cairns": "4870 (QLD)", "townsville": "4810 (QLD)", "mackay": "4740 (QLD)",
    "rockhampton": "4700 (QLD)", "gladstone": "4680 (QLD)", "toowoomba": "4350 (QLD)",
    "brisbane": "4000 (QLD)", "gold coast": "4217 (QLD)", "sunshine coast": "4558 (QLD)",
    "sydney": "2000 (NSW)", "newcastle": "2300 (NSW)", "wollongong": "2500 (NSW)",
    "melbourne": "3000 (VIC)", "geelong": "3220 (VIC)", "adelaide": "5000 (SA)",
    "hobart": "7000 (TAS)", "canberra": "2600 (ACT)"
}

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return list(dict.fromkeys(data))
        except Exception:
            return []
    return []

def save_seen(seen_list):
    trimmed = list(dict.fromkeys(seen_list))[-4000:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f)

def load_config():
    default_cfg = {
        "active_city": None,
        "last_update_id": 0,
        "asked_for_city": False,
        "query_index": 0
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                default_cfg.update(loaded)
        except Exception:
            pass
    return default_cfg

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

def send_telegram_request(payload):
    """Envía mensajes a Telegram con gestión de rate limits (Error 429)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for attempt in range(2):
        try:
            r = requests.post(api_url, json=payload, timeout=12)
            if r.status_code == 200:
                return True
            if r.status_code == 429:
                retry_after = r.json().get("parameters", {}).get("retry_after", 10)
                print(f"[Telegram Rate Limit] Esperando {retry_after}s...")
                time.sleep(min(int(retry_after) + 1, 30))
            else:
                return False
        except Exception as e:
            print(f"[Aviso Telegram]: {e}")
            time.sleep(2)
    return False

def send_simple_message(text_html):
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    send_telegram_request(payload)

def normalize_city(user_text):
    clean = user_text.strip().lower()
    if clean in AUSTRALIAN_CITIES:
        return AUSTRALIAN_CITIES[clean]
    for key, val in AUSTRALIAN_CITIES.items():
        if key in clean:
            return val
    return user_text.strip().title()

def check_telegram_city_selection(cfg):
    """Detecta si el usuario respondió en Telegram para cambiar la ciudad."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return cfg

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"offset": cfg.get("last_update_id", 0) + 1, "timeout": 5}
    try:
        r = requests.get(api_url, params=params, timeout=10)
        if r.status_code == 200:
            updates = r.json().get("result", [])
            for u in updates:
                update_id = u.get("update_id", 0)
                if update_id > cfg.get("last_update_id", 0):
                    cfg["last_update_id"] = update_id

                msg = u.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip()

                if chat_id == str(TELEGRAM_CHAT_ID) and text:
                    lower_t = text.lower()
                    if lower_t in ["/start", "/ciudad", "/zona", "cambiar", "ciudad", "hola"]:
                        cfg["active_city"] = None
                        cfg["asked_for_city"] = True
                        send_simple_message(
                            "📍 <b>¿Dónde estás buscando trabajo?</b>\n\n"
                            "Respóndeme con el nombre de la ciudad de Australia "
                            "(ej: <b>Perth</b>, <b>Sydney</b>, <b>Brisbane</b>, <b>Melbourne</b>, "
                            "<b>Darwin</b>, <b>Cairns</b>, <b>Karratha</b>, <b>Broome</b>...).\n\n"
                            "<i>Apenas respondas, comenzará el acecho de nuevas ofertas en esa zona.</i>"
                        )
                    else:
                        chosen_city = normalize_city(text)
                        cfg["active_city"] = chosen_city
                        cfg["asked_for_city"] = False
                        cfg["query_index"] = 0
                        send_simple_message(
                            f"✅ <b>Ciudad activa: {html.escape(chosen_city)}</b>\n"
                            f"Modo acecho en tiempo real activado. Te notificaré en el instante "
                            f"en que se publique una nueva oferta en <b>{html.escape(chosen_city)}</b>.\n\n"
                            f"<i>(Para cambiar de ciudad cuando quieras, escribe el nuevo nombre o /ciudad).</i>"
                        )
    except Exception as e:
        print(f"[Aviso lectura Telegram]: {e}")

    if not cfg.get("active_city") and not cfg.get("asked_for_city"):
        cfg["asked_for_city"] = True
        send_simple_message(
            "👋 <b>¡Hola! ¿Dónde estás buscando trabajo en Australia?</b>\n\n"
            "Escribe en este chat el nombre de la ciudad (ej: <b>Perth</b>, <b>Sydney</b>, "
            "<b>Brisbane</b>, <b>Melbourne</b>, <b>Darwin</b>, <b>Karratha</b>...).\n\n"
            "<i>En cuanto respondas, empezaré a enviarte las vacantes recientes de esa ubicación.</i>"
        )

    save_config(cfg)
    return cfg

def is_valid_entry_job(title, company, description=""):
    full_text = f"{title} {company} {description}".lower()
    title_lower = title.lower()
    for bad in BLACKLIST_WORDS:
        if bad in title_lower:
            return False
    strict_desc_blocks = [
        "bachelor degree", "tertiary qualification in engineering", "australian citizens only",
        "must be an australian citizen", "permanent residents only", "ahpra registration"
    ]
    if any(block in full_text for block in strict_desc_blocks):
        return False
    return True

def is_priority_org(company):
    comp_lower = str(company).lower()
    return any(org in comp_lower for org in SERIOUS_ORGS)

def detect_postcode(location_text, description_text=""):
    combined = f"{location_text} {description_text}"
    matches = re.findall(r'\b(08\d{2}|[2-7]\d{3})\b', combined)
    for m in matches:
        if m not in ["2020", "2021", "2022", "2023", "2024", "2025", "2026", "2027", "2028"]:
            return f"{m} (Extraído del anuncio)"
    loc_lower = location_text.lower()
    for city, code_info in POSTCODE_MAP.items():
        if city in loc_lower:
            return code_info
    return "Consultar suburbio en el enlace"

def detect_prerequisites(text):
    t = text.lower()
    reqs = []
    if "white card" in t or "construction induction" in t:
        reqs.append("White Card (Tarjeta de construcción)")
    if "driver" in t or "licence" in t or "license" in t or "c class" in t or "manual" in t:
        reqs.append("Licencia de conducir")
    if "forklift" in t or "lf ticket" in t or "lf licence" in t:
        reqs.append("Ticket de Forklift (Grúa horquilla)")
    if "working at heights" in t or "wah" in t:
        reqs.append("Working at Heights (Trabajo en altura)")
    if "confined space" in t:
        reqs.append("Confined Space (Espacios confinados)")
    if "rsa" in t or "responsible service of alcohol" in t:
        reqs.append("RSA (Para servir alcohol)")
    if "police check" in t or "national police clearance" in t:
        reqs.append("Police Check (Certificado de antecedentes)")
    if "drug" in t or "alcohol screen" in t or "pre-employment medical" in t:
        reqs.append("Test de drogas y alcohol")
    if "hr licence" in t or "mr licence" in t or "heavy rigid" in t:
        reqs.append("Licencia de camión (MR/HR)")
    if "ppe" in t or "steel cap" in t:
        reqs.append("EPP básico (Bototos punta de acero / ropa reflectante)")
    if not reqs:
        return "Ningún ticket especial mencionado (Ideal para recién llegados)"
    return ", ".join(reqs)

def fallback_spanish_summary(title, details):
    t = f"{title} {details}".lower()
    explicaciones = []
    if "solar" in t:
        explicaciones.append("Trabajo operativo en planta solar (montaje de paneles, movimiento de materiales y asistencia en terreno).")
    if "fifo" in t or "utility" in t or "housekeeping" in t or "camp" in t:
        explicaciones.append("Puesto en campamento/hotel (limpieza de habitaciones, ayuda en cocina/comedor o mantenimiento general).")
    if "trade assistant" in t or "ta " in t:
        explicaciones.append("Ayudante de oficios técnicos (asistir a mecánicos, electricistas o soldadores pasando herramientas y preparando el área).")
    if "warehouse" in t or "pick" in t or "packer" in t or "storeperson" in t or "container" in t:
        explicaciones.append("Operario de bodega y logística (armado de pedidos, carga/descarga de contenedores e inventario).")
    if "labourer" in t or "civil" in t or "construction" in t:
        explicaciones.append("Ayudante general de construcción/obras civiles (preparación de terreno, manejo de herramientas manuales y apoyo a la cuadrilla).")
    if "kitchen" in t or "hospitality" in t or "food" in t:
        explicaciones.append("Apoyo en cocina y gastronomía (lavado de utensilios, preparación básica de alimentos y limpieza).")
    if "farm" in t or "agri" in t or "harvest" in t:
        explicaciones.append("Trabajo agrícola o de campo (cosecha, empaque, mantenimiento de cultivos o manejo de maquinaria básica).")
    if "factory" in t or "process worker" in t or "production" in t:
        explicaciones.append("Operario de planta de producción o fábrica (línea de ensamblaje, empaque y control básico).")
    if not explicaciones:
        explicaciones.append("Puesto operativo de entrada (asistencia física, tareas manuales y apoyo general al equipo en terreno).")
    return " ".join(explicaciones)

def analyze_with_ai_or_rules(job):
    raw_text = f"{job['title']} | {job['work_type']} | {job['summary']}"
    postcode = detect_postcode(job["location"], job["summary"])
    prereqs = detect_prerequisites(raw_text)
    es_explanation = fallback_spanish_summary(job["title"], job["summary"])

    if GROQ_API_KEY:
        prompt = (
            "Eres un asesor laboral experto en Australia para recién llegados. "
            "Analiza esta oferta en inglés y responde ÚNICAMENTE con un objeto JSON válido con estas 3 claves exactas en español:\n"
            "{\n"
            '  "explicacion": "Explica en 2 frases claras en español qué tareas hará exactamente en este trabajo",\n'
            '  "codigo_postal": "Código postal de 4 dígitos si aparece o el código postal aproximado de ese suburbio/ciudad en Australia",\n'
            '  "requisitos": "Lista corta en español de tickets, licencias o requisitos físicos que piden (o indica si no
