'''
The idea of this code is to extract papers from OpenAlex with the primary topic being agronomy.
The code extract the papers and other key features needed for the analysis.
The period of the papers extracted is from 2020 to 2023, giving all papers the opportunity to obtain citations in their first 2 years.

'''
#!/usr/bin/env python3
"""
OpenAlex — Agricultural & Biological Sciences paper extractor
Field: Agricultural and Biological Sciences (primary_topic.field.id = 11)
Window: 2020–2023

CONCURRENCY MODEL:
  - Each year runs in its own thread (4 threads for 4 years) → ~4× faster main fetch
  - H-index lookups within each year are also parallelised via a shared thread pool
  - ALL threads share one RateLimiter capped at MAX_RPS requests/second, so the
    total request rate never exceeds the OpenAlex polite-pool ceiling regardless of
    how many threads are active.

RESUME LOGIC:
  Per-year output files are written atomically on completion:
    agri_bio_2020.csv … agri_bio_2023.csv
  On restart any year whose file already exists is skipped entirely.
  The final step merges all per-year files into agri_bio_papers_2020_2023.csv.

NOTES:
  - H-index is approximated using works published *before* the paper's year but
    with current citation counts (OpenAlex has no historical citation snapshots).
  - source_2yr_mean_citedness is the closest OpenAlex proxy for JIF; it reflects
    the current value, not the historical value at publication time.
  - Set COMPUTE_HINDEX = False to skip h-index lookups (much faster).
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

EMAIL          = "ramir713@purdue.edu"   # Enables polite pool (~10 req/s)
FIELD_ID       = "11"                            # Agricultural and Biological Sciences
YEARS          = [2020, 2021, 2022, 2023]
PER_PAGE       = 200
COMPUTE_HINDEX = True

# Concurrency knobs
MAX_RPS          = 8    # Hard ceiling shared across ALL threads (polite pool ≤ 10)
YEAR_WORKERS     = 4    # One thread per year — matches your 4 CPUs
HINDEX_WORKERS   = 6    # Sub-pool for h-index lookups within each year's thread

OUTPUT_DIR   = "."
FINAL_OUTPUT = os.path.join(OUTPUT_DIR, "agri_bio_papers_2020_2023.csv")

BASE_URL = "https://api.openalex.org"
HEADERS  = {"User-Agent": f"mailto:{EMAIL}"}

SELECT_FIELDS = ",".join([
    "id", "doi", "publication_year", "authorships",
    "countries_distinct_count", "institutions_distinct_count",
    "primary_location", "apc_list", "primary_topic", "referenced_works_count",
])

# ── Logging (thread-safe by default in Python) ─────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(threadName)s]  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Shared rate limiter ────────────────────────────────────────────────────────

class RateLimiter:
    """
    Token-bucket rate limiter, safe for use across multiple threads.
    All threads call .wait() before every API request; the limiter ensures
    the total rate across all callers never exceeds `max_rps`.
    """
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

# ── HTTP helper ────────────────────────────────────────────────────────────────

def api_get(endpoint: str, params: dict = None, retries: int = 5) -> dict:
    """Rate-limited GET with exponential back-off and 429 handling."""
    url = endpoint if endpoint.startswith("http") else f"{BASE_URL}/{endpoint}"
    for attempt in range(retries):
        _rate_limiter.wait()
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                log.warning(f"Rate-limited — sleeping {wait}s (Retry-After header)")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            wait = 2 ** attempt
            log.warning(f"Request failed (attempt {attempt+1}/{retries}): {exc}. Retry in {wait}s")
            time.sleep(wait)
    log.error(f"Giving up on {url}")
    return {}

# ── H-index helper ─────────────────────────────────────────────────────────────

_hindex_cache:  dict[tuple, Optional[int]] = {}
_hindex_lock  = threading.Lock()

def hindex_at_year(author_id: str, before_year: int) -> Optional[int]:
    """
    Approximate h-index for an author using only their works published
    strictly before `before_year`. Thread-safe in-memory cache prevents
    redundant API calls when the same author appears in multiple papers.
    """
    key = (author_id, before_year)

    with _hindex_lock:
        if key in _hindex_cache:
            return _hindex_cache[key]

    citation_counts = []
    cursor = "*"
    while True:
        data = api_get("works", params={
            "filter":   f"authorships.author.id:{author_id},publication_year:<{before_year}",
            "select":   "cited_by_count",
            "per_page": 200,
            "cursor":   cursor,
        })
        citation_counts.extend(r.get("cited_by_count", 0) for r in data.get("results", []))
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break

    h: Optional[int] = None
    if citation_counts:
        s = sorted(citation_counts, reverse=True)
        h = sum(1 for rank, c in enumerate(s, start=1) if c >= rank)

    with _hindex_lock:
        _hindex_cache[key] = h
    return h

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


def resolve_hindices(corr_author_ids: list, pub_year: int) -> str:
    """
    Resolves h-index for each corresponding author in parallel using the
    shared HINDEX_WORKERS sub-pool. Returns a pipe-separated string.
    """
    if not corr_author_ids:
        return ""

    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=HINDEX_WORKERS,
                            thread_name_prefix="hindex") as pool:
        future_to_aid = {
            pool.submit(hindex_at_year, aid, pub_year): aid
            for aid in corr_author_ids
        }
        for future in as_completed(future_to_aid):
            aid = future_to_aid[future]
            try:
                h = future.result()
                results[aid] = "" if h is None else str(h)
            except Exception as exc:
                log.warning(f"h-index failed for {aid}: {exc}")
                results[aid] = ""

    return "|".join(results.get(aid, "") for aid in corr_author_ids)


def flatten(work: dict) -> dict:
    pub_year    = work.get("publication_year")
    authorships = work.get("authorships") or []

    corr_author_ids, corr_inst_ids = extract_corresponding(authorships)

    hindex_str = resolve_hindices(corr_author_ids, pub_year) \
                 if (COMPUTE_HINDEX and pub_year) else ""

    primary_loc  = work.get("primary_location") or {}
    source       = primary_loc.get("source") or {}
    source_stats = source.get("summary_stats") or {}
    apc          = work.get("apc_list") or {}
    topic        = work.get("primary_topic") or {}

    return {
        "doi":                                work.get("doi"),
        "publication_year":                   pub_year,
        "author_count":                       len(authorships),
        "countries_distinct_count":           work.get("countries_distinct_count"),
        "institutions_distinct_count":        work.get("institutions_distinct_count"),
        "corresponding_author_ids":           "|".join(corr_author_ids),
        "corresponding_institution_ids":      "|".join(corr_inst_ids),
        "corresponding_author_hindex_at_pub": hindex_str,
        "source_id":                          source.get("id", "").replace("https://openalex.org/", ""),
        "source_display_name":                source.get("display_name"),
        "source_2yr_mean_citedness":          source_stats.get("2yr_mean_citedness"),
        "source_type":                        source.get("type"),
        "apc_list_value_usd":                 apc.get("value_usd"),
        "primary_topic_id":                   topic.get("id", "").replace("https://openalex.org/", ""),
        "primary_topic_display_name":         topic.get("display_name"),
        "referenced_works_count":             work.get("referenced_works_count"),
    }

# ── Single-year fetch (runs in its own thread) ─────────────────────────────────

def fetch_year(year: int) -> pd.DataFrame:
    """
    Fetches all papers for one year sequentially (cursor pagination requires it).
    Designed to be called from a thread — uses the shared rate limiter and logger.
    """
    params = {
        "filter":   f"primary_topic.field.id:{FIELD_ID},publication_year:{year},type:article",
        "select":   SELECT_FIELDS,
        "per_page": PER_PAGE,
        "cursor":   "*",
    }

    first_page = api_get("works", params=params)
    total      = first_page.get("meta", {}).get("count", "?")
    log.info(f"Year {year}: {total:,} papers to fetch" if isinstance(total, int)
             else f"Year {year}: {total} papers to fetch")

    rows    = []
    page    = 0
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

    return pd.DataFrame(rows)

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("═" * 64)
    log.info("OpenAlex extractor — Agricultural & Biological Sciences")
    log.info(f"Field ID : {FIELD_ID}  |  Years: {YEARS}")
    log.info(f"Threads  : {YEAR_WORKERS} year-workers + {HINDEX_WORKERS} h-index sub-workers")
    log.info(f"Rate cap : {MAX_RPS} req/s (shared across all threads)")
    if COMPUTE_HINDEX:
        log.warning("COMPUTE_HINDEX=True — set False for a much faster first pass.")
    log.info("═" * 64)

    completed_files: list[str] = []
    years_to_run:    list[int] = []

    for year in YEARS:
        yf = os.path.join(OUTPUT_DIR, f"agri_bio_{year}.csv")
        if os.path.exists(yf):
            log.info(f"Year {year}: file already exists — SKIPPING")
            completed_files.append((year, yf))
        else:
            years_to_run.append(year)

    # ── Run pending years in parallel ──
    if years_to_run:
        with ThreadPoolExecutor(max_workers=YEAR_WORKERS,
                                thread_name_prefix="year") as pool:
            future_to_year = {}
            for i, year in enumerate(years_to_run):
                time.sleep(i * 2)   # stagger by 2s per thread
                future_to_year[pool.submit(fetch_year, year)] = year
            for future in as_completed(future_to_year):
                year = future_to_year[future]
                try:
                    df_year = future.result()
                    yf      = os.path.join(OUTPUT_DIR, f"agri_bio_{year}.csv")
                    df_year.to_csv(yf, index=False, encoding="utf-8")
                    log.info(f"Year {year} DONE: {len(df_year):,} rows → {yf}")
                    completed_files.append((year, yf))
                except Exception as exc:
                    log.error(f"Year {year} FAILED: {exc}")

    # ── Merge in chronological order ──
    completed_files.sort(key=lambda t: t[0])
    if completed_files:
        log.info("Merging per-year files …")
        df_all = pd.concat(
            [pd.read_csv(yf) for _, yf in completed_files],
            ignore_index=True,
        )
        df_all.to_csv(FINAL_OUTPUT, index=False, encoding="utf-8")
        log.info(f"Done. {len(df_all):,} total rows → '{FINAL_OUTPUT}'")
    else:
        log.error("No year files to merge — check for errors above.")