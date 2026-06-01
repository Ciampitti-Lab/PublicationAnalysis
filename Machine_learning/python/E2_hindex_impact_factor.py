import requests
API_KEY = 'Vuopm7PwTu5AE0KW6QrHpg'
url='https://api.openalex.org/sources'

params = {
    "filter": "display_name.search:Pest Management Science",
    "select": "id,display_name,issn,is_core,is_in_doaj",
    "api_key": API_KEY,
}

response = requests.get(url, params=params)

data = response.json()

for source in data["results"]:
    print(
        source.get("display_name"),
        source.get("id"),
        source.get("issn"),
        source.get("is_core"),
        source.get("is_in_doaj")
    )