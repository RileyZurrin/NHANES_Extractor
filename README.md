# NHANES Extractor

Download the full public NHANES release catalog, preserve original XPORT data and codebooks, and create validated CSV tables and participant views.

The 2.0 pipeline was exercised against both the 2017–2018 and August 2021–August 2023 releases. It replaces the original selective scraper used for the [2017–2018 Kaggle dataset](https://www.kaggle.com/datasets/rileyzurrin/national-health-and-nutrition-exam-survey-2017-2018). Existing 2017–2018 exports are historical and unchanged.

## Setup

Python 3.10+ is required (validated locally on 3.13).

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
pytest -q
```

## Download and validate

```sh
python -m nhanes_extractor run --cycle 2021-2023
python -m nhanes_extractor run --cycle 2017-2018
```

The default output is `artifacts/2021-2023`. This downloads all public files and documentation, converts tables, creates participant views, and validates. Network failures return a nonzero exit status. Rerun the same command to resume with checksum-verified cached files. Use `--refresh` to retrieve updated source files and catalogs, or use a new output directory for an immutable new snapshot.

```sh
# Inspect coverage without downloading all XPT files.
python -m nhanes_extractor discover --cycle 2021-2023 --output artifacts/2021-2023
# Rebuild from already-downloaded sources, offline.
python -m nhanes_extractor build --output artifacts/2021-2023
# Recheck the source, all CSV values, joins, coverage and hashes, offline.
python -m nhanes_extractor validate --output artifacts/2021-2023
# Create dataset description and Kaggle metadata only after validation.
python -m nhanes_extractor prepare --output artifacts/2021-2023
# Copy a verified publication bundle; destination must be new.
python -m nhanes_extractor package --output artifacts/2021-2023 --destination releases/nhanes-2021-2023
```

No command uploads or publishes. The generated Kaggle license field is `other`, with CDC/NCHS source terms linked in the dataset description. Review the generated description and source discrepancies before publishing. The explicit cycle format also accepts older CDC cycle names, but only 2021–2023 has undergone the full-release validation described here.

## What is preserved

- Every downloadable public table in the five catalogs; restricted catalog entries remain an explicit inventory.
- Original XPT bytes, source HTML, catalog snapshots, URLs, retrieval timestamps and SHA-256 receipts.
- All numeric values, character values, missing fields, weights, design variables, lab flags and response codes.
- Repeated food/supplement records and nonparticipant lookup tables in their original shapes.
- Codebook variable labels, questions, instructions, targets, all other named fields, code/range strings, counts, skip logic and analytic sections.

`data/tables/` is the authoritative CSV layer. `data/participants.csv` and five `data/components/` views join unique-SEQN tables to the demographics roster. Repeated records are kept separately to avoid multiplying participant rows. Any repeated column names in a view are namespaced as `FILE__VARIABLE`; `metadata/column_mapping.csv` records their sources. Blank values in joined views can indicate nonmembership in a component; inspect the original per-file table when distinguishing nonparticipation from missing answers.

CSV readers must respect source character columns and empty fields. The manifest records character column names and decode choices; use pandas `float_precision='round_trip'` for exact numeric roundtrips and `keep_default_na=False` for character fields. Codebook `code` columns must be read as strings.

## Quality gates and known source issues

Tests cover malformed catalogs, restricted rows, repeated IDs, conflicting columns, source encodings, strings, negative/tiny values, missing values, codebook bins, atomic downloads and exact-hash source exceptions. The release validator checks every raw-to-CSV value, every convenience-view column, roster membership, source coverage, codebook frequencies and artifact integrity.

The October 2026 CDC snapshot contains independently verified codebook/data disagreements in DSBI, DSII, DSPI and FOLFMS_L for 2021–2023. The 2017–2018 snapshot shares the three supplement lookup discrepancies and also has a one-row DLQ_J codebook discrepancy plus narrative-only DRXFCD_J definitions. `nhanes_extractor/source_exceptions.json` records exact reviewed messages and both source hashes. They become visible warnings, never data corrections. Any different source bytes or unexpected discrepancy fails validation. The folate weight without a codebook definition receives only its original XPT label, explicitly marked as fallback metadata. Codebook-only fields remain visible with `in_data=false`.

See [the research notes](docs/RESEARCH.md) for the survey changes, source links, and engineering decisions. The generated dataset card describes survey weights, dietary-mode changes, detection limits, missingness and cross-cycle restrictions.

## Legacy entry points

`Data_scraper/scraper.py` and `Dictionary_scraper/dict_encoding_scraper.py` now launch the unified pipeline. With no arguments they run the default cycle; CLI arguments can select commands and output paths. Dictionary extraction is part of the same catalog-driven run, so it cannot silently exclude different files. Original archived scripts remain for historical reference.

## 2017–2018 compatibility verification

The full October 2026 run downloaded and validated all 133 public tables: 119 unique-participant tables, nine repeated-record tables and five lookup tables. The participant view has 9,254 rows and 2,623 columns. All 133 tables passed independent-reader comparisons and exact CSV roundtrips; 19,176 codebook checks ran. Seventy-one individually reviewed source findings remain visible warnings bound to the exact XPT and documentation hashes. Twenty-six restricted files and the withdrawn SSEVD_J assay remain cataloged without public data downloads.

Legacy cycles use CDC's BeginYear/CycleBeginYear routes. Withdrawn rows have no download/documentation URLs. Legacy layout tables supply drug variable labels and codes; narrative-only lookup documentation preserves source sections and explicitly marks XPT-label fallbacks. Food/product relationship checks use the catalog's cycle suffix.

Comparison against the historical component CSVs retained every participant and original variable name. Demographics match exactly. After accounting for old byte-string serialization and coalesced column names, the differences are 10,924 restored negative values and 12,772 formerly empty hepatitis results; the current raw files independently verify both. The lab view also includes 271 variable names absent from the historical export. No historical CSV was overwritten. The publication preparation command supports both cycles; 2017–2018 targets the existing Kaggle dataset slug and includes a source-aware view dictionary, full per-CSV Kaggle column schemas, migration guidance, and version notes.


Prepare the existing 2017–2018 Kaggle dataset update:

```sh
python -m nhanes_extractor prepare --output artifacts/2017-2018
python -m nhanes_extractor package --output artifacts/2017-2018 --destination releases/2017-2018
```

`prepare` creates the card, version notes, migration guide, `DATA_DICTIONARY.csv`, and Kaggle resource schemas. The existing dataset title/slug are preserved. Version metadata deliberately omits a license override; the current Kaggle badge is separate from the CDC source terms. These commands do not publish or upload.

## Reproduce the published 2021-2023 Version 1 package

The final publication profile now lives in `nhanes_extractor/release_2023.py`.
It builds the full dictionary for all 82 source tables and six views, checks every
dictionary column against the CSV headers, preserves the archived source artifacts,
and writes the card, version notes, file descriptions, checksums and ZIP.
It adds no inline Kaggle column schemas.

This is a frozen release profile for the October 13, 2026 snapshot, not a template
for future releases. Start with the archived validated build or an unzipped copy of
[Kaggle Version 1](https://www.kaggle.com/datasets/rileyzurrin/nhanes-2021-2023-public-data-and-codebooks).
Live CDC downloads can change. Re-running discovery or validation also changes
retrieval and validation timestamps, so it cannot promise byte-for-byte reproduction.
The profile regenerates publication files without rerunning or rewriting the archived
validation evidence. It rejects failed validation and changed artifact hashes.

```sh
python -m nhanes_extractor.release_2023 artifacts/2021-2023 \
  --destination releases/2021-2023-v1 \
  --reference docs/releases/2021-2023-v1-sha256.json
```

The destination must be new. The command writes a sibling ZIP and verification
report and exits nonzero on any missing, extra or changed member. All 472 member
paths and SHA-256 values must match the reference from the verified Kaggle download.
ZIP container bytes can differ because of timestamps and compression.

The archive retains the metadata originally uploaded, including its historical
`annually` update-frequency field. Later website edits are recorded separately in
`docs/releases/2021-2023-live.json`; the live frequency is unspecified. Reproducing
an archive does not apply those website settings or upload anything.

## Verify a Kaggle download

Compare an existing ZIP, without extracting untrusted archive paths:

```sh
python -m nhanes_extractor.verification \
  --expected docs/releases/2021-2023-v1-sha256.json \
  --actual downloaded.zip --report verification.json
```

Or download a specific public version through the API and verify it:

```sh
python -m nhanes_extractor.verification \
  --expected docs/releases/2021-2023-v1-sha256.json \
  --dataset rileyzurrin/nhanes-2021-2023-public-data-and-codebooks \
  --version 1 --report verification.json
```

`--expected` also accepts the original upload ZIP. Verification detects missing,
extra, changed and duplicate members and reads every member through the ZIP CRC
checks. A failed HTTP response or a non-ZIP response is an error, not a successful
verification. Kaggle can serve individual files before it finishes its full ZIP;
an individual-file check alone does not prove the ZIP contains no extra files.
