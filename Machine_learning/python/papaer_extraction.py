#!/usr/bin/env python3
"""
OpenAlex — Agricultural & Biological Sciences paper extractor
Field: Agricultural and Biological Sciences (primary_topic.field.id = 11)
Window: 2020–2023

TIMEOUT BEHAVIOUR:
    If OpenAlex returns a 429 rate-limit, the request waits per Retry-After
    (or a default backoff) and then continues. No early stop.
    All year files are merged into the final CSV at the end.

RESUME LOGIC:
  Per-year output files are written on completion or early-stop:
    agri_bio_2020.csv … agri_bio_2023.csv
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
from datetime import datetime, timedelta
from seaborn.objects import Path

# ── Configuration ──────────────────────────────────────────────────────────────

EMAIL          = "locostve4526@gmail.com"
FIELD_ID       = "11"
YEARS          = [2020, 2021, 2022, 2023]
PER_PAGE       = 200
COMPUTE_HINDEX = False  # Keep False for a fast run

YEAR_WORKERS   = 4
HINDEX_WORKERS = 6
MAX_RPS        = 8       # Hard ceiling shared across ALL threads

OUTPUT_DIR   = "/home/ramir713/repos/PublicationAnalysis/data/temp"
FINAL_OUTPUT = os.path.join(OUTPUT_DIR, "agri_bio_papers_2020_2023.csv")

BASE_URL = "https://api.openalex.org"
HEADERS  = {"User-Agent": f"mailto:{EMAIL}"}

SELECT_FIELDS = ",".join([
    "id", "doi", "publication_year", "authorships",
    "countries_distinct_count", "institutions_distinct_count",
    "primary_location", "apc_list", "primary_topic", "referenced_works_count",
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

# ── HTTP helper ────────────────────────────────────────────────────────────────

def api_get(endpoint: str, params: dict = None, retries: int = 3) -> dict:
    """
    Rate-limited GET with back-off.
    On 429, waits and retries instead of stopping the year.
    """
    url = endpoint if endpoint.startswith("http") else f"{BASE_URL}/{endpoint}"
    attempt = 0
    while True:
        _rate_limiter.wait()
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                try:
                    wait_seconds = float(retry_after) if retry_after is not None else None
                except ValueError:
                    wait_seconds = None
                if wait_seconds is None:
                    wait_seconds = 60.0
                wait_hours = wait_seconds / 3600.0
                log.warning(
                    "Rate-limited (Retry-After: %.2fh) - waiting before retry.",
                    wait_hours,
                )
                time.sleep(wait_seconds)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            attempt += 1
            if attempt >= retries:
                log.error(f"Giving up on {url}")
                return {}
            wait = 2 ** (attempt - 1)
            log.warning(f"Request failed (attempt {attempt}/{retries}): {exc}. Retry in {wait}s")
            time.sleep(wait)

# ── H-index helper ─────────────────────────────────────────────────────────────

_hindex_cache: dict[tuple, Optional[int]] = {}
_hindex_lock  = threading.Lock()

def hindex_at_year(author_id: str, before_year: int) -> Optional[int]:
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

#Extract 2 year exact citation

def get_exact_2y_cites(
    df_processed,
    id_col="openalex_id",
    date_col="publication_date",
    email=None,
    sleep=0.12,
    checkpoint_path=None,
    save_every=100,
    timeout=20,
    max_retries=4,
):
    """
    Compute exact citation windows per paper using OpenAlex API.

    Appends to df_processed:
      - citations_year_1_exact: from publication day to +364 days
      - citations_year_2_exact: from +365 to +729 days
      - citations_first_2y_exact: year_1 + year_2

    Designed for large batches with resume/checkpoint support.
    """

    base_url = "https://api.openalex.org/works"
    session = requests.Session()
    user_agent = f"mailto:{email}" if email else "OpenAlex-Exact2Y-Citations"
    session.headers.update({"User-Agent": user_agent})

    def _normalize_work_id(work_id):
        s = str(work_id).strip()
        if s.startswith("http"):
            s = s.rstrip("/").split("/")[-1]
        return s

    def _query_count(short_id, from_dt, to_dt):
        params = {
            "filter": f"cites:{short_id},from_publication_date:{from_dt},to_publication_date:{to_dt}",
            "select": "id",
            "per_page": 1,
        }
        if email:
            params["mailto"] = email

        for attempt in range(1, max_retries + 1):
            try:
                resp = session.get(base_url, params=params, timeout=timeout)
                status = resp.status_code
                if status in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {status}: retryable")
                resp.raise_for_status()
                count = resp.json().get("meta", {}).get("count", 0)
                return int(count) if count is not None else 0
            except Exception as e:
                if attempt == max_retries:
                    print(f"ERROR final ({short_id}): {e}")
                    return np.nan
                backoff = (2 ** (attempt - 1)) * sleep + random.uniform(0, sleep)
                time.sleep(backoff)
        return np.nan

    # Pre-normalize work IDs once for efficient lookups
    work_ids_short = df_processed[id_col].astype(str).map(_normalize_work_id)

    # Resume from checkpoint if available
    cached = {}
    cp = Path(checkpoint_path) if checkpoint_path else None
    if cp and cp.exists():
        cp_df_processed = pd.read_csv(cp)
        required_cache_cols = {
            id_col,
            "citations_year_1_exact",
            "citations_year_2_exact",
            "citations_first_2y_exact",
        }
        if required_cache_cols.issubset(set(cp_df_processed.columns)):
            cp_ids_short = cp_df_processed[id_col].astype(str).map(_normalize_work_id)
            for short_id, y1, y2, total in zip(
                cp_ids_short,
                cp_df_processed["citations_year_1_exact"],
                cp_df_processed["citations_year_2_exact"],
                cp_df_processed["citations_first_2y_exact"],
            ):
                cached[short_id] = (y1, y2, total)
            print(f"Loaded checkpoint with {len(cached)} papers from {cp}")

    results = dict(cached)
    total = len(df_processed)
    processed_now = 0

    for i, (short_id, pub_date_str) in enumerate(zip(work_ids_short, df_processed[date_col]), 1):
        if short_id in results and not any(pd.isna(v) for v in results[short_id]):
            if i % 200 == 0 or i == total:
                print(f"  progress: {i}/{total} (cached/resumed)")
            continue

        try:
            pub_date = datetime.strptime(str(pub_date_str), "%Y-%m-%d")
        except Exception:
            results[short_id] = (np.nan, np.nan, np.nan)
            continue

        y1_start = pub_date
        y1_end = pub_date + timedelta(days=364)
        y2_start = pub_date + timedelta(days=365)
        y2_end = pub_date + timedelta(days=729)

        y1_count = _query_count(short_id, y1_start.strftime("%Y-%m-%d"), y1_end.strftime("%Y-%m-%d"))
        y2_count = _query_count(short_id, y2_start.strftime("%Y-%m-%d"), y2_end.strftime("%Y-%m-%d"))

        if pd.isna(y1_count) or pd.isna(y2_count):
            total_2y = np.nan
        else:
            total_2y = int(y1_count) + int(y2_count)

        results[short_id] = (y1_count, y2_count, total_2y)
        processed_now += 1

        # Save incremental checkpoint for large runs
        if cp and (processed_now % save_every == 0):
            tmp = pd.DataFrame([
                {
                    id_col: k,
                    "citations_year_1_exact": v[0],
                    "citations_year_2_exact": v[1],
                    "citations_first_2y_exact": v[2],
                }
                for k, v in results.items()
            ])
            tmp.to_csv(cp, index=False)
            print(f"  checkpoint saved: {len(tmp)} rows")

        time.sleep(sleep)

        if i % 25 == 0 or i == total:
            print(f"  progress: {i}/{total}")

    lookup = work_ids_short.map(lambda k: results.get(k, (np.nan, np.nan, np.nan)))
    df_processed["citations_year_1_exact"] = lookup.map(lambda v: v[0])
    df_processed["citations_year_2_exact"] = lookup.map(lambda v: v[1])
    df_processed["citations_first_2y_exact"] = lookup.map(lambda v: v[2])

    # Final checkpoint write
    if cp:
        final_cp = pd.DataFrame({
            id_col: work_ids_short,
            "citations_year_1_exact": df_processed["citations_year_1_exact"],
            "citations_year_2_exact": df_processed["citations_year_2_exact"],
            "citations_first_2y_exact": df_processed["citations_first_2y_exact"],
        }).drop_duplicates(subset=[id_col], keep="first")
        final_cp.to_csv(cp, index=False)
        print(f"Final checkpoint saved to {cp}")

    return df_processed

# Apply exact 2-year enrichment (resume-safe for large collections)
checkpoint_file = Path("/home/ramir713/repos/PublicationAnalysis/data/machine_learning_data/data_ready_for_ml")



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
    if not corr_author_ids:
        return ""
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=HINDEX_WORKERS, thread_name_prefix="hindex") as pool:
        future_to_aid = {pool.submit(hindex_at_year, aid, pub_year): aid for aid in corr_author_ids}
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

# ── Single-year fetch ──────────────────────────────────────────────────────────

def fetch_year(year: int) -> tuple[pd.DataFrame, bool]:
    """
    Fetches papers for one year. Returns (DataFrame, completed).
    completed is True when the loop finishes without an unexpected exception.
    """
    params = {
        "filter":   f"primary_topic.field.id:{FIELD_ID},publication_year:{year},type:article",
        "select":   SELECT_FIELDS,
        "per_page": PER_PAGE,
        "cursor":   "*",
    }

    rows      = []
    page      = 0
    completed = True

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