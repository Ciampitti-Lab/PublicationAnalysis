#!/bin/bash
jupyter nbconvert eda_publications.ipynb \
  --to html \
  --output index.html \
  --TagRemovePreprocessor.enabled=True \
  --TagRemovePreprocessor.remove_cell_tags hide-cell \
  --TagRemovePreprocessor.remove_input_tags hide-input

git add index.html
git add eda_publications.ipynb
git commit -m "Update published notebook"
git push origin Add/data-analisys-with-plotting