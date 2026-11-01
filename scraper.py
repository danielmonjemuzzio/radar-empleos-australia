#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor Automatizado de Vacantes en Tiempo Real (SEEK Australia).
Arquitectura tolerante a fallos con rotación de lotes, persistencia atómica
e integración bidireccional con Telegram y Groq LLM.
"""

import os
import re
import sys
import html
import json
import time
import random
import logging
from typing import Dict, List, Optional, Any, Set
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configuración de Logging Profesional para GitHub Actions
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SeekMonitor")

# Variables de Entorno
TELEGRAM_TOKEN: str = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "").strip()

# Archivos de Persistencia
SEEN_FILE: str = "seen_jobs.json"
CONFIG_FILE: str = "config.json"

# Parámetros Operativos de Acecho (Stealth & Rate Limiting)
MAX_JOBS_PER_RUN: int = 12
QUERIES_PER_RUN: int = 3
MAX_SEEN_HISTORY: int = 4000

USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
]

JOB_KEYWORDS: List[str] = [
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

AUSTRALIAN_CITIES: Dict[str, str] = {
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

SERIOUS_ORGS: List[str] = [
    "programmed", "workpac", "hays", "chandler macleod", "adecco", "randstad",
    "monadelphous", "ventia", "downer", "bhp", "rio tinto", "fortescue", "fmg",
    "mineral resources", "minres", "macmahon", "perenti", "sodexo", "compass group",
    "iss facility", "civeo", "acciona", "lendlease", "cpb contractors", "bmd",
    "corestaff", "techforce", "linkforce", "agrifood", "costa group", "action workforce",
    "hoban", "persolkelly", "labourpower", "skout", "awx", "recruitwest"
]

BLACKLIST_WORDS: List[str] = [
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

POSTCODE_MAP: Dict[str, str] = {
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


def create_http_session() -> requests.Session:
    """Crea una sesión HTTP robusta con reintentos automáticos ante fallos de red."""
    session = requests.Session()
    retry_strategy = Retry(
        total=2,
        backoff_factor=1.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


HTTP_SESSION = create_http_session()


# =====================================================================
# GESTIÓN ATÓMICA DE ARCHIVOS Y ESTADO
# =====================================================================

def load_seen() -> List[str]:
    """Carga la lista de empleos vistos garantizando integridad de datos."""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return list(dict.fromkeys(str(x) for x in data))
        except Exception as e:
            logger.warning(f"Archivo {SEEN_FILE} ilegible, inicializando limpio: {e}")
    return []


def save_seen(seen_list: List[str]) -> None:
    """Guarda los IDs vistos de forma atómica para evitar corrupción."""
    trimmed = list(dict.fromkeys(seen_list))[-MAX_SEEN_HISTORY:]
    temp_file = f"{SEEN_FILE}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(trimmed, f)
        os.replace(temp_file, SEEN_FILE)
    except Exception as e:
        logger.error(f"Error guardando {SEEN_FILE}: {e}")


def load_config() -> Dict[str, Any]:
    """Carga la configuración operativa con valores por defecto seguros."""
    default_cfg: Dict[str, Any] = {
        "active_city": None,
        "last_update_id": 0,
        "asked_for_city": False,
        "query_index": 0
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    default_cfg.update(loaded)
        except Exception as e:
            logger.warning(f"Archivo {CONFIG_FILE} ilegible, restaurando valores por defecto: {e}")
    return default_cfg


def save_config(cfg: Dict[str, Any]) -> None:
    """Guarda la configuración de manera atómica."""
    temp_file = f"{CONFIG_FILE}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(temp_file, CONFIG_FILE)
    except Exception as e:
        logger.error(f"Error guardando {CONFIG_FILE}: {e}")


# =====================================================================
# COMUNICACIÓN CON TELEGRAM
# =====================================================================

def send_telegram_request(payload: Dict[str, Any]) -> bool:
    """Despacha mensajes a la API de Telegram controlando límites de tasa (HTTP 429)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Faltan credenciales TELEGRAM_TOKEN o TELEGRAM_CHAT_ID.")
        return False

    api_url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){TELEGRAM_TOKEN}/sendMessage"
    for _ in range(2):
        try:
            resp = HTTP_SESSION.post(api_url, json=payload, timeout=12)
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                retry_after = int(resp.json().get("parameters", {}).get("retry_after", 10))
                logger.warning(f"Rate limit en Telegram. Pausando por {retry_after}s...")
                time.sleep(min(retry_after + 1, 25))
            else:
                logger.warning(f"Telegram devolvió código {resp.status_code}: {resp.text[:120]}")
                return False
        except Exception as e:
            logger.warning(f"Excepción de red contactando a Telegram: {e}")
            time.sleep(2)
    return False


def send_simple_message(text_html: str) -> None:
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    send_telegram_request(payload)


def normalize_city(user_text: str) -> str:
    clean = user_text.strip().lower()
    if clean in AUSTRALIAN_CITIES:
        return AUSTRALIAN_CITIES[clean]
    for key, val in AUSTRALIAN_CITIES.items():
        if key in clean:
            return val
    return user_text.strip().title()


def check_telegram_city_selection(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Sincroniza comandos entrantes del usuario en Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return cfg

    api_url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){TELEGRAM_TOKEN}/getUpdates"
    params = {"offset": int(cfg.get("last_update_id", 0)) + 1, "timeout": 4}

    try:
        resp = HTTP_SESSION.get(api_url, params=params, timeout=10)
        if resp.status_code == 200:
            updates = resp.json().get("result", [])
            for u in updates:
                update_id = int(u.get("update_id", 0))
                if update_id > int(cfg.get("last_update_id", 0)):
                    cfg["last_update_id"] = update_id

                msg = u.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = str(msg.get("text", "")).strip()

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
                        logger.info(f"Nueva ciudad configurada vía Telegram: {chosen_city}")
                        send_simple_message(
                            f"✅ <b>Ciudad activa: {html.escape(chosen_city)}</b>\n"
                            f"Modo acecho en tiempo real activado. Recibirás únicamente las vacantes "
                            f"recién publicadas en <b>{html.escape(chosen_city)}</b>.\n\n"
                            f"<i>(Para cambiar de ciudad cuando quieras, escribe el nuevo nombre o /ciudad).</i>"
                        )
    except Exception as e:
        logger.warning(f"No se pudieron consultar actualizaciones de Telegram: {e}")

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


# =====================================================================
# MOTOR DE FILTRADO Y ANÁLISIS DE OFERTAS
# =====================================================================

def is_valid_entry_job(title: str, company: str, description: str = "") -> bool:
    """Filtra cargos ejecutivos, profesionales con título o bloqueados por ciudadanía."""
    full_text = f"{title} {company} {description}".lower()
    title_lower = title.lower()

    for bad in BLACKLIST_WORDS:
        if bad in title_lower:
            return False

    strict_desc_blocks = [
        "bachelor degree", "tertiary qualification in engineering", "australian citizens only",
        "must be an australian citizen", "permanent residents only", "ahpra registration"
    ]
    return not any(block in full_text for block in strict_desc_blocks)


def is_priority_org(company: str) -> bool:
    comp_lower = str(company).lower()
    return any(org in comp_lower for org in SERIOUS_ORGS)


def detect_postcode(location_text: str, description_text: str = "") -> str:
    combined = f"{location_text} {description_text}"
    matches = re.findall(r"\b(08\d{2}|[2-7]\d{3})\b", combined)
    excluded_years = {"2020", "2021", "2022", "2023", "2024", "2025", "2026", "2027", "2028"}
    for m in matches:
        if m not in excluded_years:
            return f"{m} (Extraído del anuncio)"

    loc_lower = location_text.lower()
    for city, code_info in POSTCODE_MAP.items():
        if city in loc_lower:
            return code_info
    return "Consultar suburbio en el enlace"


def detect_prerequisites(text: str) -> str:
    t = text.lower()
    reqs = []
    if "white card" in t or "construction induction" in t:
        reqs.append("White Card (Tarjeta de construcción)")
    if any(k in t for k in ["driver", "licence", "license", "c class", "manual"]):
        reqs.append("Licencia de conducir")
    if any(k in t for k in ["forklift", "lf ticket", "lf licence"]):
        reqs.append("Ticket de Forklift (Grúa horquilla)")
    if "working at heights" in t or "wah" in t:
        reqs.append("Working at Heights (Trabajo en altura)")
    if "confined space" in t:
        reqs.append("Confined Space (Espacios confinados)")
    if "rsa" in t or "responsible service of alcohol" in t:
        reqs.append("RSA (Para servir alcohol)")
    if "police check" in t or "national police clearance" in t:
        reqs.append("Police Check (Certificado de antecedentes)")
    if any(k in t for k in ["drug", "alcohol screen", "pre-employment medical"]):
        reqs.append("Test de drogas y alcohol")
    if any(k in t for k in ["hr licence", "mr licence", "heavy rigid"]):
        reqs.append("Licencia de camión (MR/HR)")
    if "ppe" in t or "steel cap" in t:
        reqs.append("EPP básico (Bototos punta de acero / ropa reflectante)")

    return ", ".join(reqs) if reqs else "Ningún ticket especial mencionado (Ideal para recién llegados)"


def fallback_spanish_summary(title: str, details: str) -> str:
    t = f"{title} {details}".lower()
    explicaciones = []
    if "solar" in t:
        explicaciones.append("Trabajo operativo en planta solar (montaje de paneles, movimiento de materiales y asistencia en terreno).")
    if any(k in t for k in ["fifo", "utility", "housekeeping", "camp"]):
        explicaciones.append("Puesto en campamento/hotel (limpieza de habitaciones, ayuda en cocina/comedor o mantenimiento general).")
    if "trade assistant" in t or "ta " in t:
        explicaciones.append("Ayudante de oficios técnicos (asistir a mecánicos, electricistas o soldadores pasando herramientas y preparando el área).")
    if any(k in t for k in ["warehouse", "pick", "packer", "storeperson", "container"]):
        explicaciones.append("Operario de bodega y logística (armado de pedidos, carga/descarga de contenedores e inventario).")
    if any(k in t for k in ["labourer", "civil", "construction"]):
        explicaciones.append("Ayudante general de construcción/obras civiles (preparación de terreno, manejo de herramientas manuales y apoyo a la cuadrilla).")
    if any(k in t for k in ["kitchen", "hospitality", "food"]):
        explicaciones.append("Apoyo en cocina y gastronomía (lavado de utensilios, preparación básica de alimentos y limpieza).")
    if any(k in t for k in ["farm", "agri", "harvest"]):
        explicaciones.append("Trabajo agrícola o de campo (cosecha, empaque, mantenimiento de cultivos o manejo de maquinaria básica).")
    if any(k in t for k in ["factory", "process worker", "production"]):
        explicaciones.append("Operario de planta de producción o fábrica (línea de ensamblaje, empaque y control básico).")

    if not explicaciones:
        explicaciones.append("Puesto operativo de entrada (asistencia física, tareas manuales y apoyo general al equipo en terreno).")
    return " ".join(explicaciones)


def parse_ai_json_safely(raw_content: str) -> Optional[Dict[str, Any]]:
    """Extrae y valida objetos JSON incluso si el LLM envuelve el texto en bloques Markdown."""
    try:
        return json.loads(raw_content)
    except Exception:
        match = re.search(r"\{.*\}", raw_content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return None
    return None


def analyze_with_ai_or_rules(job: Dict[str, str]) -> Dict[str, str]:
    """Genera el resumen en español con Groq o recurre de forma transparente al motor local."""
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
            '  "requisitos": "Lista corta en español de tickets, licencias o requisitos físicos que piden (o indica si no pide experiencia)"\n'
            "}\n\n"
            f"Título: {job['title']}\nEmpresa: {job['company']}\nUbicación: {job['location']}\n"
            f"Tipo: {job['work_type']}\nDetalle: {job['summary'][:700]}"
        )
        try:
            resp = HTTP_SESSION.post(
                "[https://api.groq.com/openai/v1/chat/completions](https://api.groq.com/openai/v1/chat/completions)",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"}
                },
                timeout=8
            )
            if resp.status_code == 200:
                content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                parsed = parse_ai_json_safely(content)
                if parsed:
                    es_explanation = str(parsed.get("explicacion") or es_explanation)
                    postcode = str(parsed.get("codigo_postal") or postcode)
                    prereqs = str(parsed.get("requisitos") or prereqs)
                time.sleep(random.uniform(1.5, 2.3))
        except Exception as e:
            logger.info(f"Usando motor de reglas local para '{job['title'][:30]}' ({e})")

    return {
        "explicacion": es_explanation,
        "codigo_postal": postcode,
        "requisitos": prereqs
    }


# =====================================================================
# CLIENTE DE EXTRACCIÓN SEEK AUSTRALIA (MODO ACECHO)
# =====================================================================

def fetch_seek_api_stealth(keyword: str, location: str) -> Optional[List[Dict[str, str]]]:
    """Consulta la API v5 de SEEK ordenando estrictamente por fecha de publicación (ListedDate)."""
    url = "[https://www.seek.com.au/api/jobsearch/v5/search](https://www.seek.com.au/api/jobsearch/v5/search)"
    params = {
        "siteKey": "AU-Main",
        "keywords": keyword,
        "where": location,
        "sortmode": "ListedDate",
        "pageSize": 25,
        "page": 1
    }
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-AU,en;q=0.9",
        "Referer": "[https://www.seek.com.au/](https://www.seek.com.au/)",
        "Origin": "[https://www.seek.com.au](https://www.seek.com.au)"
    }

    jobs: List[Dict[str, str]] = []
    try:
        resp = HTTP_SESSION.get(url, params=params, headers=headers, timeout=12)
        if resp.status_code in (403, 429):
            logger.warning(f"Protección Anti-Ban activada (HTTP {resp.status_code}). Cortando turno de forma segura.")
            return None

        if resp.status_code == 200:
            data = resp.json().get("data", [])
            for item in data:
                if not isinstance(item, dict) or not item.get("id"):
                    continue

                job_id = f"seek_{item.get('id')}"
                title = str(item.get("title") or "Sin título")

                advertiser = item.get("advertiser")
                company = str(advertiser.get("description") if isinstance(advertiser, dict) else "Empresa Verificada en SEEK")

                loc_list = item.get("locations")
                if isinstance(loc_list, list) and len(loc_list) > 0 and isinstance(loc_list[0], dict):
                    loc = str(loc_list[0].get("label") or location)
                else:
                    loc = location

                salary = str(item.get("salaryLabel") or "Según convenio (Award Rate)")
                work_type = str(item.get("workType") or "Casual / Full Time")
                teaser = str(item.get("teaser") or "")

                raw_bullets = item.get("bulletPoints")
                bullets = " | ".join(str(b) for b in raw_bullets) if isinstance(raw_bullets, list) else ""
                full_summary = f"{teaser} {bullets}".strip()

                jobs.append({
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "location": loc,
                    "salary": salary,
                    "work_type": work_type,
                    "portal": "SEEK AU",
                    "url": f"[https://www.seek.com.au/job/](https://www.seek.com.au/job/){item.get('id')}",
                    "summary": full_summary
                })
    except Exception as e:
        logger.warning(f"Error consultando SEEK para '{keyword}': {e}")

    return jobs


def send_telegram_alert(job: Dict[str, str]) -> bool:
    info = analyze_with_ai_or_rules(job)
    vip_badge = (
        "⭐ <b>[AGENCIA / EMPRESA TOP TIER 1]</b>\n"
        if is_priority_org(job["company"])
        else "🇦🇺 <b>[OFERTA RECIÉN PUBLICADA]</b>\n"
    )

    msg = (
        f"{vip_badge}"
        f"📌 <b>{html.escape(job['title'])}</b>\n"
        f"🏢 <b>Empresa:</b> {html.escape(job['company'])}\n"
        f"📍 <b>Ubicación:</b> {html.escape(job['location'])}\n"
        f"📮 <b>Código Postal:</b> {html.escape(info['codigo_postal'])}\n"
        f"💰 <b>Salario:</b> {html.escape(job['salary'])} ({html.escape(job['work_type'])})\n\n"
        f"🇪🇸 <b>¿De qué trata el trabajo?:</b>\n{html.escape(info['explicacion'])}\n\n"
        f"🪪 <b>Prerrequisitos / Tickets:</b>\n{html.escape(info['requisitos'])}\n\n"
        f"🌐 <b>Portal:</b> {html.escape(job['portal'])}\n"
        f"🔗 <a href=\"{job['url']}\">POSTULAR AHORA DIRECTO</a>"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    sent = send_telegram_request(payload)
    time.sleep(random.uniform(1.8, 2.6))
    return sent


# =====================================================================
# ORQUESTADOR PRINCIPAL
# =====================================================================

def main() -> None:
    cfg = load_config()
    cfg = check_telegram_city_selection(cfg)
    active_city = cfg.get("active_city")

    if not active_city:
        logger.info("Sistema en espera: el usuario aún no ha seleccionado una ciudad en Telegram.")
        return

    seen_list = load_seen()
    seen_set: Set[str] = set(seen_list)
    new_jobs_count = 0

    start_idx = int(cfg.get("query_index", 0)) % len(JOB_KEYWORDS)
    selected_keywords = [
        JOB_KEYWORDS[(start_idx + i) % len(JOB_KEYWORDS)]
        for i in range(QUERIES_PER_RUN)
    ]

    cfg["query_index"] = (start_idx + QUERIES_PER_RUN) % len(JOB_KEYWORDS)
    save_config(cfg)

    logger.info(f"Acecho activo en [{active_city}] | Lote actual: {selected_keywords}")

    for kw in selected_keywords:
        if new_jobs_count >= MAX_JOBS_PER_RUN:
            break

        time.sleep(random.uniform(3.5, 6.0))
        found_jobs = fetch_seek_api_stealth(kw, active_city)

        if found_jobs is None:
            break

        for job in found_jobs:
            if new_jobs_count >= MAX_JOBS_PER_RUN:
                break

            job_id = job["id"]
            if job_id not in seen_set:
                if is_valid_entry_job(job["title"], job["company"], job["summary"]):
                    if send_telegram_alert(job):
                        new_jobs_count += 1
                seen_set.add(job_id)
                seen_list.append(job_id)

    save_seen(seen_list)
    logger.info(f"Ciclo finalizado correctamente. Alertas nuevas enviadas: {new_jobs_count}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error(f"Fallo crítico amortiguado (Exit 0 para proteger el workflow): {exc}")
        sys.exit(0)
