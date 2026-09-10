"""Read and clean the SharePoint export, and shape rows for the tool.

STUB — next in the build order after derivation.py. No logic yet; this file
records the decisions so the shape is visible.

Responsibilities:
  * read the exported CSV (handles line breaks inside cells, stray blank
    rows, leading/trailing whitespace in codes)
  * normalise the retired round-1 quadrant label to a known set, kept only
    for reference ("round-1 label (retired scheme)")
  * build RowKey = f"{Source File} :: {Assessment Number}"  (stable, and
    unique even where a subject code appears twice in the export)
  * coerce Inspire Score / Assure Score to float or None
  * compute subject_max_number per (Source File) group
  * produce a clean DataFrame the app can hand to derivation.derive_task
  * export the current state back to CSV for re-import to SharePoint

Input columns (from the real export):
  Subject Code, Subject Title, Program Code, Assessment Number,
  Assessment Type, Learning Outcomes, Weighting, Conditions,
  Inspire Score, Assure Score, Quadrant, Confirmed, Notes/Comments,
  Source File
"""

from __future__ import annotations

# TODO: implement read_export(), clean(), row_key(), to_export_csv()
