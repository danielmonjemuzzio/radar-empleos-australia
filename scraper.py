import os
import re
import html
import json
import time
import requests
import pandas as pd
from jobspy import scrape_jobs

# Credenciales desde GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SEEN_FILE = "seen_jobs.json"

# 1. BÚSQUEDAS PARA RECIÉN LLEGADOS (Sin experiencia local ni título universitario)
SEARCH_QUERIES = [
    {"keyword": "General Labourer White Card", "location": "Western Australia"},
    {"keyword": "Trade Assistant", "location": "Western Australia"},
    {"keyword": "FIFO Utility", "location": "Perth WA"},
    {"keyword": "Solar Farm Labourer", "location": "Australia"},
    {"keyword": "Warehouse Pick Packer", "location": "Perth WA"},
    {"keyword": "Container Unloader General Hand", "location": "Australia"},
    {"keyword": "Kitchen Hand Housekeeping", "location": "Western Australia"},
    {"keyword": "Civil Construction Labourer", "location": "Queensland"},
    {"keyword": "Farm Hand", "location": "Australia"},
    {"keyword": "Factory Hand Process Worker", "location": "Perth WA"}
]

# 2. AGENCIAS Y EMPRESAS TIER 1 (Muy abiertas a contratar Visa 462 / Casuals)
SERIOUS_ORGS = [
    "programmed", "workpac", "hays", "chandler macleod", "adecco", "randstad",
    "monadelphous", "ventia", "downer", "bhp", "rio tinto", "fortescue", "fmg",
    "mineral resources", "minres", "macmahon", "perenti", "sodexo", "compass group",
    "iss facility", "civeo", "acciona", "lendlease", "cpb contractors", "bmd",
    "corestaff", "techforce", "linkforce", "agrifood", "costa group", "action workforce",
    " Hoban", "persolkelly", "labourpower", "skout", "awx", "recruitwest"
]

# 3. FILTRO ESTRICTO: Excluye universitarios (Medicina, Ingeniería, Arquitectura) y cargos Senior
BLACKLIST_WORDS = [
    # Carreras universitarias y salud
    "engineer", "engineering", "doctor", "medical", "physician", "surgeon",
    "registered nurse", "nursing", "clinical", "pharmacist", "dentist", "psychologist",
    "physiotherapist", "occupational therapist", "veterinarian", "vet ", "radiographer",
    "architect", "architecture", "Draftsperson", "lawyer", "solicitor", "legal counsel",
    "accountant", "accounting", "auditor", "actuary", "geologist", "geophysicist",
    "metallurgist", "surveyor", "quantity surveyor", "agronomist", "teacher", "lecturer",
    # Grados académicos y niveles ejecutivos
    "bachelor", "master's", "phd", "tertiary qualification", "university degree",
    "senior manager", "general manager", "director", "principal", "head of",
    "lead ", "superintendent", "project manager", "supervisor", "coordinator",
    # Restricciones migratorias incompatibles con WHV 462 y spam
    "australian citizen", "citizens only", "pr only", "permanent resident only",
    "nv1", "nv2", "baseline clearance", "unpaid", "commission only", "survey",
    "au pair", "mystery shopper", "mlm", "crypto", "volunteer"
]

# 4. MAPA DE CÓDIGOS POSTALES DE REFERENCIA EN AUSTRALIA
POSTCODE_MAP = {
    "perth": "6000 (Metro WA)", "fremantle": "6160 (WA)", "rockingham": "6168 (WA)",
    "mandurah": "6210 (Regional WA - 88 días)", "bunbury": "6230 (Regional WA - 88 días)",
    "busselton": "6280 (Regional WA - 88 días)", "margaret river": "6285 (Regional WA - 88 días)",
    "albany": "6330 (Regional WA - 88 días)", "esperance": "6450 (Regional WA - 88 días)",
    "kalgoorlie": "6430 (Regional WA - 88 días)", "geraldton": "6530 (Regional WA - 88 días)",
    "carnarvon": "6701 (Norte WA - 88 días)", "exmouth": "6707 (Norte WA - 88 días)",
    "karratha": "6714 (Norte/Pilbara WA - 88 días)", "port hedland": "6721 (Norte/Pilbara WA - 88 días)",
    "newman": "6753 (Norte/Pilbara WA - 88 días)", "tom price": "6751 (Norte/Pilbara WA - 88 días)",
    "broome": "6725 (Norte/Kimberley WA - 88 días)", "kununurra": "6743 (Norte WA - 88 días)",
    "pilbara": "6714-6753 (Norte WA - 88 días)", "kimberley": "6725-6743 (Norte WA - 88 días)",
    "darwin": "0800 (Todo NT cuenta para 88 días)", "alice springs": "0870 (NT - 88 días)",
    "cairns": "4870 (Norte QLD - 88 días)", "townsville": "4810 (Norte QLD - 88 días)",
    "mackay": "4740 (Regional QLD - 88 días)", "rockhampton": "4700 (Regional QLD - 88 días)",
    "gladstone": "4680 (Regional QLD - 88 días)", "toowoomba": "4350 (Regional QLD - 88 días)",
    "brisbane": "4000 (Metro QLD)", "gold coast": "4217 (QLD)", "sydney": "2000 (Metro NSW)",
    "melbourne": "3000 (Metro VIC)", "adelaide": "5000 (Todo SA cuenta para 88 días en construcción)"
}

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen(seen_set):
    seen_list = list(seen_set)[-5000:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen_list, f)

def is_valid_entry_job(title, company, description=""):
    """Filtra carreras universitarias, puestos senior y restricciones de ciudadanía."""
    full_text = f"{title} {company} {description}".lower()
    title_lower = title.lower()
    # Verificar palabras prohibidas en título y descripción
    for bad in BLACKLIST_WORDS:
        if bad in title_lower:
            return False
    # Bloquear si pide explícitamente título universitario o ciudadanía en la descripción
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
    """Busca un código postal australiano de 4 dígitos o lo deduce por la ciudad/región."""
    combined = f"{location_text} {description_text}"
    # Buscar código postal explícito de 4 dígitos (Rango australiano 0800-7999)
    matches = re.findall(r'\b(08\d{2}|[2-7]\d{3})\b', combined)
    for m in matches:
        # Evitar confundir años (2024, 2025, 2026) con códigos postales a menos que sea Sydney (2000)
        if m not in ["2020", "2021", "2022", "2023", "2024", "2025", "2026", "2027"]:
            return f"{m} (Extraído del anuncio)"
    
    loc_lower = location_text.lower()
    for city, code_info in POSTCODE_MAP.items():
        if city in loc_lower:
            return code_info
    return "No especificado en el texto (Consultar ciudad en el anuncio)"

def detect_prerequisites(text):
    """Detecta los tickets, licencias o requisitos básicos que pide el trabajo."""
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

def evaluate_visa_462(title, company, work_type, text):
    """Evalúa qué tan abierta es la vacante para portadores de Working Holiday 462."""
    combined = f"{title} {company} {work_type} {text}".lower()
    if any(k in combined for k in ["whv", "working holiday", "462", "417", "backpacker", "88 days", "2nd year visa"]):
        return "🟢 MUY ALTA (Menciona explícitamente Working Holiday / 88 días)"
    if is_priority_org(company) or "casual" in combined or "temp" in combined or "labour hire" in combined or "immediate start" in combined:
        return "🟢 ALTA (Modalidad Casual / Agencia Labour Hire / Inicio inmediato, muy amigable con Visa 462)"
    if "contract" in combined or "fixed term" in combined or "fifo" in combined:
        return "🟢 ALTA (Contrato por obra/turno, compatible con el límite de 6 meses de la 462)"
    return "🟡 MEDIA-ALTA (Puesto operativo de entrada; postular indicando disponibilidad inmediata)"

def fallback_spanish_summary(title, details):
    """Traduce y explica de qué trata el puesto en español si no se usa IA externa."""
    t = f"{title} {details}".lower()
    explicaciones = []
    if "solar" in t:
        explicaciones.append("Trabajo operativo en planta solar (montaje de paneles, movimiento de materiales y asistencia en terreno).")
    if "fifo" in t or "utility" in t or "housekeeping" in t or "camp" in t:
        explicaciones.append("Puesto en campamento minero/remoto (limpieza de habitaciones, ayuda en cocina/comedor o mantenimiento general del campamento).")
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
    """Usa Groq AI para generar el análisis en español o usa el motor de reglas si no hay API key."""
    raw_text = f"{job['title']} | {job['work_type']} | {job['summary']}"
    postcode = detect_postcode(job["location"], job["summary"])
    prereqs = detect_prerequisites(raw_text)
    visa_status = evaluate_visa_462(job["title"], job["company"], job["work_type"], raw_text)
    es_explanation = fallback_spanish_summary(job["title"], job["summary"])

    if GROQ_API_KEY:
        prompt = (
            "Eres un asesor laboral experto en Australia para recién llegados con Working Holiday Visa 462. "
            "Analiza esta oferta en inglés y responde ÚNICAMENTE con un objeto JSON válido con estas 4 claves exactas en español:\n"
            "{\n"
            '  "explicacion": "Explica en 2 frases claras en español qué tareas hará exactamente en este trabajo",\n'
            '  "codigo_postal": "Código postal de 4 dígitos si aparece o el código postal aproximado de ese suburbio/ciudad en Australia y si cuenta para los 88 días",\n'
            '  "requisitos": "Lista corta en español de tickets, licencias o requisitos físicos que piden (o indica si no pide experiencia)",\n'
            '  "visa_462": "Indica (🟢 ALTA o 🟡 MEDIA) y explica brevemente por qué es buena opción para un recién llegado con Visa 462"\n'
            "}\n\n"
            f"Título: {job['title']}\nEmpresa: {job['company']}\nUbicación: {job['location']}\n"
            f"Tipo: {job['work_type']}\nDetalle: {job['summary'][:800]}"
        )
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"}
                },
                timeout=12
            )
            if r.status_code == 200:
                data = json.loads(r.json()["choices"][0]["message"]["content"])
                es_explanation = data.get("explicacion", es_explanation)
                postcode = data.get("codigo_postal", postcode)
                prereqs = data.get("requisitos", prereqs)
                visa_status = data.get("visa_462", visa_status)
                # Pequeña pausa para respetar límite gratuito de Groq
                time.sleep(2.1)
        except Exception as e:
            print(f"[Aviso IA - Usando motor local]: {e}")

    return {
        "explicacion": es_explanation,
        "codigo_postal": postcode,
        "requisitos": prereqs,
        "visa_462": visa_status
    }

def fetch_seek_api(keyword, location):
    """Consulta la API JSON v5 de SEEK Australia."""
    url = "https://www.seek.com.au/api/jobsearch/v5/search"
    params = {
        "siteKey": "AU-Main",
        "keywords": keyword,
        "where": location,
        "sortmode": "ListedDate",
        "pageSize": 35,
        "page": 1
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    jobs = []
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json().get("data", [])
            for item in data:
                job_id = f"seek_{item.get('id')}"
                title = item.get("title", "Sin título")
                company = item.get("advertiser", {}).get("description", "Empresa Verificada en SEEK")
                loc_list = item.get("locations", [{}])
                loc = loc_list[0].get("label", location) if loc_list else location
                salary = item.get("salaryLabel", "Según convenio (Award Rate)")
                work_type = item.get("workType", "Casual / Full Time")
                teaser = item.get("teaser", "")
                bullets = " | ".join(item.get("bulletPoints", []))
                full_summary = f"{teaser} {bullets}".strip()

                jobs.append({
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "location": loc,
                    "salary": salary,
                    "work_type": work_type,
                    "portal": "SEEK AU",
                    "url": f"https://www.seek.com.au/job/{item.get('id')}",
                    "summary": full_summary
                })
    except Exception as e:
        print(f"[Error SEEK] {keyword}: {e}")
    return jobs

def fetch_jobspy_portals(keyword, location):
    """Extrae de Indeed Australia y LinkedIn."""
    jobs = []
    try:
        df = scrape_jobs(
            site_name=["indeed", "linkedin"],
            search_term=keyword,
            location=location,
            results_wanted=20,
            hours_old=24,
            country_indeed="Australia"
        )
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                raw_id = str(row.get("id", row.get("job_url", "")))
                job_id = f"spy_{raw_id[-25:]}"
                title = str(row.get("title", "Sin título"))
                company = str(row.get("company", "Empresa Directa"))
                loc = str(row.get("location", location))
                site = str(row.get("site", "Portal")).upper()
                url = str(row.get("job_url", ""))
                desc = str(row.get("description", ""))[:600]
                job_type = str(row.get("job_type", "Entry-Level"))

                min_s = row.get("min_amount")
                max_s = row.get("max_amount")
                salary = f"${min_s} - ${max_s} AUD" if pd.notna(min_s) else "Según convenio (Award)"

                jobs.append({
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "location": loc,
                    "salary": salary,
                    "work_type": job_type,
                    "portal": site,
                    "url": url,
                    "summary": desc if desc != "nan" else ""
                })
    except Exception as e:
        print(f"[Error JobSpy] {keyword}: {e}")
    return jobs

def send_telegram_alert(job):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    info = analyze_with_ai_or_rules(job)
    vip_badge = "⭐ <b>[AGENCIA / EMPRESA TOP TIER 1]</b>\n" if is_priority_org(job["company"]) else "🇦🇺 <b>[OFERTA RECIÉN LLEGADOS]</b>\n"

    msg = (
        f"{vip_badge}"
        f"📌 <b>{html.escape(job['title'])}</b>\n"
        f"🏢 <b>Empresa:</b> {html.escape(job['company'])}\n"
        f"📍 <b>Ubicación:</b> {html.escape(job['location'])}\n"
        f"📮 <b>Código Postal:</b> {html.escape(str(info['codigo_postal']))}\n"
        f"💰 <b>Salario:</b> {html.escape(str(job['salary']))} ({html.escape(str(job['work_type']))})\n\n"
        f"🇪🇸 <b>¿De qué trata el trabajo?:</b>\n{html.escape(str(info['explicacion']))}\n\n"
        f"🪪 <b>Prerrequisitos / Tickets:</b>\n{html.escape(str(info['requisitos']))}\n\n"
        f"🛂 <b>Apertura Visa 462:</b>\n{html.escape(str(info['visa_462']))}\n\n"
        f"🌐 <b>Portal:</b> {html.escape(job['portal'])}\n"
        f"🔗 <a href=\"{job['url']}\">POSTULAR AHORA DIRECTO</a>"
    )

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(api_url, json=payload, timeout=10)
        time.sleep(1.2)
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")

def main():
    seen_jobs = load_seen()
    new_jobs_count = 0

    for q in SEARCH_QUERIES:
        kw, loc = q["keyword"], q["location"]
        print(f"Rastreando vacantes de entrada: {kw} en {loc}...")

        found = fetch_seek_api(kw, loc) + fetch_jobspy_portals(kw, loc)

        for job in found:
            if job["id"] not in seen_jobs:
                if is_valid_entry_job(job["title"], job["company"], job["summary"]):
                    send_telegram_alert(job)
                    seen_jobs.add(job["id"])
                    new_jobs_count += 1
                else:
                    # Marcar como visto para no volver a evaluar carreras universitarias descartadas
                    seen_jobs.add(job["id"])

    save_seen(seen_jobs)
    print(f"Proceso completado. Nuevas ofertas enviadas en español: {new_jobs_count}")

if __name__ == "__main__":
    main()
