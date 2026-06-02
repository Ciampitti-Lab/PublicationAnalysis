#!/usr/bin/env python3
"""
OpenAlex — Agricultural & Biological Sciences paper extractor
Field: Agricultural and Biological Sciences (primary_topic.field.id = 11)
Window: 2018–2023

TIMEOUT BEHAVIOUR:
  If OpenAlex returns a 429 rate-limit at any point, the thread for that year
  stops immediately (no waiting) and saves whatever it has collected so far.
  All completed or partial year files are merged into the final CSV at the end.

RESUME LOGIC:
  Per-year output files are written on completion or early-stop:
    agri_bio_2018.csv … agri_bio_2023.csv
  On restart any year whose file already exists is skipped entirely.

NOTES:
  - COMPUTE_HINDEX is set to False by default for speed. Set True to enable.
  - source_2yr_mean_citedness is the closest OpenAlex proxy for JIF.
  - H-index approximation uses current citation counts, not historical ones.
"""

import os
import time
import logging
import threading
import requests
import pandas as pd
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Configuration ──────────────────────────────────────────────────────────────
OPENALEX_API_KEY = "Vuopm7PwTu5AE0KW6QrHpg"
EMAIL          = "ramir713@purdue.edu"
FIELD_ID       = "11"
YEARS          = [2018, 2019, 2020, 2021, 2022, 2023]
PER_PAGE       = 100
COMPUTE_HINDEX = False   # Keep False for a fast run

YEAR_WORKERS   = 3
MAX_RPS        = 8       # Hard ceiling shared across ALL threads

OUTPUT_DIR   = "/home/ramir713/repos/PublicationAnalysis/data/machine_learning_data"
FINAL_OUTPUT = os.path.join(OUTPUT_DIR, "agri_bio_papers_2018_2023.csv")

BASE_URL = "https://api.openalex.org"
HEADERS  = {"User-Agent": f"mailto:{EMAIL}"}

SELECT_FIELDS = ",".join([
    "id", "doi", "publication_year", "authorships",
    "countries_distinct_count", "institutions_distinct_count",
    "primary_location", "apc_list", "primary_topic", "referenced_works_count",'type'
    
])

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(threadName)s]  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Shared rate limiter ────────────────────────────────────────────────────────

class RateLimiter:
    def __init__(self, max_rps: float):
        self._min_interval = 1.0 / max_rps
        self._lock         = threading.Lock()
        self._last_call    = 0.0

    def wait(self):
        with self._lock:
            now   = time.monotonic()
            sleep = self._min_interval - (now - self._last_call)
            if sleep > 0:
                time.sleep(sleep)
            self._last_call = time.monotonic()

_rate_limiter = RateLimiter(MAX_RPS)

# ── Custom exception for rate-limit early exit ────────────────────────────────

class RateLimitHit(Exception):
    """Raised when OpenAlex returns 429 — signals the fetch loop to stop cleanly."""
    pass

# ── HTTP helper ────────────────────────────────────────────────────────────────

def api_get(endpoint: str, params: dict = None, retries: int = 3) -> dict:
    """
    Rate-limited GET with back-off.
    Raises RateLimitHit on 429 so the caller can exit immediately
    instead of sleeping for hours.
    """
    url = endpoint if endpoint.startswith("http") else f"{BASE_URL}/{endpoint}"
    for attempt in range(retries):
        _rate_limiter.wait()
        try:
            request_params = dict(params or {})
            request_params["api_key"] = OPENALEX_API_KEY
            resp = requests.get(url, params=request_params, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                time_wait = resp.headers.get("Retry-After", "?")
                wait = int (time_wait) /3600
                log.warning(f"Rate-limited (Retry-After: {wait}s) — stopping this year and saving collected data.")
                raise RateLimitHit()
            resp.raise_for_status()
            return resp.json()
        except RateLimitHit:
            raise   # propagate immediately, no retry
        except requests.RequestException as exc:
            wait = 2 ** attempt
            log.warning(f"Request failed (attempt {attempt+1}/{retries}): {exc}. Retry in {wait}s")
            time.sleep(wait)
    log.error(f"Giving up on {url}")
    return {}

# ── Per-paper extraction ───────────────────────────────────────────────────────

def extract_corresponding(authorships: list) -> tuple[list, list]:
    author_ids, inst_ids = [], []
    for entry in authorships:
        if entry.get("is_corresponding"):
            raw_aid = (entry.get("author") or {}).get("id", "")
            if raw_aid:
                author_ids.append(raw_aid.replace("https://openalex.org/", ""))
            for inst in entry.get("institutions") or []:
                raw_iid = inst.get("id", "")
                if raw_iid:
                    inst_ids.append(raw_iid.replace("https://openalex.org/", ""))
    return author_ids, inst_ids




def flatten(work: dict) -> dict:
    pub_year    = work.get("publication_year")
    authorships = work.get("authorships") or []
    corr_author_ids, corr_inst_ids = extract_corresponding(authorships)
    primary_loc  = work.get("primary_location") or {}
    source       = primary_loc.get("source") or {}
    open_access = work.get("open_access") or {}
    source_stats = source.get("summary_stats") or {}
    apc          = work.get("apc_list") or {}
    topic        = work.get("primary_topic") or {}
    return {
        "doi":                                work.get("doi"),
        "publication_year":                   pub_year,
        "author_count":                       len(authorships),
        "countries_distinct_count":           work.get("countries_distinct_count"),
        "institutions_distinct_count":        work.get("institutions_distinct_count"),
        "type":                               work.get("type"),
        "corresponding_author_ids":           "|".join(corr_author_ids),
        "corresponding_institution_ids":      "|".join(corr_inst_ids),
        "source_id":                          source.get("id", "").replace("https://openalex.org/", ""),
        "source_display_name":                source.get("display_name"),
        "source_type":                        source.get("type"),
        "source_is_core":                     source.get("is_core"),
        "source_is_in_doaj":                  source.get("is_in_doaj"),
        "source_issn":                        "|".join(source.get("issn") or []),
        "source_has_issn":                     bool(source.get("issn") or []),   
        "apc_list_value_usd":                 apc.get("value_usd"),
        "is_open_access":                     open_access.get("is_oa"),
        "oa_status":                          open_access.get("oa_status"),
        "primary_topic_id":                   topic.get("id", "").replace("https://openalex.org/", ""),
        "primary_topic_display_name":         topic.get("display_name"),
        "referenced_works_count":             work.get("referenced_works_count"),
    }

# ── Single-year fetch ──────────────────────────────────────────────────────────

def fetch_year(year: int) -> tuple[pd.DataFrame, bool]:
    """
    Fetches papers for one year. Returns (DataFrame, completed).
    completed=False means a rate-limit stopped it early — partial data is still returned.
    """
    params = {
        "filter":   f"primary_topic.field.id:{FIELD_ID},publication_year:{year},primary_location.source.type:journal",
        "select":   SELECT_FIELDS,
        "per_page": PER_PAGE,
        "cursor":   "*",
    }

    rows      = []
    page      = 0
    completed = True

    try:
        first_page = api_get("works", params=params)
        total      = first_page.get("meta", {}).get("count", "?")
        log.info(f"Year {year}: {total:,} papers to fetch" if isinstance(total, int)
                 else f"Year {year}: {total} papers to fetch")

        current = first_page
        while True:
            results = current.get("results", [])
            if not results:
                break

            for work in results:
                try:
                    rows.append(flatten(work))
                except Exception as exc:
                    log.warning(f"Skipping {work.get('id')}: {exc}")

            page += 1
            log.info(f"Year {year} — page {page:>4d}  |  {len(rows):>7,} papers collected")

            next_cursor = current.get("meta", {}).get("next_cursor")
            if not next_cursor:
                break
            params["cursor"] = next_cursor
            current = api_get("works", params=params)

    except RateLimitHit:
        completed = False
        log.warning(f"Year {year}: rate-limited after {len(rows):,} papers — saving partial data.")

    return pd.DataFrame(rows), completed

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("═" * 64)
    log.info("OpenAlex extractor — Agricultural & Biological Sciences")
    log.info(f"Field ID : {FIELD_ID}  |  Years: {YEARS}")
    log.info(f"Threads  : {YEAR_WORKERS} year-workers  |  Rate cap: {MAX_RPS} req/s")
    log.info("Rate-limit behaviour: STOP and save partial data (no waiting)")
    log.info("═" * 64)

    completed_files: list[tuple[int, str, bool]] = []   # (year, path, fully_complete)
    years_to_run:    list[int] = []

    for year in YEARS:
        yf = os.path.join(OUTPUT_DIR, f"agri_bio_{year}.csv")
        if os.path.exists(yf):
            log.info(f"Year {year}: file already exists — SKIPPING")
            completed_files.append((year, yf, True))
        else:
            years_to_run.append(year)

    if years_to_run:
        with ThreadPoolExecutor(max_workers=YEAR_WORKERS, thread_name_prefix="year") as pool:
            future_to_year = {}
            for i, year in enumerate(years_to_run):
                time.sleep(i * 2)   # stagger thread starts to avoid burst
                future_to_year[pool.submit(fetch_year, year)] = year

            for future in as_completed(future_to_year):
                year = future_to_year[future]
                try:
                    df_year, full = future.result()
                    yf = os.path.join(OUTPUT_DIR, f"agri_bio_{year}.csv")
                    if not df_year.empty:
                        df_year.to_csv(yf, index=False, encoding="utf-8")
                        status = "COMPLETE" if full else "PARTIAL"
                        log.info(f"Year {year} {status}: {len(df_year):,} rows → {yf}")
                        completed_files.append((year, yf, full))
                    else:
                        log.warning(f"Year {year}: no data collected, skipping file.")
                except Exception as exc:
                    log.error(f"Year {year} FAILED: {exc}")

    # ── Merge whatever was collected ──
    completed_files.sort(key=lambda t: t[0])
    if completed_files:
        log.info("Merging available year files …")
        df_all = pd.concat(
            [pd.read_csv(yf) for _, yf, _ in completed_files],
            ignore_index=True,
        )
        df_all.to_csv(FINAL_OUTPUT, index=False, encoding="utf-8")

        # Summary
        log.info("═" * 64)
        log.info(f"Final CSV: {len(df_all):,} total rows → '{FINAL_OUTPUT}'")
        for year, yf, full in completed_files:
            n = len(pd.read_csv(yf))
            status = "complete" if full else "⚠ partial — rate-limited"
            log.info(f"  {year}: {n:,} rows  [{status}]")
        log.info("═" * 64)
    else:
        log.error("No data collected at all — check errors above.")