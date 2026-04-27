import pandas as pd 
import requests
import time
data_path='data/top2scientistdata/Table_1_Authors_singleyr_2024_pubs_since_1788_wopp_extracted_202508.xlsx'
data=pd.read_excel(data_path,sheet_name='Data')

data=data.loc[data['sm-subfield-1']=='Agronomy & Agriculture']
cols_to_eliminate=[
'firstyr', 'lastyr','nps (ns)',
'ncs (ns)', 'cpsf (ns)', 'ncsf (ns)','cprat (ns)', 'np6024 cited2424 (ns)',
'rank', 'nc2424', 'h24', 'hm24', 'nps', 'ncs', 'cpsf', 'ncsf',
'npsfl', 'ncsfl', 'c', 'npciting', 'cprat', 'np6024 cited2424',
'np6024_rw', 'nc2424_to_rw', 'nc2424_rw', 'sm-subfield-1',
'sm-subfield-1-frac', 'sm-subfield-2', 'sm-subfield-2-frac', 'sm-field',
'sm-field-frac', 'rank sm-subfield-1',
]
data=data.drop(columns=cols_to_eliminate)
data=data.rename(columns={
'cntry':'country','np6024':'num_papers','rank (ns)':'rank',
'nc2424 (ns)':'total_cites','h24 (ns)':'h_index','hm24 (ns)':'hm_index',
'npsfl (ns)':'num_papers_single+first+last','ncsfl (ns)':'total_cites_single+first+last',
'c (ns)':'composite_score','npciting (ns)':'num_distinct_citing_papers','self%':'self_citation_percentage',
'rank sm-subfield-1 (ns)':'rank_in_subfield','sm-subfield-1 count':'num_scientists_in_subfield',
})
data =data.sort_values(by='rank').head(100)
data=data.set_index('rank')


"""
Matches a manually curated ORCID list (ordered to match df rows)
to OpenAlex Author IDs and adds:
    - OP_id  -> OpenAlex Author ID
    - ORCID_match_status -> Match result / warning flag

Parameters:
----------
df : pandas.DataFrame
    Your dataframe of authors (same order as ORCID list)

orcid_list : list
    Ordered list of ORCID URLs or bare ORCID strings
    Example:
    ["0000-0002-9016-2972", "https://orcid.org/0000-0001-2345-6789"]

email : str
    Your email for polite API usage

delay : float
    Delay between API requests

Returns:
-------
pandas.DataFrame
    Original df with:
    - OP_id
    - ORCID_match_status
"""
orcid_list = [
    (0, "https://orcid.org/0000-0002-9016-2972"),
    (1, "https://orcid.org/0000-0002-9863-8461"),
    (2, "https://orcid.org/0000-0002-3784-1124"),
    (3, "https://orcid.org/0000-0002-4701-2936")
    (4, '')
]
if len(data) != len(orcid_list):
    raise ValueError("Length of ORCID list must match number of rows in df.")

headers = {
    "User-Agent": f"mailto:{'ramir713@purdue.edu'}"
}

openalex_ids = []
match_flags = []

for orcid in orcid_list:

    # Missing ORCID
    if pd.isna(orcid) or str(orcid).strip() == "":
        openalex_ids.append(None)
        match_flags.append("NO_ORCID_PROVIDED")
        continue

    try:
        # Clean ORCID
        orcid_clean = (
            str(orcid)
            .strip()
            .replace("https://orcid.org/", "")
            .replace("http://orcid.org/", "")
        )

        # Query OpenAlex
        url = f"https://api.openalex.org/authors?filter=orcid:https://orcid.org/{orcid_clean}"
        response = requests.get(url, headers=headers, timeout=15)

        # API error
        if response.status_code != 200:
            openalex_ids.append(None)
            match_flags.append(f"API_ERROR_{response.status_code}")
            time.sleep(0.5)
            continue

        results = response.json().get("results", [])

        # No OpenAlex match
        if len(results) == 0:
            openalex_ids.append(None)
            match_flags.append(
                "NO_OPENALEX_MATCH (Possible incorrect ORCID, missing OpenAlex profile, or ORCID not linked)"
            )

        # Multiple matches (rare but useful warning)
        elif len(results) > 1:
            openalex_ids.append(results[0]["id"])
            match_flags.append(
                "MULTIPLE_MATCHES_FOUND (Check ORCID assignment manually)"
            )

        # Exact match
        else:
            openalex_ids.append(results[0]["id"])
            match_flags.append("MATCHED")

    except Exception as e:
        openalex_ids.append(None)
        match_flags.append(f"ERROR: {str(e)}")

    time.sleep(0.5)


data["OP_id"] = openalex_ids
data["ORCID_match_status"] = match_flags




data.to_csv('/home/ramir713/PublicationAnalysis/data/machine_learning_data/top100_agronomy_scientists.csv',index=False)