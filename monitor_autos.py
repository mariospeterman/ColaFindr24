#!/usr/bin/env python3

"""
monitor_autos.py

Automated car search & WhatsApp notification tool.

- Runs with Selenium (headless Chrome)
- Aggregates results from multiple classified sites
- Filters by Diesel, year >= MIN_YEAR, km<=MAX_KM, price<=MAX_PRICE
- Looks for keywords indicating accident/repairable
- Caches seen links in SQLite to avoid duplicate notifications
- Sends WhatsApp via CallMeBot for new matches

Configuration:
- Uses .env for API keys and tunables (see .env.example)
- Uses search_urls.txt for per-site search URL templates (one per line)
  You can paste exact filtered URLs from your browser and add placeholders
  {year}, {km}, {price}, {kw} where the script should substitute values.
"""

import os
import time
import re
import csv
import sqlite3
import requests
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException


# ----------------------------
# Load configuration (.env and files)
# ----------------------------

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR.joinpath('.env'))


def get_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value if value is not None and value != "" else default


def parse_int(name: str, default_value: int) -> int:
    raw = get_env(name, str(default_value))
    try:
        return int(raw)
    except Exception:
        return default_value


def parse_float(name: str, default_value: float) -> float:
    raw = get_env(name, str(default_value))
    try:
        return float(raw)
    except Exception:
        return default_value


def parse_list(name: str, default_list: list[str]) -> list[str]:
    raw = get_env(name, "")
    if not raw:
        return default_list
    # split on commas, strip whitespace, drop empties
    return [item.strip() for item in raw.split(',') if item.strip()]


# User/API config
PHONE = get_env("PHONE", "")  # e.g. +491570000000
CALLMEBOT_APIKEY = get_env("CALLMEBOT_APIKEY", "")
CALLMEBOT_STRIP_PLUS = get_env("CALLMEBOT_STRIP_PLUS", "true").lower() in ("1", "true", "yes")

# Files
CSV_FILE = get_env("CSV_FILE", "auto_export_finder.csv")
DB_FILE = get_env("DB_FILE", "seen_links.db")
SEARCH_URLS_FILE = get_env("SEARCH_URLS_FILE", "search_urls.txt")

# Limits / pacing
MAX_SEND_PER_RUN = parse_int("MAX_SEND_PER_RUN", 8)
SLEEP_BETWEEN_SITES = parse_float("SLEEP_BETWEEN_SITES", 6.0)

# Search filters (range support)
MIN_YEAR = parse_int("MIN_YEAR", 2019)
MAX_YEAR = parse_int("MAX_YEAR", 2025)
MIN_KM = parse_int("MIN_KM", 0)
MAX_KM = parse_int("MAX_KM", 150000)
MIN_PRICE = parse_int("MIN_PRICE", 5000)
MAX_PRICE = parse_int("MAX_PRICE", 25000)

# Query lists
DEFAULT_CAR_BRANDS_MODELS = [
    "BMW 320d", "BMW 520d",
    "Mercedes C 220d", "Mercedes E 220d",
    "Audi A4", "Audi A6",
    "VW Passat", "VW Arteon", "VW Tiguan", "VW Touran",
    "Skoda Superb",
    "Ford Mondeo",
    "Seat Leon",
    "Peugeot 508",
]

DEFAULT_KEYWORDS = [
    "unfall", "blech", "blechschaden", "frontschaden", "heckschaden", "seitenschaden",
    "reparatur", "reparaturbedürftig", "fahrbereit", "kleiner schaden", "leichter unfall",
    "karosserie", "instandsetzungsfähig", "wirtschaftlicher totalschaden", "unfallwagen",
    # optional: FR/NO/SE
    "accident", "avarie", "skadet", "krockad",
]

CAR_BRANDS_MODELS = parse_list("CAR_BRANDS_MODELS", DEFAULT_CAR_BRANDS_MODELS)
KEYWORDS = parse_list("KEYWORDS", DEFAULT_KEYWORDS)


def read_search_urls(file_path: Path) -> list[str]:
    path = file_path if file_path.is_absolute() else ROOT_DIR.joinpath(file_path)
    if not path.exists():
        return []
    urls: list[str] = []
    with open(path, 'r', encoding='utf-8') as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith('#'):
                continue
            urls.append(stripped)
    return urls


# ----------------------------
# DB / Caching
# ----------------------------

def init_db(db_path: str = DB_FILE):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS seen (
            link TEXT PRIMARY KEY,
            title TEXT,
            site TEXT,
            price TEXT,
            first_seen TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def is_seen(conn, link: str) -> bool:
    c = conn.cursor()
    c.execute("SELECT 1 FROM seen WHERE link = ?", (link,))
    return c.fetchone() is not None


def mark_seen(conn, link: str, title: str, site: str, price: str):
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO seen (link, title, site, price, first_seen) VALUES (?, ?, ?, ?, ?)",
        (link, title, site, price, datetime.now(timezone.utc)),
    )
    conn.commit()


# ----------------------------
# WhatsApp via CallMeBot
# ----------------------------

def send_whatsapp(message: str) -> bool:
    if not CALLMEBOT_APIKEY or not PHONE:
        print("[WARN] CallMeBot API key or PHONE not set. Skipping WhatsApp send.")
        return False
    try:
        phone_param = PHONE.strip().replace(' ', '')
        if CALLMEBOT_STRIP_PLUS and phone_param.startswith('+'):
            phone_param = phone_param[1:]
        payload = {
            "phone": phone_param,
            "text": message,
            "apikey": CALLMEBOT_APIKEY,
        }
        print(f"[DEBUG] CallMeBot request phone={phone_param} apikey={CALLMEBOT_APIKEY[:6]}... len(text)={len(message)}")
        url = "https://api.callmebot.com/whatsapp.php"
        r = requests.get(url, params=payload, timeout=20)
        body_snip = (r.text or "")[:300]
        if r.status_code == 200:
            if "APIKey is invalid" in body_snip or "error" in body_snip.lower():
                print("[ERR] WhatsApp 200 but error body:", body_snip)
                return False
            print("[OK] WhatsApp sent. Response snippet:", body_snip)
            return True
        print("[ERR] WhatsApp API returned", r.status_code, body_snip)
        return False
    except Exception as e:
        print("[ERR] WhatsApp send error:", e)
        return False


# ----------------------------
# Selenium driver
# ----------------------------

def init_driver(headless: bool = False):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--lang=en-GB")
    options.add_argument("--window-size=1920,1080")
    # user agent can help with some sites
    options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_page_load_timeout(60)
    return driver


# ----------------------------
# Utilities
# ----------------------------

def text_contains_keywords(text: str, keywords: list[str]) -> bool:
    if not text:
        return False
    t = text.lower()
    for k in keywords:
        if k.lower() in t:
            return True
    return False


def detect_site_label(url: str) -> str:
    hostname = url.split("/")[2] if "//" in url else url
    if "mobile.de" in hostname:
        return "mobile.de"
    if "autoscout24" in hostname:
        return "autoscout24"
    if "willhaben" in hostname:
        return "willhaben"
    if "leboncoin" in hostname:
        return "leboncoin"
    if "finn.no" in hostname:
        return "finn.no"
    if "blocket" in hostname:
        return "blocket"
    return hostname


# ----------------------------
# Parsers
# ----------------------------

def parse_mobile_listing(elem):
    try:
        title = elem.find_element(By.CSS_SELECTOR, "h2").text
    except Exception:
        title = ""
    try:
        link = elem.find_element(By.CSS_SELECTOR, "a").get_attribute("href")
    except Exception:
        link = ""
    try:
        price = elem.find_element(By.CSS_SELECTOR, ".price-block").text
    except Exception:
        price = ""
    desc = elem.text or ""
    return title, link, price, desc


def parse_autoscout_listing(elem):
    try:
        title = elem.find_element(By.CSS_SELECTOR, "h2").text
    except Exception:
        title = ""
    try:
        link = elem.find_element(By.TAG_NAME, "a").get_attribute("href")
    except Exception:
        link = ""
    try:
        price = elem.find_element(By.CSS_SELECTOR, "p[data-testid='price-label']").text
    except Exception:
        price = ""
    desc = elem.text or ""
    return title, link, price, desc


def parse_generic_listing(elem):
    try:
        a = elem.find_element(By.TAG_NAME, "a")
        link = a.get_attribute("href")
        title = a.text or (elem.text[:100] if elem.text else "")
    except Exception:
        link = ""
        title = elem.text[:100] if elem and elem.text else ""
    price = ""
    desc = elem.text or ""
    return title, link, price, desc


# ----------------------------
# Core scraping
# ----------------------------

def scrape_site(driver, url: str):
    results: list[tuple[str, str, str, str, str]] = []
    label = detect_site_label(url)
    print(f"[INFO] Loading {label}: {url}")
    try:
        driver.get(url)
    except WebDriverException as e:
        print("[ERR] page load failed:", e)
        return results

    time.sleep(6)  # allow JS to render

    # Site-specific flows
    try:
        if label == "mobile.de":
            elems = driver.find_elements(By.CSS_SELECTOR, "div.cBox-body--resultitem")
            for e in elems:
                title, link, price, desc = parse_mobile_listing(e)
                results.append((label, title, link, price, desc))
            return results
    except Exception:
        pass

    try:
        if label == "autoscout24":
            elems = driver.find_elements(By.CSS_SELECTOR, "article")
            for e in elems:
                title, link, price, desc = parse_autoscout_listing(e)
                results.append((label, title, link, price, desc))
            return results
    except Exception:
        pass

    try:
        if label == "willhaben":
            elems = driver.find_elements(By.CSS_SELECTOR, "div.list-item")
            if not elems:
                elems = driver.find_elements(By.CSS_SELECTOR, "div.ad")
            for e in elems:
                title, link, price, desc = parse_generic_listing(e)
                results.append((label, title, link, price, desc))
            return results
    except Exception:
        pass

    try:
        if label == "leboncoin":
            elems = driver.find_elements(By.CSS_SELECTOR, "li[data-qa-id='aditem_container']")
            if not elems:
                elems = driver.find_elements(By.CSS_SELECTOR, "section")
            for e in elems[:50]:
                title, link, price, desc = parse_generic_listing(e)
                results.append((label, title, link, price, desc))
            return results
    except Exception:
        pass

    try:
        if label == "finn.no":
            elems = driver.find_elements(By.CSS_SELECTOR, "article")
            for e in elems:
                title, link, price, desc = parse_generic_listing(e)
                results.append((label, title, link, price, desc))
            return results
    except Exception:
        pass

    try:
        if label == "blocket":
            elems = driver.find_elements(By.CSS_SELECTOR, "article")
            for e in elems:
                title, link, price, desc = parse_generic_listing(e)
                results.append((label, title, link, price, desc))
            return results
    except Exception:
        pass

    # Generic anchors fallback
    try:
        anchors = driver.find_elements(By.CSS_SELECTOR, "a")
        for a in anchors[:200]:
            href = a.get_attribute("href") or ""
            text = a.text or ""
            if href and ("/product" in href or "/ad" in href or "/car" in href or "detail" in href):
                results.append((label, text.strip(), href, "", text))
    except Exception:
        pass

    return results


# ----------------------------
# Main
# ----------------------------

def run_once():
    conn = init_db(DB_FILE)
    # Headless can be disabled via .env HEADLESS=false
    headless_env = get_env("HEADLESS", "true").lower() not in ("false", "0", "no")
    driver = init_driver(headless=headless_env)
    all_new: list[dict] = []

    templates = read_search_urls(Path(SEARCH_URLS_FILE))
    if not templates:
        print(f"[WARN] No search URLs found in {SEARCH_URLS_FILE}. Add lines with templates.")

    try:
        for template in templates:
            kw = "+".join(KEYWORDS[:3]) if KEYWORDS else ""
            # Support both legacy and extended placeholders
            format_kwargs = {
                "year": MIN_YEAR,
                "min_year": MIN_YEAR,
                "max_year": MAX_YEAR,
                "km": MAX_KM,
                "min_km": MIN_KM,
                "max_km": MAX_KM,
                "price": MAX_PRICE,
                "min_price": MIN_PRICE,
                "max_price": MAX_PRICE,
                "kw": kw,
            }
            try:
                url = template.format(**format_kwargs)
            except Exception:
                url = template

            try:
                found = scrape_site(driver, url)
            except Exception as e:
                print("[ERR] site scrape error:", e)
                found = []

            print(f"[DEBUG] {detect_site_label(url)} returned {len(found)} raw cards")

            for site, title, link, price, desc in found:
                if not link:
                    continue
                link_norm = link.split("?")[0]
                if is_seen(conn, link_norm):
                    continue

                textpool = " ".join([title or "", desc or ""]).lower()
                brand_hit = any(b.lower() in textpool for b in CAR_BRANDS_MODELS)
                kw_hit = text_contains_keywords(textpool, KEYWORDS)

                # Relaxed: pass if brand OR any keyword matches
                if brand_hit or kw_hit:
                    mark_seen(conn, link_norm, title, site, price)
                    all_new.append({
                        "site": site,
                        "title": title,
                        "link": link_norm,
                        "price": price,
                        "desc_snippet": (desc[:250] if desc else ""),
                    })

            time.sleep(SLEEP_BETWEEN_SITES)
    finally:
        driver.quit()
        conn.close()

    if all_new:
        file_exists = Path(CSV_FILE).exists()
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["timestamp", "site", "title", "price", "link", "desc_snippet"],
            )
            if not file_exists:
                writer.writeheader()
            for e in all_new:
                writer.writerow({"timestamp": datetime.now(timezone.utc).isoformat(), **e})

        count = 0
        for e in all_new:
            if count >= MAX_SEND_PER_RUN:
                break
            msg = (
                f"Neues Fahrzeug: {e['title']} | Preis: {e['price']} | "
                f"Seite: {e['site']} | Link: {e['link']}"
            )
            if send_whatsapp(msg):
                count += 1
            else:
                print(f"[WARN] WhatsApp not sent for: {e['link']}")
        print(f"[INFO] {len(all_new)} neue Treffer (davon {count} per WhatsApp gesendet).")
    else:
        print("[INFO] Keine neuen Treffer dieses Laufs.")


if __name__ == "__main__":
    run_once()


