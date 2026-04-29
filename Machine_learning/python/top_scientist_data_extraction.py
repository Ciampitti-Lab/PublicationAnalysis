import pandas as pd
import requests
import time

data_path = "data/top2scientistdata/Table_1_Authors_singleyr_2024_pubs_since_1788_wopp_extracted_202508.xlsx"
data = pd.read_excel(data_path, sheet_name="Data")

data = data.loc[data["sm-subfield-1"] == "Agronomy & Agriculture"]
cols_to_eliminate = [
    "firstyr",
    "lastyr",
    "nps (ns)",
    "ncs (ns)",
    "cpsf (ns)",
    "ncsf (ns)",
    "cprat (ns)",
    "np6024 cited2424 (ns)",
    "rank",
    "nc2424",
    "h24",
    "hm24",
    "nps",
    "ncs",
    "cpsf",
    "ncsf",
    "npsfl",
    "ncsfl",
    "c",
    "npciting",
    "cprat",
    "np6024 cited2424",
    "np6024_rw",
    "nc2424_to_rw",
    "nc2424_rw",
    "sm-subfield-1",
    "sm-subfield-1-frac",
    "sm-subfield-2",
    "sm-subfield-2-frac",
    "sm-field",
    "sm-field-frac",
    "rank sm-subfield-1",
]
data = data.drop(columns=cols_to_eliminate)
data = data.rename(
    columns={
        "cntry": "country",
        "np6024": "num_papers",
        "rank (ns)": "rank",
        "nc2424 (ns)": "total_cites",
        "h24 (ns)": "h_index",
        "hm24 (ns)": "hm_index",
        "npsfl (ns)": "num_papers_single+first+last",
        "ncsfl (ns)": "total_cites_single+first+last",
        "c (ns)": "composite_score",
        "npciting (ns)": "num_distinct_citing_papers",
        "self%": "self_citation_percentage",
        "rank sm-subfield-1 (ns)": "rank_in_subfield",
        "sm-subfield-1 count": "num_scientists_in_subfield",
    }
)


data = data.sort_values(by="rank").head(100)
data = data.set_index("rank")


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
    ["0000-0002-9016-2972", "https:/#/orcid.org/0000-0001-2345-6789"]

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
    (0, "0000-0002-9016-2972", 'A5049890100'),
    (1, "0000-0002-9863-8461", 'A5062508940'),
    (2, "0000-0002-3784-1124", True),
    (3, "0000-0002-4701-2936", True),
    (4, "0000-0002-1482-4209", True),
    (5, "0000-0002-3183-5524", True),
    (6, "0000-0002-7216-8326", True),
    (7, "0000-0002-1022-6623", True),
    (8, "0000-0001-7040-1924", True),
    (9, "0000-0002-3897-6581", True),
    (10, "0000-0002-9286-819", True),
    (11, "0000-0001-9336-418", True),
    (12, "0000-0003-4391-390", True),
    (13, "0000-0001-6808-024", True),
    (14, "0000-0001-8573-433", True),
    (15, "0000-0002-1156-827", True),
    (16, "0000-0002-1854-018", True),
    (17, "0000-0001-9543-794", True),
    (18, "", False),
    (19, "0000-0003-1484-273", True),
    (20, "0000-0002-6585-072", True),
    (21, "0000-0002-5998-465", True),
    (22, "0000-0002-5225-720", True),
    (23, "0000-0002-3142-221", True),
    (24, "0000-0001-5326-448", True),
    (25, "0000-0003-1540-466", True),
    (26, "0000-0003-3433-161", True),
    (27, "", "a5072939972"),
    (28, "0000-0003-0913-2643", True),
    (29, "0000-0002-9221-5919", True),
    (30, "", False),
    (31, "0000-0002-9775-3468", True),
    (32, "0000-0002-1664-886X", True),
    (33, "0000-0003-1330-0128", True),
    (34, "0000-0003-2367-3067", True),
    (35, "0000-0001-8971-0129", True),
    (36, "0000-0002-1182-2371", True),
    (37, "0000-0002-2616-1342", True),
    (38, "0000-0003-0739-0913", True),
    (39, "0000-0002-4176-3878", True),
    (40, "0000-0001-5262-5596", True),
    (41, "0000-0002-1010-7317", True),
    (42, "0000-0002-5681-2361", True),
    (43, "0000-0001-6097-4235", True),
    (44, "0000-0002-0284-2514", True),
    (45, "0000-0003-1540-4748", True),
    (46, "0000-0002-3057-3868", True),
    (47, "0000-0003-4350-9520", True),
    (48, "0000-0002-2982-0411", True),
    (49, "0000-0002-5049-5959", True),
    (50, "0000-0002-7741-5090", True),
    (51, "0000-0003-0808-1135", True),
    (52, "0000-0002-1984-3978", True),
    (53, "0000-0001-9771-9895", True),
    (54, "0000-0001-9518-3548", True),
    (55, "", "a5109394371"),
    (56, "0000-0002-0322-2034", True),
    (57, "0000-0002-5874-6775", True),
    (58, "", "a5019789573"),
    (59, "0000-0003-4948-1880", True),
    (60, "0000-0003-3532-8738", True),
    (61, "0000-0002-6219-1442", True),
    (62, "0000-0003-0952-8947", True),
    (63, "0000-0002-6191-8953", True),
    (64, "0000-0001-5458-1259", True),
    (65, "0000-0003-4425-3408", True),
    (66, "0000-0002-1842-419X", True),
    (67, "0000-0002-5797-6798", True),
    (
        68,
        "0000-0001-9054-0489",
        True,
    ),  # Existen dos perfiles que parecen ser la misma perosna, uno tiene el ORCID y el otro no.
    (69, "", "a5063421730"),
    (70, "0000-0003-3265-3770", True),
    (71, "0000-0002-7491-5786", True),
    (72, "0000-0002-7119-8646", True),
    (73, "0000-0002-5972-5036", True),
    (74, "0000-0002-2127-1067", True),
    (75, "0000-0002-6465-1465", True),
    (76, "0000-0003-1667-2971", True),
    (77, "0000-0002-5451-116X", True),
    (78, "0000-0002-0908-8606", True),
    (79, "0000-0002-0501-2823", True),
    (80, "0000-0002-4390-0071", True),
    (81, "0000-0003-0959-9358", True),
    (82, "", "a5112791517"),
    (83, "0000-0002-5779-8581", True),
    (84, "", "a5075501651"),
    (85, "0000-0002-8832-360X", True),
    (86, "0000-0002-3215-1706", True),
    (87, "", "a5103596717"),
    (88, "0000-0003-2131-9451", True),
    (89, "", False),
    (90, "0000-0002-0483-2109", True),
    (91, "0000-0002-7245-9852", True),
    (92, "0000-0002-9042-7504", True),
    (93, "0000-0002-4985-7262", True),
    (94, "", "a5027515270"),
    (95, "0000-0001-6385-3703", True),
    (96, "", "a5111532316"),  # Revisar en profundidad
    (97, "0000-0003-2656-1183", True),
    (98, "0000-0002-4920-4667", True),
    (99, "", False),
]
"""
0: No se pudo identificar el autor, sin ORCID, sin perfil en OpenAlex, o perfil no vinculado a ORCID
1: Se identifico el ID de OpenAlex por medio del ORCID
2: Se identifico el ID de OpenAlex del autor
21: Se identifico el ID de OpenAlex por medio del ORCID, pero existían múltiples matches. Se filtró por works_count>1 y se encontró un match fuerte.
22: Multiples ID's obtenidos, revisar caso manualmente
021: Se identifico el ID de OpenAlex por medio del ORCID, pero existían múltiples matches. Ninguno tenía más de 1 paper, revisar caso manualmente.
01: No se pudo encontrar ID de OpenAlex por medio del ORCID. Posiblemente el autor no tiene perfil de OpenAlex, o no esta vinculado a su ORCID
"""
if len(data) != len(orcid_list):
    raise ValueError("Length of ORCID list must match number of rows in df.")

headers = {"User-Agent": f"mailto:{'ramir713@purdue.edu'}"}

openalex_ids = []
match_flags = []
multiple_matches_log = []  # Para registrar casos de múltiples matches

for idx, orcid, rest in orcid_list:

    # Clean values
    orcid = str(orcid).strip()
    
    # --------------------------------------------------
    # CASE 1: Already has OpenAlex ID
    # --------------------------------------------------
    if isinstance(rest, str) and rest.strip():
        # print(f"row{idx} ya tiene OpenAlex ID")
        if idx==1 or idx==0:
            print('hola')
        openalex_ids.append(rest.strip())
        match_flags.append("2")   # Existing OpenAlex
        continue

    # --------------------------------------------------
    # CASE 2: No ORCID and no OpenAlex
    # --------------------------------------------------
    if not orcid and rest is False:
        # print(f"row{idx} no tiene ORCID ni OpenAlex")
        openalex_ids.append(None)
        match_flags.append("0")   # Missing all
        continue

    # --------------------------------------------------
    # CASE 3: ORCID available → Query OpenAlex
    # --------------------------------------------------
    if orcid:
        try:
            url = f"https://api.openalex.org/authors?filter=orcid:https://orcid.org/{orcid}"
            response = requests.get(url, headers=headers, timeout=15)

            # API error
            if response.status_code != 200:
                # print(f"row{idx} API error {response.status_code}")
                openalex_ids.append(None)
                match_flags.append(f"API_ERROR_{response.status_code}")
                time.sleep(0.5)
                continue

            results = response.json().get("results", [])

            # No match
            if not results:
                # print(f"row{idx} no se encontró en OpenAlex con ORCID {orcid}")
                openalex_ids.append(None)
                match_flags.append("01")

            # Multiple matches
            elif len(results) > 1:
                # Filter only authors with more than 1 work
                valid_results = [author for author in results if author.get("works_count", 0) > 1]

                # No strong candidates
                if len(valid_results) == 0:
                    # print(f"row{idx} múltiples matches pero ninguno con más de 1 paper")
                    openalex_ids.append(None)
                    match_flags.append("021")  
                    # Multiple matches, but all weak profiles

                # Exactly one strong candidate
                elif len(valid_results) == 1:
                    selected_author = valid_results[0]
                    # print(
                    #     f"row{idx} match filtrado por works_count>1: "
                    #     f'{selected_author["id"]} ({selected_author["works_count"]} papers)'
                    # )
                    openalex_ids.append(selected_author["id"])
                    match_flags.append("21")  
                    # Resolved multiple match after filtering

                # Still ambiguous
                else:
                    print(
                        f"row{idx} múltiples matches con más de 1 paper: "
                        f'{[(a["id"], a["works_count"]) for a in valid_results]}'
                    )
                    openalex_ids.append(valid_results[0]["id"])  
                    # Keep first but flag ambiguity
                    match_flags.append("22")

            # Exact match
            else:
                openalex_id = results[0]["id"]
                # print(f"row{idx} match encontrado: {openalex_id}")
                openalex_ids.append(openalex_id)
                match_flags.append("1")

        except Exception as e:
            # print(f"row{idx} ERROR: {e}")
            openalex_ids.append(None)
            match_flags.append(f"ERROR: {str(e)}")

        time.sleep(0.5)
        continue

    # --------------------------------------------------
    # CASE 4: Catch unexpected formats
    # --------------------------------------------------
    print(f"row{idx} formato inesperado")
    openalex_ids.append(None)
    match_flags.append("UNKNOWN")


data["OP_id"] = openalex_ids
data["ORCID_match_status"] = match_flags
print("Busqueda finalizada. Resultados de las primeras 20 filas:")
print(data[["OP_id", "ORCID_match_status"]].head(20))
print("Resumen de estados de match:")
print(data["ORCID_match_status"].value_counts())
resolved=data[data["ORCID_match_status"].isin(["1", "2", "21"])]
print(f"Total autores con ID de OpenAlex identificado: {len(resolved)}")
unresolved=data[data["ORCID_match_status"].isin(["0", "01", "021","22"])]
print(f"Total autores sin ID de OpenAlex identificado: {len(unresolved)}")

for idx, orcid, matches in multiple_matches_log:
    print(f"Fila {idx} con ORCID {orcid} tiene múltiples matches en OpenAlex:")
    for match in matches:
        print(f"  - ID: {match['id']}, Name: {match['display_name']}")
data.to_csv(
    "/home/ramir713/PublicationAnalysis/data/machine_learning_data/top100_agronomy_scientists.csv",
    index=False,
)
