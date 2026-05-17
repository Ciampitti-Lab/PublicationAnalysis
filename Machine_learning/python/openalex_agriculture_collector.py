"""
=============================================================================
OpenAlex Data Collector — Top 100 Agriculture & Agronomy Authors
=============================================================================
Input  : top100_agri_agronomy_authors.csv  (OpenAlex IDs already resolved)
Output : openalex_output/
            authors.csv       — Full author metadata (one row per author)
            works.csv         — Corresponding-author papers in time window
            sources.csv       — Journal/venue metadata for all venues found
            field_reference.csv — Human-readable description of every API field

FILTERS APPLIED TO WORKS
-------------------------
  • Publication year within [YEAR_START, YEAR_END]

Change the time window by editing the two constants below.

API   : https://api.openalex.org  (free; polite pool with email)
Docs  : https://docs.openalex.org
=============================================================================
"""

import csv
import json
import logging
import time
from pathlib import Path

import requests

# =============================================================================
# CONFIGURATION  ← edit these before running
# =============================================================================

# Path to the input CSV (adjust if running from a different directory)
INPUT_CSV = Path(
    "/home/ramir713/repos/PublicationAnalysis/data/machine_learning_data/top100_agronomy_scientists.csv"
)

# ── TIME WINDOW ──────────────────────────────────────────────────────────────
YEAR_START = 2018  # inclusive
YEAR_END = 2023  # inclusive
# ─────────────────────────────────────────────────────────────────────────────

# Output folder
OUTPUT_DIR = Path(
    "/home/ramir713/repos/PublicationAnalysis/data/machine_learning_data/openalex_output"
)

# Your email → puts you in OpenAlex's "polite pool" (faster, ~10 req/s)
CONTACT_EMAIL = "ramir713@purdue.edu"

# Seconds between requests (polite pool cap is ~10 req/s)
REQUEST_DELAY = 0.12

# Max retries on transient HTTP errors
MAX_RETRIES = 5

# Minimize console output. Set to False for detailed progress logs.
QUIET_MODE = True

# =============================================================================
# OPENALEX API FIELD REFERENCE
# All fields available in each entity type, documented for analysis reference.
# Fields marked [LIST] are stored as JSON strings in the CSV.
# Fields marked [NESTED] are flattened with dot-notation column names.
# =============================================================================

WORK_FIELDS = {
    # ── Identifiers ──────────────────────────────────────────────────────────
    "id": "OpenAlex URL ID  (https://openalex.org/W…)",
    "doi": "DOI — canonical external ID for works",
    # ── Publication metadata ─────────────────────────────────────────────────
    "title": "Full title of the work",
    "publication_year": "Integer publication year",
    "publication_date": "ISO 8601 full publication date",
    "type": "Normalised type: article | book | book-chapter | dataset | dissertation | editorial | erratum | grant | letter | other | paratext | peer-review | posted-content | preprint | proceedings | proceedings-article | reference-entry | report | retraction | review | standard | supplementary-materials",
    # ── Citation metrics ─────────────────────────────────────────────────────
    "cited_by_count": "Total citations received",
    "cited_by_api_url": "API URL to retrieve the list of citing works",
    "fwci": "Field-Weighted Citation Impact (received / expected)",
    "citation_normalized_percentile.value": "FWCI expressed as a percentile",
    # ── Authorship ───────────────────────────────────────────────────────────
    "authorships": "[LIST] [{author_position, author:{id,display_name,orcid}, institutions:[{id,display_name,ror,country_code,type}], countries:[], is_corresponding, raw_affiliation_strings, raw_author_name}]",
    "corresponding_author_ids": "[LIST] OpenAlex IDs of corresponding authors",
    "corresponding_institution_ids": "[LIST] OpenAlex institution IDs of corresponding author affiliations",
    "authors_count": "Number of authors (len of authorships list)",
    "countries_distinct_count": "Number of distinct country codes across all authorships",
    "institutions_distinct_count": "Number of distinct institutions across all authorships",
    # ── Focal-author authorship (columns added by this script) ───────────────
    "queried_author_id": "OpenAlex ID of the author this work was fetched for",
    "queried_author_position": "first | middle | last",
    "queried_author_is_corresponding": "Boolean: True when this author is the corresponding author",
    # ── Open Access ──────────────────────────────────────────────────────────
    "is_oa": "Boolean shortcut for open_access.is_oa",
    "oa_status": "diamond | gold | hybrid | bronze | green | closed",
    # ── Source (journal / venue) ─────────────────────────────────────────────
    "source_id": "OpenAlex ID of the publishing venue",
    "source_display_name": "Name of the journal / venue",
    "source_issn_l": "ISSN-L of the venue",
    "source_issn": "[LIST] All ISSNs of the venue",
    "source_type": "journal | conference | repository | ebook-platform | book-series | metadata",
    "source_is_oa": "Boolean: venue is fully open access",
    "source_host_org_name": "Publisher name",
    # ── APC ──────────────────────────────────────────────────────────────────
    "apc_list_value_usd": "Article processing charge list price in USD",
    "apc_paid_value_usd": "APC actually paid in USD (when available)",
    # ── Topics / concepts ────────────────────────────────────────────────────
    "primary_topic_id": "OpenAlex ID of the primary topic",
    "primary_topic_name": "Display name of the primary topic",
    "primary_subfield_id": "OpenAlex ID of the subfield",
    "primary_subfield_name": "Display name of the subfield",
    "primary_field_id": "OpenAlex ID of the field",
    "primary_field_name": "Display name of the field",
    "sustainable_development_goals": "[LIST] UN SDGs with scores",
    # ── References / related ─────────────────────────────────────────────────
    "referenced_works_count": "Number of works cited by this work", 
}

AUTHOR_FIELDS = {
    # ── Identifiers ──────────────────────────────────────────────────────────
    "id": "OpenAlex URL ID (https://openalex.org/A…)",
    "orcid": "ORCID URL — canonical external ID for authors",
    # ── Names ────────────────────────────────────────────────────────────────
    "display_name": "Author's canonical name in OpenAlex",
    # ── Metrics ──────────────────────────────────────────────────────────────
    "works_count": "Total works attributed to this author",
    "cited_by_count": "Total citations across all this author's works",
    "summary_stats.h_index": "h-index",
    "summary_stats.i10_index": "i10-index (papers with ≥10 citations)",
    "summary_stats.oa_percent": "Percentage of works that are open access",
    "summary_stats.2yr_mean_citedness": "Mean citations per paper in the last 2 years",
    "summary_stats.2yr_h_index": "h-index over the last 2 years",
    "summary_stats.2yr_i10_index": "i10-index over the last 2 years",
    "summary_stats.2yr_works_count": "Works published in the last 2 years",
    "summary_stats.2yr_cited_by_count": "Citations received in the last 2 years",
    # ── Topics ───────────────────────────────────────────────────────────────
    "top_topic_id": "OpenAlex ID of author's primary topic",
    "top_topic_name": "Name of author's primary topic",
    # ── URLs ─────────────────────────────────────────────────────────────────
    "works_api_url": "API URL to retrieve all works by this author",
}

SOURCE_FIELDS = {
    # ── Identifiers ──────────────────────────────────────────────────────────
    "id": "OpenAlex URL ID (https://openalex.org/S…)",
    "issn_l": "ISSN-L — canonical external ID for sources",
    "issn": "[LIST] All ISSNs for this source",
    # ── Names ────────────────────────────────────────────────────────────────
    "display_name": "Journal or venue name",
    "abbreviated_title": "Abbreviated title from the ISSN Centre",
    # ── Publisher & host ─────────────────────────────────────────────────────
    "host_organization": "OpenAlex ID of host (Publisher or Institution)",
    "host_organization_name": "Name of the host organisation",
    # ── Type & access ────────────────────────────────────────────────────────
    "type": "journal | conference | repository | ebook-platform | book-series | metadata",
    "is_oa": "Boolean: fully open access source",
    "is_in_doaj": "Boolean: indexed in DOAJ",
    "is_core": "Boolean: indexed in CORE",
    "is_indexed_in_scopus": "Boolean: indexed in Scopus",
    # ── Metrics ──────────────────────────────────────────────────────────────
    "works_count": "Total works hosted by this source",
    "cited_by_count": "Total citations to all works in this source",
    "summary_stats.h_index": "Journal h-index",
    "summary_stats.i10_index": "Journal i10-index",
    "summary_stats.oa_percent": "Percentage of OA works",
    "summary_stats.2yr_mean_citedness": "2-year mean citedness (≈ Impact Factor)",
    "summary_stats.2yr_h_index": "h-index over last 2 years",
    "counts_by_year": "[LIST] [{year, works_count, cited_by_count}]",
    # ── Topics ───────────────────────────────────────────────────────────────
    "topics": "[LIST] Most common topics in this source",
}


# =============================================================================
# HTTP SESSION UTILITIES
# =============================================================================

BASE_URL = "https://api.openalex.org"
HEADERS = {"User-Agent": f"AgricultureCitationAnalysis/1.0 (mailto:{CONTACT_EMAIL})"}


def _log_progress(message: str) -> None:
    if not QUIET_MODE:
        logging.info(message)


def _normalize_openalex_id(value: str) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = text.rstrip("/")
    if "/" in text:
        text = text.split("/")[-1]
    return text.upper()


def _get(url: str, params: dict = None) -> dict:
    """GET with exponential back-off retry. Respects REQUEST_DELAY between calls."""
    time.sleep(REQUEST_DELAY)
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                logging.warning(f"Rate-limited — sleeping {wait}s …")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            wait = 2**attempt
            logging.warning(
                f"Request error ({exc}). Retry {attempt+1}/{MAX_RETRIES} in {wait}s …"
            )
            time.sleep(wait)
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {url}")


def reconstruct_abstract(inverted_index: dict) -> str:
    """Rebuild plain text from OpenAlex's abstract inverted index."""
    if not inverted_index:
        return ""
    max_pos = max(pos for positions in inverted_index.values() for pos in positions)
    words = [""] * (max_pos + 1)
    for word, positions in inverted_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words)


# =============================================================================
# STEP 1 — LOAD AUTHORS FROM CSV
# =============================================================================


def load_authors(csv_path: Path) -> list[dict]:
    """
    Read the input CSV and return a list of author dicts.
    Expected columns (at minimum): position, author, openalex_id
    All extra columns are preserved and carried through.
    """
    authors = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            oa_id_raw = (
                row.get("openalex_id")
                or row.get("OP_id")
                or row.get("openalex_url")
                or ""
            )
            oa_id = _normalize_openalex_id(oa_id_raw)
            if not oa_id:
                row_id = row.get("rank_in_subfield") or row.get("position") or ""
                logging.warning(f"Row {row_id} has no openalex_id — skipping.")
                continue
            authors.append(
                {
                    "position": str(
                        row.get("position") or row.get("rank_in_subfield") or ""
                    ).strip(),
                    "name": str(row.get("author") or row.get("authfull") or "").strip(),
                    "institution": str(
                        row.get("institution") or row.get("inst_name") or ""
                    ).strip(),
                    "country": str(row.get("country") or "").strip(),
                    "rank": str(row.get("rank") or row.get("rank_in_subfield") or "").strip(),
                    "main_field": str(row.get("main_field") or "").strip(),
                    "subfield": str(row.get("subfield_1") or row.get("subfield") or "").strip(),
                    "selection_reason": str(row.get("selection_reason") or "").strip(),
                    "openalex_id": oa_id,
                    "openalex_url": str(
                        row.get("openalex_url")
                        or row.get("OP_id")
                        or f"https://openalex.org/{oa_id}"
                    ).strip(),
                    "match_status": str(
                        row.get("openalex_match_status")
                        or row.get("ORCID_match_status")
                        or ""
                    ).strip(),
                    "match_score": str(row.get("openalex_match_score") or "").strip(),
                }
            )
    _log_progress(f"Loaded {len(authors)} authors from {csv_path}")
    return authors


# =============================================================================
# STEP 2 — FETCH AUTHOR METADATA
# =============================================================================


def fetch_author_metadata(oa_id: str) -> dict:
    """Fetch the full Author object from OpenAlex."""
    return _get(f"{BASE_URL}/authors/{oa_id}")


def flatten_author(raw: dict, csv_meta: dict) -> dict:
    """
    Merge OpenAlex Author object with the original CSV metadata into one flat row.
    Nested / list fields are serialised as JSON strings.
    """
    ss = raw.get("summary_stats") or {}
    last_insts = raw.get("last_known_institutions") or []
    ids = raw.get("ids") or {}

    return {
        # ── From input CSV ───────────────────────────────────────────────────
        "csv_position": csv_meta["position"],
        "csv_name": csv_meta["name"],
        "csv_institution": csv_meta["institution"],
        "csv_country": csv_meta["country"],
        "csv_rank": csv_meta["rank"],
        "csv_main_field": csv_meta["main_field"],
        "csv_subfield": csv_meta["subfield"],
        "csv_selection_reason": csv_meta["selection_reason"],
        "csv_match_status": csv_meta["match_status"],
        "csv_match_score": csv_meta["match_score"],
        # ── OpenAlex identifiers ─────────────────────────────────────────────
        "openalex_id": raw.get("id", "").split("/")[-1],
        "queried_author_id": raw.get("id", "").split("/")[-1],
        "openalex_url": raw.get("id", ""),
        "orcid": raw.get("orcid", ""),
        "id_mag": ids.get("mag", ""),
        "id_scopus": ids.get("scopus", ""),
        "id_twitter": ids.get("twitter", ""),
        "id_wikipedia": ids.get("wikipedia", ""),
        # ── Names ────────────────────────────────────────────────────────────
        "display_name": raw.get("display_name", ""),
        "display_name_alternatives": json.dumps(
            raw.get("display_name_alternatives", [])
        ),
        # ── Metrics ──────────────────────────────────────────────────────────
        "works_count": raw.get("works_count", ""),
        "cited_by_count": raw.get("cited_by_count", ""),
        "h_index": ss.get("h_index", ""),
        "i10_index": ss.get("i10_index", ""),
        "oa_percent": ss.get("oa_percent", ""),
        "2yr_mean_citedness": ss.get("2yr_mean_citedness", ""),
        "2yr_h_index": ss.get("2yr_h_index", ""),
        "2yr_i10_index": ss.get("2yr_i10_index", ""),
        "2yr_works_count": ss.get("2yr_works_count", ""),
        "2yr_cited_by_count": ss.get("2yr_cited_by_count", ""),
        "counts_by_year": json.dumps(raw.get("counts_by_year", [])),
        # ── Affiliation ──────────────────────────────────────────────────────
        "last_known_institution_id": last_insts[0].get("id", "") if last_insts else "",
        "last_known_institution_name": (
            last_insts[0].get("display_name", "") if last_insts else ""
        ),
        "last_known_institution_ror": (
            last_insts[0].get("ror", "") if last_insts else ""
        ),
        "last_known_institution_country": (
            last_insts[0].get("country_code", "") if last_insts else ""
        ),
        "all_last_known_institutions": json.dumps(last_insts),
        "affiliations_history": json.dumps(raw.get("affiliations", [])),
        # ── Topics ───────────────────────────────────────────────────────────
        "top_topic_id": (raw.get("topics") or [{}])[0].get("id", ""),
        "top_topic_name": (raw.get("topics") or [{}])[0].get("display_name", ""),
        "all_topics": json.dumps(raw.get("topics", [])),
        # ── URL ──────────────────────────────────────────────────────────────
        "works_api_url": raw.get("works_api_url", ""),
        # ── Provenance ───────────────────────────────────────────────────────
        "created_date": raw.get("created_date", ""),
        "updated_date": raw.get("updated_date", ""),
    }


# =============================================================================
# STEP 3 — FETCH CORRESPONDING-AUTHOR WORKS IN TIME WINDOW
# =============================================================================


def fetch_corresponding_works(oa_id: str, year_start: int, year_end: int) -> list:
    """
    Fetch all works where `oa_id` is an author, published between year_start
    and year_end (inclusive), using cursor-based pagination.

    Filter breakdown:
      authorships.author.id      → restrict to this specific author
      publication_year            → within the time window
    """
    normalized_id = _normalize_openalex_id(oa_id)
    if not normalized_id:
        return []
    filter_str = (
        f"authorships.author.id:{normalized_id},"
        f"publication_year:{year_start}-{year_end}"
    )

    params = {
        "filter": filter_str,
        "per_page": 200,
        "cursor": "*",
    }

    all_works = []
    page_num = 0
    while True:
        page_num += 1
        data = _get(f"{BASE_URL}/works", params=params)
        results = data.get("results", [])
        all_works.extend(results)

        meta = data.get("meta", {})
        cursor = meta.get("next_cursor")
        total = meta.get("count", 0)
        _log_progress(
            f"    Page {page_num}: {len(results)} works "
            f"({len(all_works)}/{total} total)"
        )

        if not cursor or not results:
            break
        params["cursor"] = cursor

    return all_works


def flatten_work(raw: dict, queried_author_id: str) -> dict:
    """
    Flatten a raw OpenAlex Work object into a single CSV row.
    Adds focal-author-specific authorship columns.
    """
    abstract = reconstruct_abstract(raw.get("abstract_inverted_index") or {})

    pl = raw.get("primary_location") or {}
    src = pl.get("source") or {}
    oa = raw.get("open_access") or {}
    pt = raw.get("primary_topic") or {}
    pt_sf = pt.get("subfield") or {}
    pt_f = pt.get("field") or {}
    pt_d = pt.get("domain") or {}
    cnp = raw.get("citation_normalized_percentile") or {}
    ids = raw.get("ids") or {}

    # Find focal author's authorship entry (guard against None author objects)
    target_auth = {}
    target_id = _normalize_openalex_id(queried_author_id)
    for a in raw.get("authorships") or []:
        author_obj = a.get("author") or {}
        author_id = _normalize_openalex_id(author_obj.get("id"))
        if author_id and author_id == target_id:
            target_auth = a
            break

    # Normalize corresponding flag for strict downstream filtering
    queried_is_corresponding = bool(target_auth.get("is_corresponding"))

    return {
        # ── Identifiers ──────────────────────────────────────────────────────
        "openalex_id": raw.get("id", "").split("/")[-1],
        "openalex_url": raw.get("id", ""),
        "doi": raw.get("doi", ""),
        # ── Publication metadata ─────────────────────────────────────────────
        "title": raw.get("title", ""),
        "publication_year": raw.get("publication_year", ""),
        "publication_date": raw.get("publication_date", ""),
        "type": raw.get("type", ""),
        # ── Citation metrics ─────────────────────────────────────────────────
        "cited_by_count": raw.get("cited_by_count", ""),
        "fwci": raw.get("fwci", ""),
        "citation_percentile_value": cnp.get("value", ""),
        "cited_by_api_url": raw.get("cited_by_api_url", ""),
        # ── Authorship summary ───────────────────────────────────────────────
        "authors_count": raw.get("authors_count", len(raw.get("authorships") or [])),
        "countries_distinct_count": raw.get("countries_distinct_count", ""),
        "institutions_distinct_count": raw.get("institutions_distinct_count", ""),
        "corresponding_author_ids": json.dumps(raw.get("corresponding_author_ids", [])),
        "corresponding_institution_ids": json.dumps(
            raw.get("corresponding_institution_ids", [])
        ),
        # ── Focal author's authorship ────────────────────────────────────────
        "queried_author_id": target_id,
        "queried_author_position": target_auth.get("author_position", ""),
        "queried_author_is_corresponding": queried_is_corresponding,
        "queried_author_raw_name": target_auth.get("raw_author_name", ""),
        "queried_author_raw_affiliation": json.dumps(
            target_auth.get("raw_affiliation_strings", [])
        ),
        # ── Open Access ──────────────────────────────────────────────────────
        "is_oa": oa.get("is_oa", ""),
        "oa_status": oa.get("oa_status", ""),
        # ── Source (journal) ─────────────────────────────────────────────────
        "source_id": src.get("id", "").split("/")[-1] if src.get("id") else "",
        "source_display_name": src.get("display_name", ""),
        "source_issn_l": src.get("issn_l", ""),
        "source_issn": json.dumps(src.get("issn", [])),
        "source_type": src.get("type", ""),
        "source_is_oa": src.get("is_oa", ""),
        "source_host_org_name": src.get("host_organization_name", ""),
        # ── APC ──────────────────────────────────────────────────────────────
        "apc_list_value_usd": (raw.get("apc_list") or {}).get("value_usd", ""),
        "apc_paid_value_usd": (raw.get("apc_paid") or {}).get("value_usd", ""),
        # ── Topics ───────────────────────────────────────────────────────────
        "primary_topic_id": pt.get("id", "").split("/")[-1] if pt.get("id") else "",
        "primary_topic_name": pt.get("display_name", ""),
        "primary_topic_score": pt.get("score", ""),
        "primary_subfield_id": (
            pt_sf.get("id", "").split("/")[-1] if pt_sf.get("id") else ""
        ),
        "primary_subfield_name": pt_sf.get("display_name", ""),
        "primary_field_id": pt_f.get("id", "").split("/")[-1] if pt_f.get("id") else "",
        "primary_field_name": pt_f.get("display_name", ""),
        "all_topics": json.dumps(raw.get("topics", [])),
        "keywords": json.dumps(raw.get("keywords", [])),
        "sustainable_development_goals": json.dumps(
            raw.get("sustainable_development_goals", [])
        ),
        # ── References / related ─────────────────────────────────────────────
        "referenced_works_count": raw.get("referenced_works_count", ""),
        "referenced_works": json.dumps(raw.get("referenced_works", [])),
        "related_works": json.dumps(raw.get("related_works", [])),
    }


# =============================================================================
# STEP 4 — FETCH SOURCE (JOURNAL) METADATA
# =============================================================================


def fetch_source_metadata(source_id: str) -> dict:
    """Fetch the full Source object from OpenAlex."""
    return _get(f"{BASE_URL}/sources/{source_id}")


def flatten_source(raw: dict) -> dict:
    """Flatten a raw OpenAlex Source object into a single CSV row."""
    ss = raw.get("summary_stats") or {}
    ids = raw.get("ids") or {}
    return {
        "openalex_id": raw.get("id", "").split("/")[-1],
        "openalex_url": raw.get("id", ""),
        "issn_l": raw.get("issn_l", ""),
        "issn": json.dumps(raw.get("issn", [])),
        "display_name": raw.get("display_name", ""),
        "abbreviated_title": raw.get("abbreviated_title", ""),
        "alternate_titles": json.dumps(raw.get("alternate_titles", [])),
        "type": raw.get("type", ""),
        "is_oa": raw.get("is_oa", ""),
        "is_in_doaj": raw.get("is_in_doaj", ""),
        "is_core": raw.get("is_core", ""),
        "is_indexed_in_scopus": raw.get("is_indexed_in_scopus", ""),
        "host_organization": raw.get("host_organization", ""),
        "host_organization_name": raw.get("host_organization_name", ""),
        "host_organization_lineage_names": json.dumps(
            raw.get("host_organization_lineage_names", [])
        ),
        "societies": json.dumps(raw.get("societies", [])),
        "apc_prices": json.dumps(raw.get("apc_prices", [])),
        "apc_usd": raw.get("apc_usd", ""),
        "works_count": raw.get("works_count", ""),
        "cited_by_count": raw.get("cited_by_count", ""),
        "h_index": ss.get("h_index", ""),
        "i10_index": ss.get("i10_index", ""),
        "oa_percent": ss.get("oa_percent", ""),
        "2yr_mean_citedness": ss.get("2yr_mean_citedness", ""),
        "2yr_h_index": ss.get("2yr_h_index", ""),
        "counts_by_year": json.dumps(raw.get("counts_by_year", [])),
        "topics": json.dumps(raw.get("topics", [])),
        "id_mag": ids.get("mag", ""),
        "id_wikidata": ids.get("wikidata", ""),
        "id_fatcat": ids.get("fatcat", ""),
        "homepage_url": raw.get("homepage_url", ""),
        "works_api_url": raw.get("works_api_url", ""),
        "created_date": raw.get("created_date", ""),
        "updated_date": raw.get("updated_date", ""),
    }


# =============================================================================
# CSV & DOCUMENTATION HELPERS
# =============================================================================


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        logging.warning(f"No rows to write → {path}")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    _log_progress(f"  ✓ {len(rows):,} rows → {path.name}")


def write_field_reference(path: Path) -> None:
    """Write a CSV documenting every field across all three entity types."""
    rows = []
    for entity, fields in [
        ("Work", WORK_FIELDS),
        ("Author", AUTHOR_FIELDS),
        ("Source", SOURCE_FIELDS),
    ]:
        for field, description in fields.items():
            rows.append({"entity": entity, "field": field, "description": description})
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["entity", "field", "description"])
        writer.writeheader()
        writer.writerows(rows)
    _log_progress(f"  ✓ {len(rows)} field definitions → {path.name}")


# =============================================================================
# MAIN PIPELINE
# =============================================================================


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                (
                    OUTPUT_DIR / "collection.log"
                    if OUTPUT_DIR.exists()
                    else "collection.log"
                ),
                encoding="utf-8",
            ),
        ],
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Re-attach file handler now that OUTPUT_DIR exists
    log_path = OUTPUT_DIR / "collection.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(fh)

    _log_progress("=" * 70)
    _log_progress("OpenAlex Agriculture & Agronomy — Data Collection")
    _log_progress(f"Time window   : {YEAR_START}–{YEAR_END}")
    _log_progress("Filter        : publication year only")
    _log_progress(f"Input CSV     : {INPUT_CSV}")
    _log_progress(f"Output dir    : {OUTPUT_DIR.resolve()}")
    _log_progress("=" * 70)

    # ── STEP 1: Load authors ──────────────────────────────────────────────────
    _log_progress("\n[STEP 1] Loading authors from CSV …")
    authors = load_authors(INPUT_CSV)

    # ── STEP 2: Fetch author metadata ─────────────────────────────────────────
    _log_progress(f"\n[STEP 2] Fetching author metadata ({len(authors)} authors) …")
    author_rows = []
    for a in authors:
        _log_progress(f"  [{a['position']:>2}] {a['name']} ({a['openalex_id']})")
        try:
            raw = fetch_author_metadata(a["openalex_id"])
            author_rows.append(flatten_author(raw, a))
        except Exception as exc:
            logging.error(f"  Failed: {exc}")

    write_csv(OUTPUT_DIR / "authors.csv", author_rows)

    # ── STEP 3: Fetch works in time window ─────────────────────────────────────
    _log_progress(
        f"\n[STEP 3] Fetching works "
        f"({YEAR_START}–{YEAR_END}) …"
    )
    all_work_rows = []
    all_source_ids = set()
    total_raw_works = 0
    total_corresponding_works = 0

    for a in authors:
        _log_progress(f"  [{a['position']:>2}] {a['name']} ({a['openalex_id']})")
        try:
            raw_works = fetch_corresponding_works(
                a["openalex_id"], YEAR_START, YEAR_END
            )
            _log_progress(f"    → {len(raw_works)} works retrieved")
            total_raw_works += len(raw_works)

            corresponding_for_author = 0

            for raw_work in raw_works:
                flat = flatten_work(raw_work, a["openalex_id"])
                if flat.get("queried_author_is_corresponding"):
                    corresponding_for_author += 1
                all_work_rows.append(flat)
                if flat.get("source_id"):
                    all_source_ids.add(flat["source_id"])

            total_corresponding_works += corresponding_for_author
            logging.info(
                f"    Corresponding flag: {corresponding_for_author} of {len(raw_works)}"
            )

        except Exception as exc:
            logging.error(f"  Failed fetching works: {exc}")

    write_csv(OUTPUT_DIR / "works.csv", all_work_rows)
    logging.info(
        f"Overall corresponding flag: {total_corresponding_works:,} of {total_raw_works:,}"
    )
    _log_progress(f"  Total works : {len(all_work_rows):,}")
    _log_progress(f"  Unique sources found: {len(all_source_ids)}")

    # ── STEP 4: Fetch source metadata ─────────────────────────────────────────
    _log_progress(
        f"\n[STEP 4] Fetching source/journal metadata "
        f"({len(all_source_ids)} unique sources) …"
    )
    source_rows = []
    for i, sid in enumerate(sorted(all_source_ids), 1):
        _log_progress(f"  [{i}/{len(all_source_ids)}] {sid}")
        try:
            raw_src = fetch_source_metadata(sid)
            source_rows.append(flatten_source(raw_src))
        except Exception as exc:
            logging.warning(f"  Could not fetch source {sid}: {exc}")

    write_csv(OUTPUT_DIR / "sources.csv", source_rows)

    # ── STEP 5: Write field reference ──────────────────────────────────────────
    _log_progress("\n[STEP 5] Writing field reference …")
    write_field_reference(OUTPUT_DIR / "field_reference.csv")
 
    # ── Summary ────────────────────────────────────────────────────────────────
    if QUIET_MODE:
        logging.info(f"Total works retrieved: {len(all_work_rows):,}")
    else:
        logging.info("\n" + "=" * 70)
        logging.info("COLLECTION COMPLETE")
        logging.info(f"  authors.csv      : {len(author_rows)} rows")
        logging.info(
            f"  works.csv        : {len(all_work_rows):,} rows  "
            f"({YEAR_START}–{YEAR_END})"
        )
        logging.info(f"  sources.csv      : {len(source_rows)} rows")
        logging.info(f"  field_reference  : documented")
        logging.info(f"  collection.log   : full run log")
        logging.info("=" * 70)


if __name__ == "__main__":
    main()
