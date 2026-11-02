#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radar de Empleos Australia - Especializado en Perfil Clásico WHV 462.
Filtra ofertas de < 48 horas en SEEK, Workforce Australia, Jora y CareerOne.
Excluye carreras universitarias, prioriza oficios con tickets cortos (Forklift, RSA,
Traffic Controller, White Card, Barista, Farm, Hospitality) y analiza la realidad
del puesto con IA antes de pausarse automáticamente tras entregar el Top 30.
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
logger = logging.getLogger("AusJobRadar462")

TELEGRAM_TOKEN: str = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "").strip()

SEEN_FILE: str = "seen_jobs.json"
CONFIG_FILE: str = "config.json"

# Límites operativos: Top 30 mejores ofertas (< 48h) y auto-pausa
TOP_JOBS_LIMIT: int = 30
MAX_AGE_DAYS: int = 2
MAX_SEEN_HISTORY: int = 5000

USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
]

# 1. BÚSQUEDAS CLÁSICAS DE ALTA ROTACIÓN PARA VISA 462 (Cursos cortos + Entrada directa)
JOB_KEYWORDS: List[str] = [
    "Forklift Driver LF",
    "Traffic Controller",
    "Bartender RSA Bar Staff",
    "Barista Cafe All Rounder",
    "Kitchen Hand Food Prep",
    "Housekeeping Room Attendant Cleaner",
    "General Labourer White Card",
    "Warehouse Pick Packer Container",
    "Farm Hand Fruit Picker Nursery",
    "FIFO Utility Mine Site Cleaner",
    "Trade Assistant Construction",
    "Event Crew Stadium Staff"
]

# 2. DICCIONARIO DE CIUDADES Y REGIONES DE AUSTRALIA
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
    "bowen": "Bowen QLD", "bundaberg": "Bundaberg QLD", "airlie beach": "Airlie Beach QLD",
    "darwin": "Darwin NT", "alice springs": "Alice Springs NT", "adelaide": "Adelaide SA",
    "hobart": "Hobart TAS", "canberra": "Canberra ACT"
}

# 3. AGENCIAS Y EMPRESAS CONOCIDAS POR CONTRATAR WHV
SERIOUS_ORGS: List[str] = [
    "programmed", "workpac", "hays", "chandler macleod", "adecco", "randstad",
    "monadelphous", "ventia", "downer", "bhp", "rio tinto", "fortescue", "fmg",
    "mineral resources", "minres", "macmahon", "perenti", "sodexo", "compass group",
    "iss facility", "civeo", "acciona", "lendlease", "cpb contractors", "bmd",
    "corestaff", "techforce", "linkforce", "agrifood", "costa group", "action workforce",
    "hoban", "persolkelly", "labourpower", "skout", "awx", "recruitwest", "sidekicker",
    "supple", "pinnacle people", "the star", "crown", "merivale", "alh group", "altus traffic",
    "evolution traffic", "warp traffic", "linfox", "toll", "dhl"
]

# 4. BLOQUEO ESTRICTO: Cero títulos universitarios, cero diplomados largos y cero cargos ejecutivos
BLACKLIST_WORDS: List[str] = [
    "engineer", "engineering", "doctor", "medical", "physician", "surgeon",
    "registered nurse", "nursing", "clinical", "pharmacist", "dentist", "psychologist",
    "physiotherapist", "occupational therapist", "veterinarian", "vet ", "radiographer",
    "architect", "architecture", "draftsperson", "lawyer", "solicitor", "legal counsel",
    "accountant", "accounting", "auditor", "actuary", "geologist", "geophysicist",
    "metallurgist", "surveyor", "quantity surveyor", "agronomist", "teacher", "lecturer",
    "bachelor", "master's", "phd", "tertiary qualification", "university degree",
    "degree in", "diploma of", "advanced diploma", "cert iii", "cert iv", "certificate iii",
    "certificate iv", "trade qualified", "qualified electrician", "qualified plumber",
    "qualified carpenter", "qualified boilermaker", "qualified mechanic", "hd fitter",
    "senior manager", "general manager", "director", "principal", "head of",
    "superintendent", "project manager", "area manager", "operations manager",
    "australian citizen", "citizens only", "pr only", "permanent resident only",
    "nv1", "nv2", "baseline clearance", "unpaid", "commission only", "survey",
    "au pair", "mystery shopper", "mlm", "crypto", "volunteer", "internship"
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
    "bowen": "4805 (QLD)", "bundaberg": "4670 (QLD)", "airlie beach": "4802 (QLD)",
    "brisbane": "4000 (QLD)", "gold coast": "4217 (QLD)", "sunshine coast": "4558 (QLD)",
    "sydney": "2000 (NSW)", "newcastle": "2300 (NSW)", "wollongong": "2500 (NSW)",
    "byron bay": "2481 (NSW)", "melbourne": "3000 (VIC)", "geelong": "3220 (VIC)",
    "adelaide": "5000 (SA)", "hobart": "7000 (TAS)", "canberra": "2600 (ACT)"
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

    send_simple_message(
        "📍 <b>¿En qué ubicación de Australia estás buscando trabajo hoy?</b>\n\n"
        "Respóndeme con el nombre de la ciudad o región "
        "(ej: <b>Perth</b>, <b>Sydney</b>, <b>Brisbane</b>, <b>Melbourne</b>, "
        "<b>Gold Coast</b>, <b>Cairns</b>, <b>Darwin</b>, <b>Margaret River</b>...).\n\n"
        "🎒 <i>Buscaré las <b>30 mejores ofertas clásicas para WHV 462</b> publicadas hace "
        "menos de 2 días (Forklift, Barman/RSA, Traffic Control, Labourer, Bodega, Hospitality, Farm) "
        "y luego me pausaré automáticamente.</i>"
    )
    cfg["waiting_for_city"] = True
    save_config(cfg)
    return None


# =====================================================================
# FILTRADO ESTRICTO WHV 462 Y PUNTUACIÓN DE CALIDAD (TOP 30)
# =====================================================================

def is_valid_whv_job(title: str, company: str, description: str = "") -> bool:
    """
    Descarta cualquier empleo que pida título universitario, diplomados largos
    o ciudadanía australiana. Mantiene empleos operativos y de cursos rápidos.
    """
    full_text = f"{title} {company} {description}".lower()
    title_lower = title.lower()

    for bad in BLACKLIST_WORDS:
        if bad in title_lower:
            return False

    strict_desc_blocks = [
        "bachelor degree", "bachelor's degree", "master's degree", "tertiary qualification",
        "university degree", "must hold a degree", "australian citizens only",
        "must be an australian citizen", "permanent residents only", "ahpra registration",
        "minimum 5 years experience", "minimum 10 years"
    ]
    return not any(block in full_text for block in strict_desc_blocks)


def is_priority_org(company: str) -> bool:
    comp_lower = str(company).lower()
    return any(org in comp_lower for org in SERIOUS_ORGS)


def score_whv_job_quality(job: Dict[str, Any]) -> int:
    """
    Puntúa más alto las ofertas ideales para Visa 462:
    +45 pts: Agencia / Empleador conocido por contratar WHV
    +35 pts: Pide cursos cortos clásicos (Forklift LF, RSA, Traffic Control, White Card, Barista)
    +25 pts: Muestra tarifa por hora explícita ($30-$50/hr, casual loading, penalty rates)
    +25 pts: Inicio inmediato (Immediate start, Casual, No experience required, Training provided)
    +15 pts: Portal directo (SEEK AU / Workforce Australia)
    """
    score = 0
    text = f"{job['title']} {job['company']} {job['summary']}".lower()
    salary_str = str(job.get("salary", "")).lower()

    if is_priority_org(job["company"]):
        score += 45

    whv_classic_tickets = [
        "forklift", "lf ticket", "traffic control", "tc ticket", "white card",
        "rsa", "rcg", "rsg", "barista", "bartender", "pick packer", "container",
        "kitchen hand", "housekeeping", "room attendant", "farm hand", "fifo"
    ]
    if any(k in text for k in whv_classic_tickets):
        score += 35

    if "$" in salary_str or "per hour" in salary_str or "p/h" in salary_str or "/hr" in salary_str:
        score += 25

    if any(k in text for k in [
        "immediate start", "multiple", "urgent", "no experience",
        "training provided", "casual", "backpacker", "working holiday", "whv"
    ]):
        score += 25

    if job.get("portal") in ("SEEK AU", "Workforce Australia (Gob)"):
        score += 15

    return score


# =====================================================================
# MOTORES DE EXTRACCIÓN MULTIPORTAL (< 2 DÍAS DE ANTIGÜEDAD)
# =====================================================================

def fetch_seek_last_2_days(keyword: str, location: str) -> List[Dict[str, str]]:
    url = "https://www.seek.com.au/api/jobsearch/v5/search"
    params = {
        "siteKey": "AU-Main",
        "keywords": keyword,
        "where": location,
        "daterange": 2,
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
    url = "https://au.jora.com/j"
    params = {
        "q": keyword,
        "l": location,
        "a": "2d",
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
    url = "https://www.careerone.com.au/api/v1/search/jobs"
    params = {
        "keywords": keyword,
        "location": location,
        "datePosted": "2",
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
# DETECTOR PROFUNDO DE TICKETS WHV Y ANÁLISIS REALISTA CON IA
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


def detect_whv_prerequisites(text: str) -> str:
    """Detecta todos los cursos cortos clásicos de WHV 462 y requisitos fáciles de cumplir."""
    t = text.lower()
    reqs = []
    if any(k in t for k in ["forklift", "lf ticket", "lf licence", "high risk work", "lo ticket", "order picker"]):
        reqs.append("🚜 Ticket de Forklift (LF/LO - Curso de 2 días)")
    if any(k in t for k in ["traffic control", "tc ticket", "stop/slow", "implement traffic", "prepare work zone"]):
        reqs.append("🛑 Ticket de Traffic Controller (TC + White Card - Curso de 1 a 2 días)")
    if any(k in t for k in ["white card", "construction induction", "general construction"]):
        reqs.append("🪪 White Card (Inducción de construcción - Curso de 1 día)")
    if any(k in t for k in ["rsa", "responsible service of alcohol"]):
        reqs.append("🍺 RSA (Certificado para servir alcohol - Curso online de 4 horas)")
    if any(k in t for k in ["rcg", "rsg", "responsible conduct of gambling", "responsible service of gaming", "gaming licence"]):
        reqs.append("🎰 RCG/RSG (Certificado para salas de juego/pubs - Curso de 1 día)")
    if any(k in t for k in ["barista", "latte art", "espresso", "coffee making"]):
        reqs.append("☕ Experiencia o curso corto de Barista (manejo de máquina de espresso)")
    if any(k in t for k in ["food safety", "food handling", "food handler", "hygiene"]):
        reqs.append("🍽️ Certificado básico de manipulación de alimentos (Food Handling)")
    if "working at heights" in t or "wah" in t:
        reqs.append("🧗 Working at Heights (Trabajo en altura - Curso de 1 día)")
    if "confined space" in t:
        reqs.append("🕳️ Confined Space (Espacios confinados - Curso de 1 día)")
    if any(k in t for k in ["ewp", "elevated work platform", "yellow card", "scissor lift", "boom lift"]):
        reqs.append("🏗️ Ticket EWP / Yellow Card (Plataforma elevadora - Curso de 1 día)")
    if any(k in t for k in ["driver", "licence", "license", "c class", "manual", "own transport", "reliable transport"]):
        reqs.append("🚗 Licencia de conducir vigente / Transporte propio")
    if any(k in t for k in ["police check", "national police clearance"]):
        reqs.append("📄 Police Check (Certificado de antecedentes online)")
    if any(k in t for k in ["drug", "alcohol screen", "pre-employment medical", "d&a"]):
        reqs.append("🧪 Test rápido de drogas y alcohol")
    if any(k in t for k in ["ppe", "steel cap", "hi-vis", "high vis", "hard hat"]):
        reqs.append("🥾 EPP básico (Bototos punta de acero y ropa reflectante Hi-Vis)")
    if any(k in t for k in ["heavy lifting", "physically fit", "20kg", "25kg", "manual handling"]):
        reqs.append("💪 Buena condición física (levantar entre 15 y 25 kg)")

    if not reqs:
        return "✅ Sin cursos ni licencias especiales mencionadas (Entrada directa con buena actitud)"
    return " | ".join(reqs)


def fallback_realistic_summary(title: str, details: str) -> str:
    """Resumen realista de qué se hace físicamente en el puesto si Groq no responde."""
    t = f"{title} {details}".lower()
    tareas = []
    if any(k in t for k in ["forklift", "lf ", "reach truck", "counterbalance"]):
        tareas.append("Mover pallets con grúa horquilla (Forklift), cargar/descargar camiones en patio o bodega y ubicar mercadería en racks.")
    if "traffic control" in t or "stop/slow" in t:
        tareas.append("Estar de pie en terreno con el cartel Stop/Slow regulando el paso de vehículos, colocando conos y señalética alrededor de obras viales.")
    if any(k in t for k in ["bartender", "bar staff", "bar attendant", "pub", "waitstaff", "food and beverage"]):
        tareas.append("Tirar cerveza de barril, preparar tragos básicos, atender clientes en barra/mesas, cobrar en caja y mantener limpia la zona del bar.")
    if "barista" in t or "cafe" in t:
        tareas.append("Preparar cafés en máquina comercial a ritmo rápido, espumar leche, atender pedidos de clientes en mostrador y limpiar la estación.")
    if any(k in t for k in ["kitchen hand", "dishwasher", "catering", "food prep"]):
        tareas.append("Lavar ollas, platos y bandejas en máquina industrial, picar o pelar ingredientes básicos, sacar basura y mantener la cocina impecable.")
    if any(k in t for k in ["housekeeping", "room attendant", "cleaner", "cleaning"]):
        tareas.append("Hacer camas, cambiar sábanas y toallas, aspirar pisos y desinfectar baños en habitaciones de hotel, campamentos o edificios a ritmo constante.")
    if any(k in t for k in ["warehouse", "pick", "packer", "storeperson", "container"]):
        tareas.append("Caminar por pasillos de bodega armando pedidos con escáner RF, envolver pallets con film plástico o vaciar cajas de contenedores a mano.")
    if any(k in t for k in ["labourer", "civil", "construction", "trade assistant", "ta ", "solar"]):
        tareas.append("Trabajo físico en obra o terreno: mover materiales, usar herramientas manuales/eléctricas, asistir a los técnicos y mantener el sitio limpio y seguro.")
    if any(k in t for k in ["farm", "agri", "harvest", "picker", "packer", "nursery"]):
        tareas.append("Trabajo al aire libre en granja o vivero: cosechar fruta/verdura, clasificar y empacar en cajas, podar plantas o regar cultivos.")
    if any(k in t for k in ["fifo", "utility", "mine site"]):
        tareas.append("Turnos largos en campamento minero: limpiar habitaciones del campamento (Housekeeping), ayudar en el comedor masivo (Mess/Kitchen) o lavandería.")

    if not tareas:
        tareas.append("Trabajo operativo práctico: realizar tareas manuales en equipo, mover insumos, mantener el orden del lugar y seguir instrucciones del supervisor.")
    return " ".join(tareas)


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
    """
    Usa Groq LLM para destripar la oferta sin adornos corporativos:
    explica qué hará realmente en el día a día y qué cursos cortos/requisitos piden.
    """
    raw_text = f"{job['title']} | {job['work_type']} | {job['summary']}"
    postcode = detect_postcode(job["location"], job["summary"])
    detected_reqs = detect_whv_prerequisites(raw_text)
    es_explanation = fallback_realistic_summary(job["title"], job["summary"])

    if GROQ_API_KEY:
        prompt = (
            "Eres un asesor experto en Australia para jóvenes con visa Work and Holiday (WHV 462). "
            "Analiza esta oferta en inglés sin rodeos ni lenguaje corporativo y responde ÚNICAMENTE "
            "con un objeto JSON válido con estas 3 claves exactas en español:\n"
            "{\n"
            '  "explicacion": "Explica en 2 a 3 frases directas y realistas qué va a hacer físicamente en su turno diario (ej: manejar grúa horquilla moviendo pallets, atender barra sirviendo cerveza, sostener el cartel Stop/Slow en la calle, descargar cajas o limpiar habitaciones).",\n'
            '  "codigo_postal": "Código postal de 4 dígitos si aparece o el código postal aproximado de ese suburbio/ciudad en Australia",\n'
            '  "requisitos": "Lista clara y exacta en español de los prerrequisitos, licencias o cursos cortos que piden (ej: Forklift LF, RSA, Traffic Control, White Card, Barista, auto propio, levantar 20kg, buen nivel de inglés o si no pide experiencia). Aclara cuáles son cursos rápidos de sacar."\n'
            "}\n\n"
            f"Título del puesto: {job['title']}\n"
            f"Empresa: {job['company']}\n"
            f"Ubicación: {job['location']}\n"
            f"Descripción del anuncio: {job['summary'][:700]}\n"
            f"Tickets detectados automáticamente: {detected_reqs}"
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
                timeout=9
            )
            if resp.status_code == 200:
                content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                parsed = parse_ai_json_safely(content)
                if parsed:
                    es_explanation = str(parsed.get("explicacion") or es_explanation)
                    postcode = str(parsed.get("codigo_postal") or postcode)
                    ai_reqs = str(parsed.get("requisitos") or "").strip()
                    if ai_reqs:
                        detected_reqs = ai_reqs
                time.sleep(1.2)
        except Exception:
            pass

    return {
        "explicacion": es_explanation,
        "codigo_postal": postcode,
        "requisitos": detected_reqs
    }


def send_telegram_alert(job: Dict[str, Any], rank_idx: int, total_to_send: int) -> bool:
    info = analyze_with_ai_or_rules(job)
    vip_badge = (
        f"⭐ <b>[OPCIÓN #{rank_idx}/{total_to_send} - EMPLEADOR TOP WHV]</b>\n"
        if is_priority_org(job["company"])
        else f"🎒 <b>[OPCIÓN #{rank_idx}/{total_to_send} - IDEAL WHV 462 (&lt; 48H)]</b>\n"
    )

    msg = (
        f"{vip_badge}"
        f"📌 <b>{html.escape(job['title'])}</b>\n"
        f"🏢 <b>Empresa:</b> {html.escape(job['company'])}\n"
        f"📍 <b>Ubicación:</b> {html.escape(job['location'])}\n"
        f"📮 <b>Código Postal:</b> {html.escape(info['codigo_postal'])}\n"
        f"💰 <b>Salario:</b> {html.escape(job['salary'])} ({html.escape(job['work_type'])})\n\n"
        f"🛠️ <b>¿De qué trata el trabajo en realidad?:</b>\n{html.escape(info['explicacion'])}\n\n"
        f"🪪 <b>Prerrequisitos y Cursos Cortos (Tickets):</b>\n{html.escape(info['requisitos'])}\n\n"
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
# ORQUESTADOR PRINCIPAL (BARRIDO 48H -> TOP 30 WHV 462 -> AUTO-PAUSA)
# =====================================================================

def main() -> None:
    cfg = load_config()
    target_city = ask_or_read_city_from_telegram(cfg)

    if not target_city:
        logger.info("Solicitud de ubicación enviada a Telegram. Sistema en pausa esperando respuesta.")
        return

    seen_list = load_seen()
    seen_set: Set[str] = set(seen_list)
    candidates: Dict[str, Dict[str, Any]] = {}

    send_simple_message(
        f"🚀 <b>Iniciando barrido WHV 462 en: {html.escape(target_city)}</b>\n"
        f"Buscando empleos clásicos (Forklift, Bartender/RSA, Traffic Control, Barista, "
        f"Labourer, Bodega, Farm, Hospitality) publicados hace <b>menos de 2 días</b>...\n"
        f"<i>Descartando carreras universitarias y seleccionando el Top 30.</i>"
    )

    for kw in JOB_KEYWORDS:
        logger.info(f"Buscando '{kw}' (< 48h) en {target_city}...")

        batch = []
        batch.extend(fetch_seek_last_2_days(kw, target_city))
        batch.extend(fetch_workforce_australia_gov(kw, target_city))
        batch.extend(fetch_jora_australia(kw, target_city))
        batch.extend(fetch_careerone_australia(kw, target_city))

        for job in batch:
            jid = job["id"]
            if jid not in seen_set and jid not in candidates:
                if is_valid_whv_job(job["title"], job["company"], job["summary"]):
                    job["score"] = score_whv_job_quality(job)
                    candidates[jid] = job
                else:
                    seen_set.add(jid)
                    seen_list.append(jid)

        time.sleep(random.uniform(1.4, 2.5))

    ranked_jobs = sorted(candidates.values(), key=lambda x: x.get("score", 0), reverse=True)
    top_30_jobs = ranked_jobs[:TOP_JOBS_LIMIT]

    sent_count = 0
    total_to_send = len(top_30_jobs)

    for idx, job in enumerate(top_30_jobs, start=1):
        if send_telegram_alert(job, idx, total_to_send):
            sent_count += 1
        seen_set.add(job["id"])
        seen_list.append(job["id"])

    save_seen(seen_list)
    cfg["active_city"] = None
    cfg["waiting_for_city"] = False
    save_config(cfg)

    send_simple_message(
        f"✅ <b>Barrido WHV 462 finalizado en {html.escape(target_city)}</b>\n"
        f"Se entregaron las <b>{sent_count} mejores opciones</b> publicadas en las últimas 48 horas.\n\n"
        f"⏸️ <b>El radar ha quedado en pausa automáticamente.</b>\n"
        f"Cuando quieras revisar otra ciudad o un nuevo lote, escribe la ubicación aquí y ejecuta el workflow en GitHub Actions."
    )
    logger.info(f"Entregadas {sent_count} ofertas WHV 462 de {target_city}. Bot en pausa.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error(f"Error controlado: {exc}")
        sys.exit(0)
