from pathlib import Path

from pyalex import Works, Authors, Sources
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from collections import defaultdict
import time
import warnings
from scipy import stats
from scipy.stats import gaussian_kde

warnings.filterwarnings("ignore")
from scipy.stats import chi2_contingency

# ── Style ──────────────────────────────────────────────────────────────────────
sns.set_theme(style="whitegrid", palette="tab10")
plt.rcParams.update({"figure.dpi": 130, "figure.figsize": (10, 5)})

# ── Topic level for analysis ───────────────────────────────────────────────────
# Options: "topic_domain", "topic_field", "topic_subfield", "primary_topic"
TOPIC_COL = "primary_topic"
TOPIC_LEVEL_LABEL = TOPIC_COL.replace("topic_", "").replace("_", " ").capitalize()
ACTUAL_Y= pd.Timestamp.now().year
MIN_SHARED_PAPERS = 30





# ── Target_author authors of interest ────────────────────────────────────────────────
author_ids = {
    "https://openalex.org/A5064124035": "Ciampitti",
    "https://openalex.org/A5074248754": "Basso",
    "https://openalex.org/A5053935458": "Kaiyu",
    "https://openalex.org/A5005128316": "Grassini",
    "https://openalex.org/A5010412338": "Archontoulis",
    "https://openalex.org/A5073947803": "Castellano",
    "https://openalex.org/A5026642372": "Lobell",
    "https://openalex.org/A5073721257": "Peng",
    "https://openalex.org/A5050045466": "Vara Prasad",
    "https://openalex.org/A5072153127": "Rattalino",
    "https://openalex.org/A5047677277": "Hoogenboom",
    "https://openalex.org/A5089812471": "Messina",
}
coauthors_ids = {}


def get_works(author_ids_dict, from_date="2018-01-01", to_date="2025-12-31"):
    """Fetch all works for a dict of {openalex_id: name}, enriching each work
    with queried_author, queried_author_id, author_position, and
    is_corresponding_author. If date filtering returns zero results, fall back
    to a publication_year range filter."""
    works_list = []
    author_stats = {}
    for aid, name in author_ids_dict.items():
        print(f"  Fetching: {name} …", end=" ")
        cursor = "*"
        n = 0
        try:
            year_range = f"{int(str(from_date)[:4])}-{int(str(to_date)[:4])}"
        except (TypeError, ValueError):
            year_range = None
        use_year_range = False
        if aid not in author_stats:
            try:
                author = Authors()[aid]
                summary = author.get("summary_stats") or {}
                author_stats[aid] = {
                    "h_index": summary.get("h_index"),
                    "i10_index": summary.get("i10_index"),
                }
            except Exception:
                author_stats[aid] = {"h_index": None, "i10_index": None}
        while cursor:
            if use_year_range and year_range:
                filters = {
                    "author.id": aid,
                    "publication_year": year_range,
                }
            else:
                filters = {
                    "author.id": aid,
                    "from_publication_date": from_date,
                    "to_publication_date": to_date,
                }
            results = Works().filter(**filters).get(per_page=200, cursor=cursor)
            if (not use_year_range) and year_range and results.meta.get("count", 0) == 0:
                # Fallback to year-range filter when date filter yields nothing.
                use_year_range = True
                cursor = "*"
                continue
            for work in results:
                author_position, is_corresponding = None, False
                for auth in work.get("authorships", []):
                    if auth.get("author", {}).get("id") == aid:
                        author_position = auth.get("author_position")
                        is_corresponding = auth.get("is_corresponding", False)
                        break
                work["queried_author"] = name
                work["queried_author_id"] = aid
                work["queried_author_h_index"] = author_stats[aid].get("h_index")
                work["queried_author_i10_index"] = author_stats[aid].get("i10_index")
                work["author_position"] = author_position
                work["is_corresponding_author"] = is_corresponding
                works_list.append(work)
                n += 1
            next_cursor = results.meta.get("next_cursor")
            cursor = next_cursor if next_cursor != cursor else None
            time.sleep(0.5)
    print(f"\nTotal works fetched: {len(works_list)}")
    return works_list

def get_journal_impact_factors(works_list):
    """
    Extract unique journals from a works_list (output of get_works) and
    fetch their 2yr_mean_citedness (impact factor equivalent) from OpenAlex.

    Returns a DataFrame with columns: journal_name, impact_factor
    """
    # Extract unique source IDs from works
    source_ids = {}
    for work in works_list:
        loc = work.get("primary_location") or {}
        source = loc.get("source") or {}
        sid = source.get("id")
        sname = source.get("display_name")
        if sid and sname:
            source_ids[sid] = sname  # deduplicate by ID

    print(f"  Found {len(source_ids)} unique journals. Fetching IFs…")

    rows = []
    for sid, fallback_name in source_ids.items():
        try:
            source_obj = Sources()[sid]
            name = source_obj.get("display_name") or fallback_name
            stats = source_obj.get("summary_stats") or {}
            impact_factor = stats.get("2yr_mean_citedness")
            rows.append({"journal_name": name, "impact_factor": impact_factor})
            time.sleep(0.3)
        except Exception as e:
            print(f"  Warning: could not fetch {sid}: {e}")
            rows.append({"journal_name": fallback_name, "impact_factor": None})

    df = pd.DataFrame(rows).sort_values("impact_factor", ascending=False).reset_index(drop=True)
    return df

def get_prolific_coauthors(
    Target_author_works,
    author_ids,
    coauthors_ids,
    min_shared_papers: int = MIN_SHARED_PAPERS,
    top_n: int | None = None,
 ):
    """
    Return {author_id: name} for co-authors who have collaborated with the
    target-author set on at least `min_shared_papers` DISTINCT papers.

    - Shared-paper count is based on distinct OpenAlex work IDs, so duplicates
      in `Target_author_works` (from querying multiple target authors) do not
      inflate counts.
    - Excludes anyone already in `author_ids` or `coauthors_ids`.
    - Updates both `author_ids` and `coauthors_ids` in-place with the new entries.
    - If `top_n` is provided, only the top_n by shared-paper count are returned;
      otherwise, all eligible coauthors are returned.
    """
    already_tracked = set(author_ids.keys()) | set(coauthors_ids.keys())

    shared_papers_by_aid = defaultdict(set)  # aid -> {work_id, ...}
    name_by_aid = {}
    for work in Target_author_works:
        work_id = work.get("id")
        if not work_id:
            continue
        qid = work.get("queried_author_id")
        for auth in work.get("authorships", []):
            author = auth.get("author") or {}
            aid = author.get("id")
            name = author.get("display_name")
            # Skip if same as the queried author, already tracked, or missing id
            if not aid or aid == qid or aid in already_tracked:
                continue
            shared_papers_by_aid[aid].add(work_id)
            if aid not in name_by_aid and name:
                name_by_aid[aid] = name

    eligible = [
        (aid, name_by_aid.get(aid), len(work_ids))
        for aid, work_ids in shared_papers_by_aid.items()
        if len(work_ids) >= min_shared_papers
    ]
    eligible.sort(key=lambda x: (x[2], x[1] or ""), reverse=True)

    if top_n is not None:
        eligible = eligible[:top_n]

    new_coauthors = {}
    for aid, name, n_shared in eligible:
        display_name = name or aid
        print(f"  {display_name}: {n_shared} shared papers")
        new_coauthors[aid] = display_name

    print(f"Selected coauthors: {len(new_coauthors)} (min_shared_papers={min_shared_papers})")

    # Add to both lists
    coauthors_ids.update(new_coauthors)
    author_ids.update(new_coauthors)

    return new_coauthors
def get_publications_table(works_list):
    """
    Flatten raw OpenAlex works into a tidy DataFrame.
    Extracts only fields present in needed_cols, keeping display names
    and counts while dropping IDs, URLs, and scores.
    """
    rows = []
    for work in works_list:
        pub_year = work.get("publication_year")

        # ── counts_by_year → year-offset citation columns ──────────────────
        citation_counts = {}
        for entry in work.get("counts_by_year", []):
            year  = entry.get("year")
            count = entry.get("cited_by_count", 0)
            if year and pub_year and year >= pub_year:
                citation_counts[f"citations_year_{year - pub_year}"] = count

        # ── authorships → team size ────────────────────────────────────────
        n_authors = len(work.get("authorships", []))

        # ── topics → hierarchy ─────────────────────────────────────────────
        topics = work.get("topics") or []
        primary_topic  = topics[0] if topics else {}
        topic_name     = primary_topic.get("display_name")
        topic_subfield = (primary_topic.get("subfield") or {}).get("display_name")
        topic_field    = (primary_topic.get("field")    or {}).get("display_name")
        topic_domain   = (primary_topic.get("domain")   or {}).get("display_name")

        # ── concepts → names only ─────────────────────────────────────────
        concepts = sorted(
            work.get("concepts") or [],
            key=lambda c: c.get("score", 0), reverse=True
        )
        concept_names = [c["display_name"] for c in concepts[:5] if c.get("display_name")]

        # ── keywords ──────────────────────────────────────────────────────
        keyword_names = [
            kw["display_name"]
            for kw in (work.get("keywords") or [])
            if kw.get("display_name")
        ]

        # ── SDGs ──────────────────────────────────────────────────────────
        sdg_names = [
            sdg["display_name"]
            for sdg in (work.get("sustainable_development_goals") or [])
            if sdg.get("display_name")
        ]

        # ── references ────────────────────────────────────────────────────
        n_references = len(work.get("referenced_works") or [])

        # ── percentiles ───────────────────────────────────────────────────
        pct_year       = work.get("cited_by_percentile_year") or {}
        percentile_min = pct_year.get("min")
        percentile_max = pct_year.get("max")

        norm_pct                 = work.get("citation_normalized_percentile") or {}
        citation_norm_percentile = norm_pct.get("value")

       
        # ── journal (FIX robusto) ─────────────────────────────────────────
        primary_location = work.get("primary_location") or {}
        source = primary_location.get("source") or {}

        journal_display_name = source.get("display_name")
        journal_publisher = source.get("host_organization_name")

        # ── open_access ───────────────────────────────────────────────────
        oa        = work.get("open_access") or {}
        is_oa     = oa.get("is_oa", False)
        oa_status = oa.get("oa_status")

        rows.append({
            "article_id":               work.get("id"),
            "title":                    work.get("title", ""),
            "publication_date":         work.get("publication_date"),
            "publication_year":         pub_year,
            "type":                     work.get("type"),
            "author_type":              work.get("author_type"),
            "queried_author":           work.get("queried_author"),
            "general_h_index":   work.get("queried_author_h_index"),
            "general_i10_index": work.get("queried_author_i10_index"),
            "author_position":          work.get("author_position"),
            "is_corresponding_author":  work.get("is_corresponding_author", False),
            "n_authors":                n_authors,
            "journal_display_name":     journal_display_name,
            "journal_publisher":        journal_publisher,
            "is_oa":                    is_oa,
            "oa_status":                oa_status,
            "primary_topic":            topic_name,
            "topic_subfield":           topic_subfield,
            "topic_field":              topic_field,
            "topic_domain":             topic_domain,
            "top_concepts":             concept_names,
            "keywords":                 keyword_names,
            "sdgs":                     sdg_names,
            "total_citations":          work.get("cited_by_count", 0),
            "percentile_min":           percentile_min,
            "percentile_max":           percentile_max,
            "citation_norm_percentile": citation_norm_percentile,
            "n_references":             n_references,
            **citation_counts,
        })

    df = pd.DataFrame(rows)
    df["total_citations"] = df["total_citations"].fillna(0)
    # Total citations by author across this table
    df["author_total_citations"] = df.groupby("queried_author")["total_citations"].transform("sum")
    df.sort_values("total_citations", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def load_journals_of_interest(path: str | Path) -> list[str]:
    with open(path, "r", encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]

def prepare_output_tables(
    target_author_works,
    coauthors_works,
    journals_of_interest,
    target_author_works_2015=None,
):
    for work in target_author_works:
        work["author_type"] = "Target_author"
    for work in coauthors_works:
        work["author_type"] = "Collaborator"

    target_df = get_publications_table(target_author_works)
    coauthors_df = get_publications_table(coauthors_works)
    all_works = target_author_works + coauthors_works
    all_df = get_publications_table(all_works)

    filtered_target_df = target_df[target_df["journal_display_name"].isin(journals_of_interest)].copy()
    filtered_all_df = all_df[all_df["journal_display_name"].isin(journals_of_interest)].copy()

    filtered_target_df_corr = filtered_target_df[filtered_target_df["is_corresponding_author"]].copy()
    filtered_all_df_corr = filtered_all_df[filtered_all_df["is_corresponding_author"]].copy()

    ta_ten_corr = pd.DataFrame()
    if target_author_works_2015 is not None:
        ta_ten = get_publications_table(target_author_works_2015)
        ta_ten = ta_ten[ta_ten["journal_display_name"].isin(journals_of_interest)].copy()
        ta_ten_corr = ta_ten[ta_ten["is_corresponding_author"]].copy()

    return {
        "Target_authors_df": target_df,
        "coauthors_df": coauthors_df,
        "all_df": all_df,
        "filtered_TargetA_df": filtered_target_df,
        "filtered_TargetA_df_corr": filtered_target_df_corr,
        "filtered_all_df": filtered_all_df,
        "filtered_all_df_corr": filtered_all_df_corr,
        "ta_ten_corr": ta_ten_corr,
    }


def save_output_tables(tables, output_dir: str | Path):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    file_map = {
        "filtered_TargetA_df": "filtered_TargetA_df.csv",
        "filtered_TargetA_df_corr": "filtered_TargetA_df_corr.csv",
        "filtered_all_df": "filtered_all_df.csv",
        "filtered_all_df_corr": "filtered_all_df_corr.csv",
        "ta_ten_corr": "ta_ten_corr.csv",
        "JOURNAL_IF_2025": "JOURNAL_IF_2025.csv",
    }

    for key, filename in file_map.items():
        df = tables.get(key)
        if df is not None and not df.empty:
            df.to_csv(output_dir / filename, index=False)


def main():
    project_root = Path(__file__).resolve().parents[1]
    data_dir = project_root / "data"
    journals_path = project_root / "journals_of_interest.txt"

    print("Fetching Target_author authors")
    target_author_works = get_works(author_ids)
    journal_if_2025 = get_journal_impact_factors(target_author_works)
    print("\nJournal impact factors (2025):")
    print(journal_if_2025.head(10).to_string(index=False))

    target_author_works_2015 = get_works(author_ids, from_date="2015-01-01", to_date="2025-12-31")
    print(f"\nIdentifying co-authors with more than {MIN_SHARED_PAPERS} papers as coauthors")
    get_prolific_coauthors(
        target_author_works,
        author_ids,
        coauthors_ids,
        min_shared_papers=MIN_SHARED_PAPERS,
        top_n=None,
    )
    coauthors_works = get_works(coauthors_ids)

    journals_of_interest = load_journals_of_interest(journals_path)
    tables = prepare_output_tables(
        target_author_works,
        coauthors_works,
        journals_of_interest,
        target_author_works_2015=target_author_works_2015,
    )
    tables["JOURNAL_IF_2025"] = journal_if_2025

    save_output_tables(tables, data_dir)

    print(f"\n3 different tables:")
    print(f"Target_author works   : {tables['Target_authors_df'].shape[0]}")
    print(f"Coauthor works  : {tables['coauthors_df'].shape[0]}")
    print(f"Total combined  : {tables['all_df'].shape[0]}")


if __name__ == "__main__":
    main()