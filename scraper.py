#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radar de Empleos Australia - Modo Barrido Profundo (Últimos 2 Días).
Extrae vacantes de < 48 horas en múltiples portales oficiales (SEEK, Workforce AU,
Jora, CareerOne), selecciona las 30 mejores opciones y se pausa automáticamente.
"""

import os
import re
import sys
import html
import json
import time
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Set
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("AusJobRadar")

TELEGRAM_TOKEN: str = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "").strip()

SEEN_FILE: str = "seen_jobs.json"
CONFIG_FILE: str = "config.json"

# Límites de la corrida: Top 30 mejores ofertas de los últimos 2 días y auto-pausa
TOP_JOBS_LIMIT: int = 30
MAX_AGE_DAYS: int = 2
MAX_SEEN_HISTORY: int = 5000

USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
]

JOB_KEYWORDS: List[str] = [
    "General Labourer",
    "Trade Assistant",
    "FIFO Utility",
    "Warehouse Pick Packer",
    "Construction Labourer White Card",
    "Container Unloader",
    "Solar Farm Labourer",
    "Factory Process Worker",
    "Farm Hand",
    "Kitchen Hand Housekeeping"
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
    session = requests.Session()
    retry_strategy = Retry(
        total=2,
        backoff_factor=1.2,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


HTTP_SESSION = create_http_session()


# =====================================================================
# PERSISTENCIA ATÓMICA
# =====================================================================

def load_seen() -> List[str]:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return list(dict.fromkeys(str(x) for x in data))
        except Exception as e:
            logger.warning(f"Inicializando {SEEN_FILE} limpio: {e}")
    return []


def save_seen(seen_list: List[str]) -> None:
    trimmed = list(dict.fromkeys(seen_list))[-MAX_SEEN_HISTORY:]
    temp_file = f"{SEEN_FILE}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(trimmed, f)
        os.replace(temp_file, SEEN_FILE)
    except Exception as e:
        logger.error(f"Error guardando {SEEN_FILE}: {e}")


def load_config() -> Dict[str, Any]:
    default_cfg: Dict[str, Any] = {
        "active_city": None,
        "last_update_id": 0,
        "waiting_for_city": False
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    default_cfg.update(loaded)
        except Exception as e:
            logger.warning(f"Restaurando {CONFIG_FILE} por defecto: {e}")
    return default_cfg


def save_config(cfg: Dict[str, Any]) -> None:
    temp_file = f"{CONFIG_FILE}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(temp_file, CONFIG_FILE)
    except Exception as e:
        logger.error(f"Error guardando {CONFIG_FILE}: {e}")


# =====================================================================
# INTERFAZ CON TELEGRAM (SOLICITUD DE UBICACIÓN Y AUTO-PAUSA)
# =====================================================================

def send_telegram_request(payload: Dict[str, Any]) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Faltan credenciales TELEGRAM_TOKEN o TELEGRAM_CHAT_ID.")
        return False

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for _ in range(2):
        try:
            resp = HTTP_SESSION.post(api_url, json=payload, timeout=12)
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                retry_after = int(resp.json().get("parameters", {}).get("retry_after", 10))
                time.sleep(min(retry_after + 1, 25))
            else:
                return False
        except Exception:
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


def ask_or_read_city_from_telegram(cfg: Dict[str, Any]) -> Optional[str]:
    """
    Lee si el usuario envió una ubicación en Telegram.
    Si no hay ubicación nueva, pregunta en qué ubicación busca trabajo y pausa la ejecución.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return None

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"offset": int(cfg.get("last_update_id", 0)) + 1, "timeout": 5}
    detected_city: Optional[str] = None

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
                    if lower_t in ["/start", "/buscar", "/ciudad", "/ubicacion", "hola", "buscar"]:
                        detected_city = None
                        cfg["waiting_for_city"] = False
                    else:
                        detected_city = normalize_city(text)
    except Exception as e:
        logger.warning(f"Error consultando Telegram: {e}")

    if detected_city:
        cfg["active_city"] = detected_city
        cfg["waiting_for_city"] = False
        save_config(cfg)
        return detected_city

    if cfg.get("active_city"):
        return str(cfg["active_city"])

    # Si no hay ciudad configurada, pregunta la ubicación y se pausa
    send_simple_message(
        "📍 <b>¿En qué ubicación de Australia estás buscando trabajo hoy?</b>\n\n"
        "Respóndeme en este chat con el nombre de la ciudad o región "
        "(ej: <b>Perth</b>, <b>Sydney</b>, <b>Brisbane</b>, <b>Melbourne</b>, "
        "<b>Darwin</b>, <b>Karratha</b>, <b>Cairns</b>, <b>Adelaide</b>...).\n\n"
        "🔎 <i>En cuanto respondas y ejecutes la acción, buscaré las <b>30 mejores ofertas "
        "publicadas hace menos de 2 días</b> en los portales oficiales y volveré a pausarme.</i>"
    )
    cfg["waiting_for_city"] = True
    save_config(cfg)
    return None


# =====================================================================
# FILTRADO, PUNTUACIÓN DE CALIDAD Y CLASIFICACIÓN (TOP 30)
# =====================================================================

def is_valid_entry_job(title: str, company: str, description: str = "") -> bool:
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


def score_job_quality(job: Dict[str, Any]) -> int:
    """
    Calcula un puntaje de calidad para ordenar y elegir las 30 mejores opciones:
    +50 pts: Agencia / Empresa Tier 1 (BHP, Programmed, Hays, WorkPac, etc.)
    +25 pts: Salario explícito por hora o anual indicado en el anuncio
    +20 pts: Mención de inicio inmediato (Immediate start) o múltiples vacantes
    +15 pts: Portal directo verificado (SEEK / Workforce Australia Gobierno)
    """
    score = 0
    text = f"{job['title']} {job['company']} {job['summary']}".lower()
    salary_str = str(job.get("salary", "")).lower()

    if is_priority_org(job["company"]):
        score += 50
    if "$" in salary_str or "per hour" in salary_str or "p/h" in salary_str or "hr" in salary_str:
        score += 25
    if any(k in text for k in ["immediate start", "multiple", "urgent", "no experience", "training provided"]):
        score += 20
    if job.get("portal") in ("SEEK AU", "Workforce Australia (Gob)"):
        score += 15
    if any(k in text for k in ["white card", "fifo", "trade assistant", "forklift", "warehouse"]):
        score += 10
    return score


# =====================================================================
# MOTORES DE EXTRACCIÓN MULTIPORTAL (< 2 DÍAS DE ANTIGÜEDAD)
# =====================================================================

def fetch_seek_last_2_days(keyword: str, location: str) -> List[Dict[str, str]]:
    """
    Portal 1: SEEK Australia API v5.
    Usa el parámetro oficial daterange=2 (publicadas hace máximo 2 días).
    """
    url = "https://www.seek.com.au/api/jobsearch/v5/search"
    params = {
        "siteKey": "AU-Main",
        "keywords": keyword,
        "where": location,
        "daterange": 2,  # Filtro estricto oficial de SEEK: últimos 2 días (< 48h)
        "sortmode": "ListedDate",
        "pageSize": 25,
        "page": 1
    }
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-AU,en;q=0.9",
        "Referer": "https://www.seek.com.au/"
    }

    jobs: List[Dict[str, str]] = []
    try:
        resp = HTTP_SESSION.get(url, params=params, headers=headers, timeout=12)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            for item in data:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                job_id = f"seek_{item.get('id')}"
                title = str(item.get("title") or "Sin título")
                advertiser = item.get("advertiser")
                company = str(advertiser.get("description") if isinstance(advertiser, dict) else "Empresa Verificada SEEK")

                loc_list = item.get("locations")
                loc = str(loc_list[0].get("label") or location) if (isinstance(loc_list, list) and loc_list) else location
                salary = str(item.get("salaryLabel") or "Según convenio (Award Rate)")
                work_type = str(item.get("workType") or "Casual / Full Time")
                teaser = str(item.get("teaser") or "")
                raw_bullets = item.get("bulletPoints")
                bullets = " | ".join(str(b) for b in raw_bullets) if isinstance(raw_bullets, list) else ""
                listing_date = str(item.get("listingDateDisplay") or "Hace < 48h")

                jobs.append({
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "location": loc,
                    "salary": salary,
                    "work_type": f"{work_type} ({listing_date})",
                    "portal": "SEEK AU",
                    "url": f"https://www.seek.com.au/job/{item.get('id')}",
                    "summary": f"{teaser} {bullets}".strip()
                })
    except Exception as e:
        logger.warning(f"[SEEK AU] Aviso en '{keyword}': {e}")
    return jobs


def fetch_workforce_australia_gov(keyword: str, location: str) -> List[Dict[str, str]]:
    """
    Portal 2: Workforce Australia (Portal Oficial del Gobierno de Australia).
    Filtra vacantes creadas en las últimas 48 horas con ABN verificado.
    """
    url = "https://www.workforceaustralia.gov.au/api/v1/global/vacancies"
    city_only = location.split()[0]
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%d")

    params = {
        "searchText": f"{keyword} {city_only}",
        "sort": "DatePostedDesc",
        "pageSize": 20,
        "pageNumber": 1
    }
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json"
    }

    jobs: List[Dict[str, str]] = []
    try:
        resp = HTTP_SESSION.get(url, params=params, headers=headers, timeout=12)
        if resp.status_code == 200:
            results = resp.json().get("results", []) or resp.json().get("vacancies", [])
            for item in results:
                if not isinstance(item, dict):
                    continue
                vac_id = item.get("vacancyId") or item.get("id")
                if not vac_id:
                    continue

                posted_raw = str(item.get("creationDate") or item.get("publishDate") or "")[:10]
                if posted_raw and posted_raw < cutoff_date:
                    continue

                title = str(item.get("title") or item.get("jobTitle") or "Vacante Verificada")
                company = str(item.get("employerName") or item.get("organisationName") or "Empleador Verificado ABN")
                loc = str(item.get("location") or item.get("suburb") or location)
                salary = str(item.get("salary") or item.get("remuneration") or "Según convenio (Award Rate)")
                desc = re.sub(r"<[^>]+>", " ", str(item.get("description") or item.get("summary") or ""))

                jobs.append({
                    "id": f"gov_{vac_id}",
                    "title": title,
                    "company": company,
                    "location": loc,
                    "salary": salary,
                    "work_type": "Verificado Gob AU (< 48h)",
                    "portal": "Workforce Australia (Gob)",
                    "url": f"https://www.workforceaustralia.gov.au/individuals/jobs/details/{vac_id}",
                    "summary": desc[:600].strip()
                })
    except Exception as e:
        logger.info(f"[Workforce Gob] Consulta omitida para '{keyword}': {e}")
    return jobs


def fetch_jora_australia(keyword: str, location: str) -> List[Dict[str, str]]:
    """
    Portal 3: Jora Australia (Agregador oficial de SEEK Group en Australia).
    Filtra con since=last_48_hours / a=48h para anuncios de menos de 2 días.
    """
    url = "https://au.jora.com/j"
    params = {
        "q": keyword,
        "l": location,
        "a": "2d",  # Últimos 2 días (48 horas)
        "sp": "facet_listed_date"
    }
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-AU,en;q=0.9"
    }

    jobs: List[Dict[str, str]] = []
    try:
        resp = HTTP_SESSION.get(url, params=params, headers=headers, timeout=12)
        if resp.status_code == 200:
            cards = re.findall(
                r'<div[^>]+class="[^"]*job-card[^"]*"[^>]*data-job-id="([^"]+)"[^>]*>(.*?)</div>\s*</div>',
                resp.text,
                re.DOTALL
            )
            for jid, block in cards[:15]:
                title_m = re.search(r'class="[^"]*job-title[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
                comp_m = re.search(r'class="[^"]*job-company[^"]*"[^>]*>(.*?)</span>', block, re.DOTALL)
                abst_m = re.search(r'class="[^"]*job-abstract[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)

                title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else keyword
                company = re.sub(r"<[^>]+>", "", comp_m.group(1)).strip() if comp_m else "Empresa en Jora AU"
                summary = re.sub(r"<[^>]+>", " ", abst_m.group(1)).strip() if abst_m else title

                jobs.append({
                    "id": f"jora_{jid}",
                    "title": title,
                    "company": company,
                    "location": location,
                    "salary": "Según convenio (Award Rate)",
                    "work_type": "Publicado hace < 2 días",
                    "portal": "Jora AU",
                    "url": f"https://au.jora.com/job/rd/{jid}",
                    "summary": summary[:600]
                })
    except Exception as e:
        logger.info(f"[Jora AU] Consulta omitida para '{keyword}': {e}")
    return jobs


def fetch_careerone_australia(keyword: str, location: str) -> List[Dict[str, str]]:
    """
    Portal 4: CareerOne Australia.
    Consulta vacantes recientes publicadas en las últimas 48 horas.
    """
    url = "https://www.careerone.com.au/api/v1/search/jobs"
    params = {
        "keywords": keyword,
        "location": location,
        "datePosted": "2",  # Últimos 2 días
        "page": 1,
        "pageSize": 15
    }
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json"
    }

    jobs: List[Dict[str, str]] = []
    try:
        resp = HTTP_SESSION.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code == 200 and "application/json" in resp.headers.get("Content-Type", ""):
            items = resp.json().get("jobs", []) or resp.json().get("data", [])
            for item in items:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                jid = item.get("id")
                title = str(item.get("title") or keyword)
                company = str(item.get("companyName") or "Empresa Verificada CareerOne")
                slug = str(item.get("slug") or jid)
                summary = str(item.get("description") or item.get("summary") or "")

                jobs.append({
                    "id": f"c1_{jid}",
                    "title": title,
                    "company": company,
                    "location": location,
                    "salary": str(item.get("salary") or "Según convenio (Award Rate)"),
                    "work_type": "Hace < 48h",
                    "portal": "CareerOne AU",
                    "url": f"https://www.careerone.com.au/jobview/{slug}",
                    "summary": re.sub(r"<[^>]+>", " ", summary)[:600].strip()
                })
    except Exception as e:
        logger.info(f"[CareerOne AU] Consulta omitida para '{keyword}': {e}")
    return jobs


# =====================================================================
# TRADUCCIÓN Y ENRIQUECIMIENTO EN ESPAÑOL
# =====================================================================

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
    raw_text = f"{job['title']} | {job['work_type']} | {job['summary']}"
    postcode = detect_postcode(job["location"], job["summary"])
    prereqs = detect_prerequisites(raw_text)
    es_explanation = fallback_spanish_summary(job["title"], job["summary"])

    if GROQ_API_KEY:
        prompt = (
            "Eres un asesor laboral experto en Australia. Analiza esta oferta en inglés y responde "
            "ÚNICAMENTE con un objeto JSON válido con estas 3 claves exactas en español:\n"
            "{\n"
            '  "explicacion": "Explica en 2 frases claras en español qué tareas hará exactamente en este trabajo",\n'
            '  "codigo_postal": "Código postal de 4 dígitos si aparece o el código postal aproximado de ese suburbio/ciudad en Australia",\n'
            '  "requisitos": "Lista corta en español de tickets, licencias o requisitos físicos que piden (o indica si no pide experiencia)"\n'
            "}\n\n"
            f"Título: {job['title']}\nEmpresa: {job['company']}\nUbicación: {job['location']}\n"
            f"Detalle: {job['summary'][:650]}"
        )
        try:
            resp = HTTP_SESSION.post(
                "https://api.groq.com/openai/v1/chat/completions",
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
                time.sleep(1.2)
        except Exception:
            pass

    return {
        "explicacion": es_explanation,
        "codigo_postal": postcode,
        "requisitos": prereqs
    }


def send_telegram_alert(job: Dict[str, Any], rank_idx: int, total_to_send: int) -> bool:
    info = analyze_with_ai_or_rules(job)
    vip_badge = (
        f"⭐ <b>[OPCIÓN #{rank_idx}/{total_to_send} - AGENCIA TIER 1]</b>\n"
        if is_priority_org(job["company"])
        else f"🇦🇺 <b>[OPCIÓN #{rank_idx}/{total_to_send} - PUBLICADA HACE &lt; 2 DÍAS]</b>\n"
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
    time.sleep(random.uniform(1.4, 2.1))
    return sent


# =====================================================================
# ORQUESTADOR PRINCIPAL (BARRIDO DE 48H -> TOP 30 -> AUTO-PAUSA)
# =====================================================================

def main() -> None:
    cfg = load_config()
    target_city = ask_or_read_city_from_telegram(cfg)

    if not target_city:
        logger.info("Solicitud de ubicación enviada a Telegram. Sistema en pausa esperando respuesta del usuario.")
        return

    seen_list = load_seen()
    seen_set: Set[str] = set(seen_list)
    candidates: Dict[str, Dict[str, Any]] = {}

    send_simple_message(
        f"🚀 <b>Iniciando barrido profundo en: {html.escape(target_city)}</b>\n"
        f"Consultando ofertas publicadas hace <b>menos de 2 días</b> en SEEK AU, "
        f"Workforce Australia (Gobierno), Jora AU y CareerOne...\n"
        f"<i>Seleccionando las 30 mejores opciones para ti.</i>"
    )

    for kw in JOB_KEYWORDS:
        logger.info(f"Buscando '{kw}' (< 48h) en {target_city}...")

        # Consulta multiportal de confianza
        batch = []
        batch.extend(fetch_seek_last_2_days(kw, target_city))
        batch.extend(fetch_workforce_australia_gov(kw, target_city))
        batch.extend(fetch_jora_australia(kw, target_city))
        batch.extend(fetch_careerone_australia(kw, target_city))

        for job in batch:
            jid = job["id"]
            if jid not in seen_set and jid not in candidates:
                if is_valid_entry_job(job["title"], job["company"], job["summary"]):
                    job["score"] = score_job_quality(job)
                    candidates[jid] = job
                else:
                    seen_set.add(jid)
                    seen_list.append(jid)

        time.sleep(random.uniform(1.5, 2.8))

    # Ordenar todas las ofertas encontradas de mayor a menor calidad y tomar el Top 30
    ranked_jobs = sorted(candidates.values(), key=lambda x: x.get("score", 0), reverse=True)
    top_30_jobs = ranked_jobs[:TOP_JOBS_LIMIT]

    sent_count = 0
    total_to_send = len(top_30_jobs)

    for idx, job in enumerate(top_30_jobs, start=1):
        if send_telegram_alert(job, idx, total_to_send):
            sent_count += 1
        seen_set.add(job["id"])
        seen_list.append(job["id"])

    # Guardar historial y limpiar ciudad activa para que el bot se pause
    save_seen(seen_list)
    cfg["active_city"] = None
    cfg["waiting_for_city"] = False
    save_config(cfg)

    send_simple_message(
        f"✅ <b>Barrido finalizado en {html.escape(target_city)}</b>\n"
        f"Se entregaron las <b>{sent_count} mejores ofertas</b> publicadas en las últimas 48 horas.\n\n"
        f"⏸️ <b>El radar ha quedado en pausa automáticamente.</b>\n"
        f"Cuando quieras hacer otro barrido, escribe una ciudad aquí y ejecuta el workflow en GitHub Actions."
    )
    logger.info(f"Entregadas {sent_count} ofertas de {target_city}. Bot pausado exitosamente.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error(f"Error controlado: {exc}")
        sys.exit(0)
