import sys
from numpy import nan
from pyalex import Works, Authors
import pandas as pd
import spacy
from collections import Counter, defaultdict
import time
from datetime import datetime
from plotnine import *
from plotnine.data import *
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation
import gensim
from gensim import corpora
from gensim.models import LdaModel
import numpy as np

nlp = spacy.load("en_core_web_sm")  # English load
# sys.path.append("/usr/local/repositories/")
# from ds_utils.plotting import *
# from ds_utils.gsheets import *

# --------------------------------------------------------------
# Get connector
# gsheet_obj = None
# gsheet_obj = get_gsheets_connector()
sheet_id = "1_GBfO9hcQofCT7OtcuREgiMgQ-2v0YjDA9CekdYD_lw"

# Find Authors of Interest ------------------------------------------------------------------
mandrini = Authors().search("Mandrini").get()
author_ls = Authors().search("Ciampitti").get()
author_ls = Authors().search("Basso").get()
author_ls = Authors().search("Kaiyu Guan").get()
author_ls = Authors().search("Archontoulis").get()
author_ls = Authors().search("Grassini").get()
author_ls = Authors().search("Lobell").get()
author_ls = Authors().search("Castellano").get()

if False:
    # Print name and OpenAlex ID for each author
    for author in author_ls:
        print(f"{author['display_name']} | {author['id']}")

    # Filter papers where authors are listed
    papers = (
        Works()
        .filter(**{"author.id": "https://openalex.org/A5073947803"})
        .get(per_page=200)
    )

    for paper in papers:
        print(paper["title"], "|", paper["publication_year"])


# Get All Works by These Authors ------------------------------------------------------------------
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
}
coauthors_ids = {}

"""
Alerts for germanmandrini@gmail.com
Alejandro Plastina - new articles	All results
Kenneth Cassman - new articles	All results
Kaiyu Guan - new articles	All results
New citations to my articles	All results
Michael J. Castellano - new articles	All results
Andrew John Margenot - new articles	All results
John M. Antle - new articles	All results
Taro Mieno - new articles	All results
PJ Thorburn - new articles	All results
John Shanahan - new articles	All results
David Lobell - new articles	All results
Dr. Emily K. Burchfield - new articles	All results
Nicole Olynk Widmar - new articles	All results
Gary Schnitkey - new articles	All results
Juan Ignacio Rattalino Edreira - new articles	All results
Ben Gramig - new articles	All results
Fernando E. Miguez - new articles	All results
Xin Zhang - new articles	All results
Bert Federico Esteban - new articles	All results
Dr Jonathan Jesus Ojeda - new articles	All results
Sotirios V. Archontoulis - new articles	All results
Nicolas Martin - new articles	All results
Sotirios V. Archontoulis - new related research	All results
Alert for a profile that is no longer public. Alert is inactive.	All results
Nigel Key - new articles	All results
Zhou Zhang - new articles	All results
Shalamar Armstrong - new articles	All results
Bruno Basso - new articles	All results
Recommended articles	All results
David Kanter - new articles	All results
M Francesca Cotrufo - new articles	All results
Cameron M. Pittelkow - new articles	All results
German Bollero - new articles	All results
Laila A. Puntel - new articles	All results
Christoph Müller - new articles	All results
Patricio Grassini - new articles	All results
Rafael A Martinez-Feria - new articles	All results

"""


def get_works(author_ids):
    all_works = []

    for aid, name in author_ids.items():
        print(f"Fetching works for author: {name}")
        cursor = "*"

        while cursor:
            results = (
                Works()
                .filter(
                    **{
                        "author.id": aid,
                        "from_publication_date": "2020-01-01",
                        "to_publication_date": "2025-12-31",
                    }
                )
                .get(per_page=200, cursor=cursor)
            )

            for work in results:
                # Find this author's position in the paper
                author_position = None
                for auth in work.get("authorships", []):
                    if auth.get("author", {}).get("id") == aid:
                        author_position = auth.get("author_position")
                        is_corresponding = auth.get("is_corresponding", False)
                        break

                # Enrich the work with additional info
                work["queried_author"] = name
                work["queried_author_id"] = aid
                work["author_position"] = author_position
                work["is_corresponding_author"] = is_corresponding

                all_works.append(work)

            # Pagination
            next_cursor = results.meta.get("next_cursor")
            if next_cursor == cursor:
                break
            cursor = next_cursor

            time.sleep(1)

    print(f"Total works retrieved: {len(all_works)}")

    work = all_works[0]
    work.keys()
    return all_works


all_works = get_works(author_ids)


# Select prolific co-authors to add to author_ids
def get_prolific_coauthors(all_works):
    coauthor_counter = Counter()

    for work in all_works:
        queried_aid = work.get("queried_author_id")
        for auth in work.get("authorships", []):
            author_id = auth.get("author", {}).get("id")
            author_name = auth.get("author", {}).get("display_name")

            # Skip the queried author themselves
            if author_id != queried_aid:
                coauthor_counter[(author_id, author_name)] += 1

    # Get top 20 co-authors by count
    top_coauthors = coauthor_counter.most_common(15)
    coauthors_ids.update({aid: name for (aid, name), count in top_coauthors})
    # Display nicely
    for (aid, name), count in top_coauthors:
        print(f"{name} ({aid}): {count} co-authored papers")


get_prolific_coauthors(all_works)
print(f"Total number of authors in author_ids: {len(author_ids)}")
print(f"Total number of authors in coauthors_ids: {len(coauthors_ids)}")

# Make it into a df ------------------------------------------------------------------


def compute_citations_by_year(cited_by_api, pub_year):
    # Prepare output dict
    citation_counts = {f"citations_{i}yr": 0 for i in range(5)}

    if not cited_by_api or not pub_year:
        return citation_counts

    by_year_data = cited_by_api.get("by_year", [])
    if not by_year_data:
        return citation_counts

    for entry in by_year_data:
        try:
            year = entry.get("year")
            count = entry.get("cited_by_count", 0)
            if year is None or pub_year is None:
                continue
            offset = year - pub_year
            if 0 <= offset <= 4:
                citation_counts[f"citations_{offset}yr"] += count
        except Exception as e:
            print(f"Error parsing citation year data: {entry}, error: {e}")
            continue

    return citation_counts


def get_publications_table(all_works):
    # Create list of processed rows
    rows = []

    for work in all_works:
        pub_year = work.get("publication_year")
        # Initialize dictionary for year-offset citation counts
        citation_counts = {}
        for count_entry in work.get("counts_by_year", []):
            year = count_entry.get("year")
            cited_by = count_entry.get("cited_by_count", 0)
            if year and pub_year and year >= pub_year:
                offset = year - pub_year
                citation_counts[f"citations_year_{offset}"] = cited_by

        # Safely extract journal/source info
        primary_location = work.get("primary_location") or {}
        source = primary_location.get("source") or {}

        row = {
            "article_id": work.get("id"),
            "title": work.get("display_name", ""),
            "queried_author": work.get("queried_author"),
            "author_position": work.get("author_position"),
            "is_corresponding_author": work.get("is_corresponding_author", False),
            "publication_year": pub_year,
            "is_published": work.get("author_position"),
            "is_accepted": work.get("is_accepted"),
            "journal_display_name": source.get("display_name"),
            "journal_publisher": source.get("host_organization_name"),
            "total_citations": work.get("cited_by_count", 0),
            **citation_counts,
        }

        rows.append(row)

    # Create DataFrame
    works_df = pd.DataFrame(rows)

    works_df.sort_values(by=["total_citations"], ascending=False, inplace=True)

    return works_df


def clean_and_process_titles(df, text_column):
    with nlp.select_pipes(
        enable=["tok2vec", "tagger", "lemmatizer", "attribute_ruler"]
    ):
        docs = list(nlp.pipe(df[text_column].astype(str).str.lower(), batch_size=100))

    tokenized_docs = []
    for doc in docs:
        # Filter: only alpha, not stop word, not punctuation, length > 2
        tokens = [
            t.lemma_ for t in doc if t.is_alpha and not t.is_stop and len(t.text) > 2
        ]
        tokenized_docs.append(tokens)

    return tokenized_docs


# Define seed topics for agricultural/environmental research
SEED_TOPICS = {
    "crop_yield": [
        "yield",
        "production",
        "productivity",
        "biomass",
        "grain",
        "harvest",
    ],
    "climate": [
        "climate",
        "temperature",
        "precipitation",
        "weather",
        "drought",
        "warming",
    ],
    "soil": ["soil", "nutrient", "nitrogen", "fertilizer", "organic", "carbon"],
    "water": [
        "water",
        "irrigation",
        "rainfall",
        "moisture",
        "drought",
        "evapotranspiration",
    ],
    "crop_management": [
        "management",
        "practice",
        "tillage",
        "rotation",
        "planting",
        "density",
    ],
    "modeling": [
        "model",
        "simulation",
        "prediction",
        "forecast",
        "algorithm",
        "machine",
    ],
    "remote_sensing": ["remote", "sensing", "satellite", "imagery", "spectral", "ndvi"],
    "sustainability": [
        "sustainable",
        "efficiency",
        "environmental",
        "impact",
        "emission",
        "footprint",
    ],
    "genetics": ["genetic", "variety", "cultivar", "breeding", "hybrid", "germplasm"],
    "economics": ["economic", "farmer", "income", "cost", "profit", "market"],
}


def train_gensim_lda_with_seeds(
    tokenized_docs, seed_topics, num_topics=15, passes=15, random_state=42
):
    """
    Train LDA model with Gensim using seed topics for semi-supervised topic modeling
    """
    # Create dictionary and corpus
    dictionary = corpora.Dictionary(tokenized_docs)

    # Filter extremes
    dictionary.filter_extremes(no_below=3, no_above=0.7, keep_n=2000)

    # Create corpus
    corpus = [dictionary.doc2bow(doc) for doc in tokenized_docs]

    print(f"Dictionary size: {len(dictionary)}")
    print(f"Corpus size: {len(corpus)}")

    # Train LDA model
    lda_model = LdaModel(
        corpus=corpus,
        id2word=dictionary,
        num_topics=num_topics,
        random_state=random_state,
        passes=passes,
        alpha="auto",
        eta="auto",
        per_word_topics=True,
    )

    return lda_model, dictionary, corpus


def display_gensim_topics(lda_model, num_words=10, seed_topics=None):
    """
    Display topics with their top words and match to seed topics
    """
    topics = lda_model.show_topics(num_topics=-1, num_words=num_words, formatted=False)

    topic_interpretations = []

    for topic_id, words in topics:
        topic_words = [word for word, prob in words]
        topic_probs = [prob for word, prob in words]

        # print(f"\nTopic {topic_id + 1}:")
        # print(" ".join([f"{word}({prob:.3f})" for word, prob in words]))

        # Match to seed topics
        if seed_topics:
            best_match = None
            best_score = 0

            for seed_name, seed_words in seed_topics.items():
                overlap = len(set(topic_words) & set(seed_words))
                if overlap > best_score:
                    best_score = overlap
                    best_match = seed_name

            if best_match and best_score > 0:
                print(
                    f"→ Likely relates to: {best_match.replace('_', ' ').title()} (overlap: {best_score})"
                )
                topic_interpretations.append(
                    (topic_id, best_match, best_score, topic_words)
                )

        print("-" * 80)

    return topic_interpretations


def get_document_topics(lda_model, corpus, works_df):
    """
    Assign dominant topics to each document
    """
    doc_topics = []

    for idx, doc in enumerate(corpus):
        topics = lda_model.get_document_topics(doc)
        if topics:
            # Get dominant topic
            dominant_topic = max(topics, key=lambda x: x[1])
            doc_topics.append(
                {
                    "doc_idx": idx,
                    "dominant_topic": dominant_topic[0],
                    "topic_prob": dominant_topic[1],
                }
            )
        else:
            doc_topics.append(
                {"doc_idx": idx, "dominant_topic": None, "topic_prob": 0.0}
            )

    topic_df = pd.DataFrame(doc_topics)
    works_with_topics = works_df.copy()
    works_with_topics["dominant_topic"] = topic_df["dominant_topic"]
    works_with_topics["topic_probability"] = topic_df["topic_prob"]

    return works_with_topics


# Main analysis workflow
print("Building publications dataframe...")
works_df = get_publications_table(all_works)

print("\nCleaning and tokenizing paper titles...")
tokenized_titles = clean_and_process_titles(works_df, "title")

print("\nTraining Gensim LDA model with seed topics...")
lda_model, dictionary, corpus = train_gensim_lda_with_seeds(
    tokenized_titles, SEED_TOPICS, num_topics=15, passes=15
)

print("\n" + "=" * 80)
print("DISCOVERED TOPICS IN AGRICULTURAL RESEARCH")
print("=" * 80)

topic_interpretations = display_gensim_topics(
    lda_model, num_words=10, seed_topics=SEED_TOPICS
)

print("\nAssigning topics to documents...")
works_with_topics = get_document_topics(lda_model, corpus, works_df)

# Summary by topic
print("\n" + "=" * 80)
print("TOPIC DISTRIBUTION ACROSS PAPERS")
print("=" * 80)
topic_summary = (
    works_with_topics.groupby("dominant_topic")
    .agg(
        num_papers=("article_id", "count"),
        avg_citations=("total_citations", "mean"),
        total_citations=("total_citations", "sum"),
    )
    .sort_values("num_papers", ascending=False)
)

print(topic_summary)

# Top cited papers by topic
print("\n" + "=" * 80)
print("TOP 3 MOST CITED PAPERS PER TOPIC")
print("=" * 80)

for topic_id in works_with_topics["dominant_topic"].dropna().unique():
    topic_papers = works_with_topics[works_with_topics["dominant_topic"] == topic_id]
    top_papers = topic_papers.nlargest(3, "total_citations")

    print(f"\nTopic {int(topic_id) + 1}:")
    for idx, row in top_papers.iterrows():
        print(
            f"  - {row['title'][:80]}... ({row['total_citations']} citations, {row['publication_year']})"
        )
# Topic analysis by author
print("\n" + "=" * 80)
print("TOPIC DISTRIBUTION BY AUTHOR")
print("=" * 80)

author_topics = (
    works_with_topics.groupby(["queried_author", "dominant_topic"])
    .size()
    .reset_index(name="count")
)
author_topics_pivot = author_topics.pivot(
    index="queried_author", columns="dominant_topic", values="count"
).fillna(0)

print("\nNumber of papers per topic for each author:")
print(author_topics_pivot.astype(int))

# Most common topic per author
print("\n" + "=" * 80)
print("PRIMARY RESEARCH FOCUS PER AUTHOR")
print("=" * 80)

for author in works_with_topics["queried_author"].unique():
    author_data = works_with_topics[works_with_topics["queried_author"] == author]
    if author_data["dominant_topic"].notna().any():
        top_topic = (
            author_data["dominant_topic"].mode().values[0]
            if len(author_data) > 0
            else None
        )
        if top_topic is not None:
            topic_words = lda_model.show_topics(
                num_topics=-1, num_words=5, formatted=False
            )[int(top_topic)][1]
            print(f"\n{author}: Topic {int(top_topic)+1}")
            print(f"  Keywords: {', '.join([word for word, prob in topic_words])}")
            print(
                f"  Papers: {len(author_data)}, Avg citations: {author_data['total_citations'].mean():.1f}"
            )

# Compare Authors  ------------------------------------------------------------------


def plot_pub_and_citations_per_year_per_author():
    summary = (
        works_df.groupby(["queried_author", "publication_year"])
        .agg(
            total_works=("article_id", "count"),
            corresponding_author_works=("is_corresponding_author", "sum"),
            total_citations=("total_citations", "sum"),
            corresponding_author_citations=(
                "total_citations",
                lambda x: x[works_df.loc[x.index, "is_corresponding_author"]].sum(),
            ),
        )
        .reset_index()
    )

    summary_long = pd.melt(
        summary,
        id_vars=["queried_author", "publication_year"],
        value_vars=[
            "total_works",
            "corresponding_author_works",
            "total_citations",
            "corresponding_author_citations",
        ],
        var_name="metric",
        value_name="count",
    )

    # Make metric names prettier
    summary_long["metric"] = summary_long["metric"].replace(
        {
            "total_works": "Total Works",
            "corresponding_author_works": "Corresponding Author Works",
            "total_citations": "Total Citations",
            "corresponding_author_citations": "Corresponding Author Citations",
        }
    )

    timeline_plot = (
        ggplot(
            summary_long, aes(x="publication_year", y="count", color="queried_author")
        )
        + geom_line(size=1.2)
        + geom_point(size=2)
        + facet_wrap("~metric", scales="free_y", ncol=2)
        + labs(
            title="Author Timeline: Publications and Citations (2020–2025)",
            x="Publication Year",
            y="Count",
            color="Author",
        )
        # + theme_minimal()
        + theme(
            figure_size=(12, 8),
            subplots_adjust={"hspace": 0.4},
            axis_text_x=element_text(rotation=45, ha="right"),
        )
    )

    timeline_plot


def summarize_by_journal(works_df):
    works_df2 = works_df.sort_values(
        "is_corresponding_author", ascending=False
    ).drop_duplicates(subset=["article_id"], keep="first")

    # Identify and sort citation columns in order of year offset
    citation_cols = sorted(
        [col for col in works_df2.columns if col.startswith("citations_year_")],
        key=lambda x: int(x.split("_")[-1]),
    )

    # Restrict to year offsets 0 to 5 (if present)
    citation_cols = [col for col in citation_cols if int(col.split("_")[-1]) <= 5]

    # Fill missing citation values with 0
    works_df2[citation_cols] = works_df2[citation_cols].fillna(0)

    # Group and aggregate
    summary = (
        works_df2.groupby("journal_display_name")
        .agg(
            total_publications=("article_id", "count"),
            **{col: (col, "sum") for col in citation_cols},
        )
        .reset_index()
        .sort_values(by="total_publications", ascending=False)
    )

    return summary


def summarize_by_journal_avg_citations(works_df, max_year_offset=5):
    # Ensure publication_year is present
    current_year = pd.Timestamp.now().year
    works_df = works_df.copy()
    works_df["age"] = current_year - works_df["publication_year"]

    # Collect relevant citation columns
    citation_cols = [f"citations_year_{i}" for i in range(max_year_offset + 1)]

    # Fill missing citations with 0
    works_df[citation_cols] = works_df[citation_cols].fillna(0)

    # Initialize aggregation dicts
    total_pubs = (
        works_df.groupby("journal_display_name")["article_id"]
        .count()
        .rename("total_publications")
    )

    avg_citation_data = {}
    for i in range(max_year_offset + 1):
        col = f"citations_year_{i}"

        # Only include articles that are old enough for this offset
        eligible = works_df[works_df["age"] >= i]

        # Group and compute average
        avg = eligible.groupby("journal_display_name")[col].mean().rename(f"avg_{col}")
        count = (
            eligible.groupby("journal_display_name")[col]
            .count()
            .rename(f"n_eligible_year_{i}")
        )

        avg_citation_data[f"avg_{col}"] = avg
        avg_citation_data[f"n_eligible_year_{i}"] = count

    # Combine all into one DataFrame
    summary_df = total_pubs.to_frame()

    for df in avg_citation_data.values():
        summary_df = summary_df.join(df, how="left")

    summary_df = summary_df.reset_index().sort_values(
        by="total_publications", ascending=False
    )
    summary_df = summary_df.loc[summary_df["total_publications"] > 10].copy()
    summary_df.sort_values("avg_citations_year_2", ascending=False, inplace=True)
    summary_df.reset_index(drop=True, inplace=True)

    range_id = "journal!A35"  # Tab
    clear_range_id = f"{range_id}:J100"

    # response = pd_to_gsheets(
    #     summary_df,
    #     gsheet_obj,
    #     sheet_id,
    #     range_id,
    #     clear_sheet=True,
    #     clear_range_id=clear_range_id,
    #     chunk_size=3000,
    #     verbose=True,
    # )

    return summary_df


# Check if # of coauthors affects citations
def team_size():
    return None


# Extract Low-Level Concept IDs  ------------------------------------------------------------------
# Initialize accumulators
concept_data = defaultdict(
    lambda: {"name": "", "level": 0, "count": 0, "score_sum": 0.0}
)

# Loop through works and collect concept stats
for work in all_works:
    for concept in work.get("concepts", []):
        if concept["level"] >= 2:
            cid = concept["id"]
            concept_data[cid]["name"] = concept["display_name"]
            concept_data[cid]["level"] = concept["level"]
            concept_data[cid]["count"] += 1
            concept_data[cid]["score_sum"] += concept.get("score", 0.0)

# Convert to pandas DataFrame
concept_df = pd.DataFrame(
    [
        {
            "concept_id": cid,
            "concept_name": data["name"],
            "level": data["level"],
            "count": data["count"],
            "score_sum": data["score_sum"],
        }
        for cid, data in concept_data.items()
    ]
)

concept_df.loc[concept_df["level"] > 2].head(20)

# Optional: sort by count or score
concept_df = concept_df.sort_values(by="count", ascending=False).reset_index(drop=True)

# Show top rows
concept_filt_df = concept_df.loc[concept_df["count"] > 100]

if False:
    #  ------------------------------------------------------------
    # Check papers on one concept
    target_concept_id = "https://openalex.org/C2777695942"

    filtered_papers = [
        work
        for work in all_works
        if any(
            concept["id"] == target_concept_id for concept in work.get("concepts", [])
        )
    ]

    # Print some basic info for each matching paper
    for paper in filtered_papers:
        print(f"{paper['display_name']} ({paper.get('publication_year')})")
        print(f"DOI: {paper.get('doi')}")
        print(f"Journal: {paper.get('host_venue', {}).get('display_name', 'N/A')}")
        print("---")
    #  ------------------------------------------------------------
    concept_counter = Counter()

    for work in all_works:
        for concept in work.get("concepts", []):
            if concept["level"] >= 2:
                concept_counter[concept["id"]] += 1

    # Get most common specific concepts
    specific_concepts = [cid for cid, count in concept_counter.items()]
    #  ------------------------------------------------------------
    # Create a DataFrame to summarize works and their concept levels

    rows = []

    for work in all_works:
        work_id = work.get("id")
        title = work.get("display_name", "")[:100]  # Trim long titles
        concept_levels = {0: 0, 1: 0, 2: 0, 3: 0}

        for concept in work.get("concepts", []):
            level = concept.get("level")
            if level in concept_levels:
                concept_levels[level] += 1

        rows.append(
            {
                "work_id": work_id,
                "title": title,
                "level_0": concept_levels[0],
                "level_1": concept_levels[1],
                "level_2": concept_levels[2],
                "level_3": concept_levels[3],
            }
        )

    # Create DataFrame
    df = pd.DataFrame(rows)
    df.sort_values(by="level_1", inplace=True)
    df

# Get All Articles in These Concepts (2020–2025) ------------------------------------------------------------------

# Create dictionary of relevant concept IDs and names
concept_ids = dict(
    zip(concept_filt_df["concept_id"][0:6], concept_filt_df["concept_name"][0:6])
)

# Map to store work_id → matched_concepts
work_concept_matches = defaultdict(lambda: {"concepts": set(), "data": None})

# Loop through each concept ID
for cid, name in concept_ids.items():
    print(f"\nFetching works for concept: {name} ")
    cursor = "*"
    while cursor:
        result = (
            Works()
            .filter(
                **{
                    "concept.id": cid,
                    "from_publication_date": "2020-01-01",
                    "to_publication_date": "2025-12-31",
                }
            )
            .get(per_page=200, cursor=cursor)
        )

        for work in result:
            wid = work["id"]
            matched_concepts = {
                c["id"]
                for c in work.get("concepts", [])
                if c["id"] in concept_ids.keys()
            }

            if len(matched_concepts) >= 1:
                work_concept_matches[wid]["concepts"].update(matched_concepts)
                work_concept_matches[wid]["data"] = work  # store work once

        cursor = (
            result.meta.get("next_cursor")
            if result.meta.get("next_cursor") != cursor
            else None
        )
        cursor = None
        time.sleep(1)  # Respect API rate limit

print("Filtering for works with more than one matching concept...")

# Filter for works with >1 relevant concept
filtered_works = [
    data["data"] for data in work_concept_matches.values() if len(data["concepts"]) > 1
]

print(f"Total filtered works: {len(filtered_works)}")
