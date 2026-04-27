# *Pipeline for machine learning models*

## Data extraction

The idea is to use  the data from [Top SCINET - Top 2% Scientists](https://topscinet.com/) to extract the top 100 scientist in the subfield Agronomy & Agriculture. Search their Open Alex ID and use it to extract all their works from 2018 to 2023

## Data preprocessing

After obtaining the data from all the 100 authors select the correct features from the Open Alex API and make different filters.

### Ongoin filters

* Papers that wher published in peer reviwed journals
* Papers where the queried author where corresponding authors
* Papers that are categorized inside the subfield selected
