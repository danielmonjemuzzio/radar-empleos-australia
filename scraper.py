import os
import json
import time
import requests
import pandas as pd
from jobspy import scrape_jobs

# Credenciales desde GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SEEN_FILE = "seen_jobs.json"

# 1. Configura tus búsquedas (Puedes añadir todas las que quieras)
SEARCH_QUERIES = [
    {"keyword": "FIFO Utility", "location": "Perth WA"},
    {"keyword": "Trade Assistant", "location": "Western Australia"},
    {"keyword": "Construction Labourer White Card", "location": "Western Australia"},
    {"keyword": "Solar Farm", "location": "Australia"},
    {"keyword": "Shutdown", "location": "Western Australia"},
    {"keyword": "Forklift Warehouse", "location": "Perth WA"},
    {"keyword": "Hospitality Housekeeping", "location": "Western Australia"},
    {"keyword": "Civil Labourer", "location": "Queensland"}
]

# 2. Organizaciones serias y grandes agencias (Destacado VIP en Telegram)
SERIOUS_ORGS = [
    "programmed", "workpac", "hays", "chandler macleod", "adecco", "randstad",
    "monadelphous", "ventia", "downer", "bhp", "rio tinto", "fortescue", "fmg",
    "mineral resources", "minres", "macmahon", "perenti", "sodexo", "compass group",
    "iss facility", "civeo", "acciona", "lendlease", "cpb contractors", "bmd",
    "water corporation", "synergy", "western power", "corestaff", "techforce", "linkforce"
]

# 3. Palabras bloqueadas (Filtro anti-spam y ofertas falsas)
BLACKLIST_WORDS = [
    "unpaid", "commission only", "survey", "tutor", "au pair", 
    "mystery shopper", "mlm", "crypto", "volunteer"
]

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen(seen_set):
    # Mantiene las últimas 5000 ofertas en memoria para que el archivo sea ultraligero
    seen_list = list(seen_set)[-5000:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen_list, f)

def is_valid_job(title, company):
    text = f"{title} {company}".lower()
    return not any(bad in text for bad in BLACKLIST_WORDS)

def is_priority_org(company):
    comp_lower = str(company).lower()
    return any(org in comp_lower for org in SERIOUS_ORGS)

def fetch_seek_api(keyword, location):
    """Consulta directamente la API JSON v5 de SEEK Australia."""
    url = "https://www.seek.com.au/api/jobsearch/v5/search"
    params = {
        "siteKey": "AU-Main",
        "keywords": keyword,
        "where": location,
        "sortmode": "ListedDate",
        "pageSize": 50,
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
                loc = item.get("locations", [{}])[0].get("label", location)
                salary = item.get("salaryLabel", "No especificado (Ver anuncio)")
                teaser = item.get("teaser", "")
                
                jobs.append({
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "location": loc,
                    "salary": salary,
                    "portal": "SEEK AU",
                    "url": f"https://www.seek.com.au/job/{item.get('id')}",
                    "summary": teaser
                })
    except Exception as e:
        print(f"[Error SEEK] {keyword}: {e}")
    return jobs

def fetch_jobspy_portals(keyword, location):
    """Extrae de Indeed Australia y LinkedIn usando JobSpy."""
    jobs = []
    try:
        df = scrape_jobs(
            site_name=["indeed", "linkedin"],
            search_term=keyword,
            location=location,
            results_wanted=30,
            hours_old=24, # Solo ofertas de las últimas 24 horas
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
                
                min_s = row.get("min_amount")
                max_s = row.get("max_amount")
                salary = f"${min_s} - ${max_s}" if pd.notna(min_s) else "Ver oferta"

                jobs.append({
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "location": loc,
                    "salary": salary,
                    "portal": site,
                    "url": url,
                    "summary": ""
                })
    except Exception as e:
        print(f"[Error JobSpy] {keyword}: {e}")
    return jobs

def send_telegram_alert(job):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    vip_badge = "⭐ [ORGANIZACIÓN TOP / TIER 1]\n" if is_priority_org(job["company"]) else "🏢 [OFERTA VERIFICADA]\n"
    
    msg = (
        f"{vip_badge}"
        f"📌 *{job['title']}*\n"
        f"🏛 *Empresa:* {job['company']}\n"
        f"📍 *Ubicación:* {job['location']}\n"
        f"💰 *Salario:* {job['salary']}\n"
        f"🌐 *Portal:* {job['portal']}\n"
    )
    if job["summary"]:
        msg += f"📝 _{job['summary'][:140]}..._\n"
    msg += f"\n🔗 [POSTULAR AHORA DIRECTO]({job['url']})"

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(api_url, json=payload, timeout=10)
        # Pausa de 1.2s para respetar el límite de Telegram al enviar cientos de ofertas
        time.sleep(1.2)
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")

def main():
    seen_jobs = load_seen()
    new_jobs_count = 0

    for q in SEARCH_QUERIES:
        kw, loc = q["keyword"], q["location"]
        print(f"Rastreando: {kw} en {loc}...")
        
        found = fetch_seek_api(kw, loc) + fetch_jobspy_portals(kw, loc)
        
        for job in found:
            if job["id"] not in seen_jobs and is_valid_job(job["title"], job["company"]):
                send_telegram_alert(job)
                seen_jobs.add(job["id"])
                new_jobs_count += 1

    save_seen(seen_jobs)
    print(f"Proceso completado. Nuevas ofertas enviadas: {new_jobs_count}")

if __name__ == "__main__":
    main()
