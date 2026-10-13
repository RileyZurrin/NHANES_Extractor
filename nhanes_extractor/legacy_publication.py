"""Publication preparation for the existing 2017–2018 Kaggle dataset."""
import csv
import json
from pathlib import Path
from .core import write_json

DATASET_ID = 'rileyzurrin/national-health-and-nutrition-exam-survey-2017-2018'
REPOSITORY = 'https://github.com/RileyZurrin/NHANES_Extractor'


def prepare_2017(root, manifest, report, catalog):
    root = Path(root)
    entries = {r['file_id']: r for r in manifest['files']}
    with (root / 'metadata/variables.csv').open(newline='') as stream:
        variables = {(r['file_id'], r['variable']): r for r in csv.DictReader(stream)}
    with (root / 'metadata/column_mapping.csv').open(newline='') as stream:
        mappings = list(csv.DictReader(stream))
    resources, dictionary = [], []

    def field(fid, name):
        definition = variables.get((fid, name), {})
        parts = [definition.get('label', ''), definition.get('description', '')]
        parts = list(dict.fromkeys(p for p in parts if p))
        if definition.get('target'):
            parts.append('Target: ' + definition['target'])
        parts.append(f'Source: {fid}.{name}. Codes and analytic notes: metadata/codes.csv and metadata/sections.csv.')
        return {'name': name, 'type': 'string' if name in entries[fid]['character_columns'] else 'number',
                'description': ' '.join(parts)}

    for entry in entries.values():
        if not entry['data_url']:
            continue
        fields = [field(entry['file_id'], name) for name in entry['column_names']]
        resources.append({'path': entry['csv_path'], 'description': f"{entry['title']}. Grain: {entry['grain']}; {entry['rows']:,} rows. Original source table; consult its codebook.",
                          'schema': {'fields': fields}})
    for relative in sorted({r['output_file'] for r in mappings}):
        by_column = {r['output_column']: r for r in mappings if r['output_file'] == relative}
        with (root / relative).open(newline='') as stream:
            header = next(csv.reader(stream))
        fields = []
        for name in header:
            row = by_column.get(name, {'file_id': 'DEMO_J', 'variable': 'SEQN'})
            fid, variable = row['file_id'], row['variable']
            definition = variables.get((fid, variable), {})
            spec = field(fid, variable)
            spec['name'] = name
            fields.append(spec)
            dictionary.append({'output_file': relative, 'output_column': name, 'cycle': '2017-2018',
                               'file_id': fid, 'variable': variable, 'label': definition.get('label', ''),
                               'description': definition.get('description', ''), 'target': definition.get('target', ''),
                               'instructions': definition.get('instructions', ''), 'type': spec['type'],
                               'metadata_source': definition.get('metadata_source', ''), 'codebook_url': entries[fid]['doc_url']})
        resources.append({'path': relative, 'description': 'One row per demographics participant. Source-qualified duplicate names; repeated-record and lookup tables excluded. See DATA_DICTIONARY.csv.', 'schema': {'fields': fields}})
    with (root / 'DATA_DICTIONARY.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dictionary[0]))
        writer.writeheader()
        writer.writerows(dictionary)
    table_rows = '\n'.join(f"| {c.title()} | {sum(r['component'] == c and bool(r['data_url']) for r in entries.values())} |"
                           for c in ('demographics', 'dietary', 'examination', 'laboratory', 'questionnaire'))
    card = f'''# National Health and Nutrition Examination Survey 2017–2018

A reproducible CSV export of CDC/NCHS NHANES 2017–2018, with all {report['public_files']} public source tables in this snapshot, data dictionaries, original XPT files, and validation records. The participant view has **{report['participants']:,} people and {report['participant_columns']:,} columns**, including SEQN.

This is the 2017–2018 survey cycle. Source retrieval in 2026 does not make these observations 2026 data. The August 2021–August 2023 cycle is a separate release.

Original data and documentation are available free of charge from CDC.

[Original CDC release]({catalog['release_url']}) · [Extractor on GitHub]({REPOSITORY})

## What changed from the original export

This update replaces the selective component export with a source-preserving release. Negative values are retained; text is decoded into readable strings; laboratory flags and additional released variables are included. Repeated food, supplement, audiometry, and prescription records are available in separate tables. Original source files, definitions, response codes, and provenance are bundled.

**This is a schema-changing update.** Duplicate variable names are qualified as `FILE__VARIABLE`, and all five component views use the complete demographics roster. Consult `MIGRATION.md` and `DATA_DICTIONARY.csv` before updating a notebook built against version 1. No automatic category recoding, imputation, outlier deletion, or participant deduplication has been applied.

## Coverage

Catalog snapshot: {catalog['discovered_at']}.

| Component | Public source tables |
|---|---:|
{table_rows}

The release has {report.get('grains', {}).get('participant', 0)} unique-participant tables, {report.get('grains', {}).get('participant_repeated', 0)} repeated-participant tables, and {report.get('grains', {}).get('lookup', 0)} lookup tables. The catalog also records 26 restricted entries and the withdrawn SSEVD_J assay. Their underlying data are not included. Coverage means all public XPT links in the archived component catalogs, not every measurement ever collected by NHANES. Shared supplement and drug reference tables can reside under earlier CDC year directories and are included because this cycle links them.

## Files and data dictionaries

- `data/participants.csv`: one row per participant, joining only source tables with unique SEQN.
- `data/components/`: demographics, dietary, examination, laboratory, and questionnaire views, each with {report['participants']:,} rows.
- `data/tables/`: all {report['public_files']} source tables at their original record grain.
- `DATA_DICTIONARY.csv`: every column in each participant/component view, its original file and variable, label, description, target population, instructions, type, and codebook URL.
- `metadata/variables.csv`: source-file variable definitions, including documented-only fields (`in_data=false`) and clearly labeled fallback metadata.
- `metadata/codes.csv`: response codes, ranges, descriptions, published frequencies, cumulative counts, and skip destinations. Read codes as strings; use `(cycle, file_id, variable)` as the dictionary key.
- `metadata/sections.csv`: methods, eligibility, and analytic guidance from each codebook.
- `metadata/column_mapping.csv`: compact source mapping for convenience-view columns.
- `metadata/profiles.csv`: missingness and numeric-value summaries.
- `source/`: original XPT files, codebooks, catalog pages, and retrieval receipts.
- `catalog.json`, `manifest.json`, `validation.json`, and `checksums.json`: coverage, schemas, provenance, validation, and integrity.

## Joining and importing

Use SEQN to identify participants. Individual-food, individual-supplement, audiometry sensor, and prescription tables contain repeated SEQN values. They are intentionally excluded from the wide participant view; aggregate for a stated purpose or use an explicit one-to-many join. Food and product/drug lookup tables have separate keys. The participant/product pair is not necessarily unique; do not silently drop repeated records.

Blank values in joined views can indicate absence from a component; inspect the original table to distinguish membership from missing responses. Numeric missing values and blank character fields are empty CSV fields. Original XPT files remain the archival representation. For exact numeric imports use pandas `float_precision="round_trip"`; read character columns according to the manifest with `keep_default_na=False` to preserve leading zeros and literal strings such as NA.

```python
import json
from pathlib import Path
import pandas as pd

root = Path("/kaggle/input/national-health-and-nutrition-exam-survey-2017-2018")
manifest = json.loads((root / "manifest.json").read_text())
entry = next(f for f in manifest["files"] if f["file_id"] == "DEMO_J")
chars = entry["character_columns"]
df = pd.read_csv(root / entry["csv_path"], float_precision="round_trip",
                 keep_default_na=False, dtype={{c: str for c in chars}},
                 na_values={{c: [""] for c in entry["column_names"] if c not in chars}})
```

## Survey analysis

NHANES uses a complex survey design. Select interview, examination, dietary, fasting, or other subsample weights appropriate to the variables and sample, together with SDMVSTRA and SDMVPSU. An unweighted convenience-table average is not a population estimate. Read the original codebook analytic notes for each included measurement.

For this cycle the first dietary recall was collected in person and the second by telephone; 24-hour supplement and detailed prescription records are included where publicly released. Refusal, don't-know, eligibility, age top-coding, and below-detection-limit conventions are variable-specific. Do not globally turn values such as 7, 9, or repeated 9s into missing. Preserve detection flags and CDC-provided laboratory fill values.

Do not combine 2017–2018 with the overlapping 2017–March 2020 pre-pandemic sample as independent observations. Cross-cycle comparisons and pooling require harmonization and appropriate weights. Consult the [NHANES analytic tutorials](https://wwwn.cdc.gov/nchs/nhanes/tutorials/default.aspx) and per-file notes.

## Validation and known source discrepancies

All {report['public_files']} tables passed independent ReadStat/pandas reader comparisons and exact parsed-value CSV roundtrips. Every convenience-view column was checked against its source; {report['frequency_checks']:,} codebook checks ran. The independent-reader report describes the exact encoded-zero correction needed by the secondary pandas reader and comparison-only trailing-whitespace normalization.

There are **{len(report['source_warnings'])} reviewed source warnings across five files**: 46 supplement-reference count discrepancies in DSBI/DSII/DSPI, 24 disability-codebook discrepancies in DLQ_J, and one missing-definition finding covering the three DRXFCD_J fields. DLQ_J contains 8,897 respondents while its twelve frequency tables each total 8,898. DRXFCD_J supplies narrative documentation; its XPT labels are preserved with their metadata source explicitly identified. No rows or values are invented to match documentation. Each exception is bound to the cycle, exact finding, and both source hashes. Full details are in `metadata/source_discrepancies.json`.

## Attribution and source terms

Original data: CDC, National Center for Health Statistics, National Health and Nutrition Examination Survey 2017–2018. Cite the cycle, relevant source files, and snapshot date when using this export. Independent extraction by Riley Zurrin; this dataset is not an official CDC product and is not endorsed by CDC, HHS, or the U.S. Government.

Consult the [NCHS Data User Agreement](https://www.cdc.gov/nchs/policy/data-user-agreement.html) and [CDC agency-material guidance](https://www.cdc.gov/other/agencymaterials.html). The source terms and any third-party notices continue to apply; this export does not grant additional rights over them.
'''
    (root / 'README.md').write_text(card)
    migration = '''# Migrating from the original 2017–2018 export

This release changes file paths and some column names. Keep version 1 pinned when reproducing an existing published analysis; use this version explicitly for corrected or new work.

## File paths

The original files were `NHANES_2017-2018/demographics.csv`, `dietary.csv`, `examination.csv`, `laboratory.csv`, and `questionnaire.csv`. The five component views now live at `data/components/{demographics,dietary,examination,laboratory,questionnaire}.csv`. The authoritative per-source files are `data/tables/FILE.csv`. All component views share the 9,254-person demographics roster; examination and laboratory row counts are therefore larger than the original selective exports. This does not mean new participants were collected.

## Columns and dictionaries

Look up your old variable name in `DATA_DICTIONARY.csv`, filtering by `output_file`. If it occurs in multiple source files, choose the file appropriate to your analysis. Names such as `FILE__VARIABLE` keep all source values separately; the old export combined duplicate names and could conceal differences. A variable name alone is not a globally unique dictionary key.

The source dictionaries are `metadata/variables.csv` and `metadata/codes.csv`; the view dictionary is `DATA_DICTIONARY.csv`. No single-column dictionary can safely replace this file-aware model. Codebook-only fields remain documented but are not invented in data tables.

## Values and records

Negative values are no longer replaced with zero. Text is readable rather than Python byte-string literals such as b'Type A'. Laboratory comment/detection flags are retained. Current public source revisions may fill values absent from the historical export. Missing, refused, don't-know and not-applicable responses remain distinct according to their codebooks.

Repeated food, supplement, sensor and prescription records remain separate. Do not merge them into a one-row-per-person frame without choosing the intended aggregation. A matching SEQN is not proof of a one-to-one relationship.

Read README.md for CSV import and survey-weight guidance, and VERSION_NOTES.txt for the version summary.
'''
    (root / 'MIGRATION.md').write_text(migration)
    notes = 'Complete validated 2017–2018 refresh: 133 public source tables; 9,254 participants. Corrects negative-to-zero conversion and byte-string text. Preserves lab flags, repeated records and lookup tables. Adds embedded data dictionaries, source files, provenance and validation. Breaking changes: source-qualified duplicate columns and component views aligned to the full roster. Read MIGRATION.md. Includes 71 explicitly documented CDC source warnings; no imputation or fabricated corrections.'
    (root / 'VERSION_NOTES.txt').write_text(notes + '\n')
    for relative, description in [('DATA_DICTIONARY.csv', 'Complete source-aware dictionary for all convenience-view columns.'),
                                  ('metadata/variables.csv', 'Source-file definitions; join using cycle, file_id and variable.'),
                                  ('metadata/codes.csv', 'Response codes/ranges as strings, descriptions, published counts and skip logic.'),
                                  ('metadata/sections.csv', 'Original documentation sections including analytic notes.'),
                                  ('metadata/column_mapping.csv', 'Convenience-column source mapping.'),
                                  ('metadata/profiles.csv', 'Source-column profile statistics.')]:
        with (root / relative).open(newline='') as stream:
            header = next(csv.reader(stream))
        resources.append({'path': relative, 'description': description,
                          'schema': {'fields': [{'name': c, 'type': 'string', 'description': c.replace('_', ' ')} for c in header]}})
    write_json(root / 'dataset-metadata.json', {
        'title': 'National Health & Nutrition Exam Survey 2017-2018', 'id': DATASET_ID,
        'subtitle': '133 public tables, participant views, data dictionaries and source validation',
        'description': card, 'resources': resources,
        'keywords': ['health', 'exercise', 'healthcare', 'nutrition', 'drugs and medications'],
        'userSpecifiedSources': f'CDC/NCHS NHANES 2017–2018: {catalog["release_url"]}. Extraction repository: {REPOSITORY}.'
    })
