"""Build the dataset card from validated catalog facts, without uploading."""
import json
from pathlib import Path
from .core import write_json


def prepare(root):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text())
    report = json.loads((root / 'validation.json').read_text())
    if not report['passed']:
        raise ValueError('Validate successfully before preparing publication metadata')
    cycle = manifest['cycle']
    if cycle == '2017-2018':
        from .legacy_publication import prepare_2017
        return prepare_2017(root, manifest, report, json.loads((root / 'catalog.json').read_text()))
    if cycle != '2021-2023':
        raise ValueError('The publication card is reviewed for 2021-2023 only; review cycle-specific guidance first')
    catalog = json.loads((root / 'catalog.json').read_text())
    relations = json.loads((root / 'metadata/relationships.json').read_text())
    supplement_link = next((r for r in relations if r.get('source_file') == 'DSQIDS_L' and r.get('lookup_file') == 'DSPI'), {})
    supplement_key = next((r for r in relations if r.get('source_file') == 'DSQIDS_L' and 'candidate_key' in r), {})
    table_lines = ['| Component | Public files |', '|---|---:|']
    for component in ('demographics', 'dietary', 'examination', 'laboratory', 'questionnaire'):
        n = sum(r['component'] == component and bool(r['data_url']) for r in manifest['files'])
        table_lines.append(f'| {component.title()} | {n} |')
    card = f'''# {catalog['title']} — public data and codebooks

Source: CDC / National Center for Health Statistics (NCHS).
Independent export by Riley Zurrin; not an official CDC release or endorsed by CDC, HHS, or the U.S. Government.
The original data and documentation are available free of charge from [CDC]({catalog['release_url']}).

## Coverage and snapshot

This export covers all **{report['public_files']} public XPT files** linked by the five component catalogs in the archived snapshot.
It includes **{report['participants']:,} participants** and **{report['participant_columns']:,} columns** in the convenience participant table.
It inventories **{report['unavailable_files']} restricted/unavailable files** separately; their underlying data are not included.
Catalog discovery: {catalog['discovered_at']}. Individual retrieval timestamps and checksums are in source receipts and the manifest.
This is a snapshot of released public files, not a claim that every measurement collected by NHANES has been released.

{chr(10).join(table_lines)}

## Files and joins

- `data/tables/FILE.csv`: every public source table, preserving original variables, rows, weights, flags, and response codes.
- `data/participants.csv`: demographics roster joined to tables with exactly one row per SEQN. Repeated records and lookup tables are not flattened into it.
- `data/components/*.csv`: five participant-level views, each aligned to the full demographics roster.
- `metadata/column_mapping.csv`: exact source of every column in the convenience views. Repeated variable names are qualified as `FILE__VARIABLE`; values are never silently coalesced.
- `metadata/variables.csv`: per-file definitions, labels, target populations and instructions. `in_data` distinguishes fields present in downloaded data from documented-only fields.
- `metadata/codes.csv`: codes and ranges as **strings**, descriptions, published counts, cumulative counts, and skip destinations. Keys are `(cycle, file_id, variable)`, not variable name alone.
- `metadata/sections.csv`: eligible samples, analytic notes, methods and other codebook sections. Read these before analysis.
- `metadata/profiles.csv`: per-column missingness, distinct values, negative values and data types.
- `source/xpt/` and `source/codebooks/`: original data and documentation. Shared dietary supplement reference files may live under CDC's 1999 directory; they are linked by the current cycle and intentionally included.
- `catalog.json`, `manifest.json`, `validation.json`, `checksums.json`: coverage, provenance, validation and integrity records.

Use `SEQN` to join participant data. Individual-food tables (`DR1IFF_L`, `DR2IFF_L`) and individual-supplement tables (`DSQIDS_L`) have repeated SEQN values: aggregate intentionally or use an explicit one-to-many join.
`metadata/relationships.json` records food/product linkage checks. In this snapshot, {supplement_link.get('unmatched_rows', 0)} supplement records ({len(supplement_link.get('unmatched_ids', []))} distinct unknown-product IDs) intentionally have no product-table match. {supplement_key.get('duplicate_rows', 0)} repeated `(SEQN, DSDPID)` pair(s) are retained; this pair is not a guaranteed row key.
Food and supplement lookup files have their own keys. Consult their codebooks; never join them on SEQN.
A missing cell introduced by the demographics join can mean the participant was absent from that component. Original per-file tables preserve component membership.

## Values and CSV import

No imputation, outlier removal, automatic category decoding, or refusal/don't-know recoding has been applied.
Negative values, tiny values, detection-limit flags, and survey weights are retained.
SAS numeric missing values are empty CSV fields; SAS character blanks remain blank. Original XPT files are the authoritative archival representation.
When exact numeric fidelity matters, use pandas `float_precision="round_trip"`. For character fields, use the source schema in the manifest and disable pandas' default NA-token inference so literal strings such as `NA` and leading-zero codes survive.
Do not globally replace repeated-digit values such as 7 or 9 with missing: their meaning is variable-specific.

## Survey interpretation

The cycle is August 2021–August 2023, not calendar 2021–2022. It used a changed sampling design and data-collection procedures after the pandemic pause.
Use the appropriate survey weights and `SDMVSTRA` / `SDMVPSU`; ordinary unweighted means and standard errors do not describe the U.S. population.
Blood analytes can require phlebotomy weights; fasting and other subsamples have specific weights. PFAS uses `WTSPF2YR`. Do not assume a single universal weight.
Dietary Day 1 and Day 2 have different weights and reliability criteria; 30-day supplement analyses use the applicable Day 1 guidance.
Dietary interviews changed mode. The 24-hour supplement interviews were discontinued. Prescription medication names, durations and reasons were not collected in this cycle; `RXQ_RX_L` contains use/count categories.
Below-detection-limit lab values may already contain CDC's fill values; retain and interpret the accompanying flags.
Age top-coding, eligibility restrictions and special response codes are documented in the codebooks.
Do not treat the 2017–March 2020 combined sample as independent of 2017–2018, or pool cycles without appropriate weighting and harmonization.

See [CDC analytic guidance](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/overviewbrief.aspx?Cycle=2021-2023),
[release notes](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/releasenotes.aspx?Cycle=2021-2023), and the per-file analytic notes.

## Validation

{report.get('independent_reader_files', 0)} files were cross-checked with independent ReadStat and pandas readers (see `metadata/independent_readers.json` for the comparison rules and pandas zero-decoding fix).
{report['raw_csv_roundtrips']} raw-to-CSV roundtrips were checked for exact parsed-value equality.
{report['frequency_checks']:,} checks compared source data with published codebook frequencies or totals.
Participant IDs, coverage, metadata coverage, artifact hashes and all convenience-view columns were checked.
**{len(report.get('source_warnings', []))} known source-documentation discrepancies across {len({w['file_id'] for w in report.get('source_warnings', [])})} source files are retained as warnings.**
DSBI and DSII have row/frequency differences from the linked codebooks; DSPI has two differing source-category counts; FOLFMS_L has a missing weight definition and differing detection-flag counts.
These were independently cross-checked with pandas and ReadStat. The source values are retained. Exceptions apply only to exact source and codebook hashes; changed discrepancies fail validation.
See `metadata/source_discrepancies.json` and `validation.json` for every discrepancy. The remaining checked counts/totals agree.
Some codebook fields are documented but absent from the XPT (e.g., three MCQ_L fields); `in_data` and the manifest make this explicit.

## Use and attribution

Use is governed by the [NCHS Data User Agreement](https://www.cdc.gov/nchs/policy/data-user-agreement.html), including statistical use and prohibitions on identifying participants or linking to individually identifiable records.
See [CDC use of agency materials](https://www.cdc.gov/other/agencymaterials.html). This export does not grant additional rights over source materials or replace those terms.
Cite CDC/NCHS NHANES, the cycle, individual source files, and this snapshot date. No CDC logos are used to brand this dataset.
'''
    (root / 'README.md').write_text(card, encoding='utf-8')
    write_json(root / 'dataset-metadata.json', {
        'title': f'NHANES {cycle}: Public Data and Codebooks',
        'id': f'rileyzurrin/nhanes-{cycle}-public-data-and-codebooks',
        'subtitle': 'All released public tables, participant views, dictionaries and validation',
        'description': card,
        'licenses': [{'name': 'other'}]
    })
