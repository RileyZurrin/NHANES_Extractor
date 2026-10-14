"""Reproduce the reviewed October 13, 2026 publication from its archived build.

This profile preserves the metadata embedded in Kaggle Version 1. Later website
presentation edits are recorded separately in docs/releases/2021-2023-live.json.
"""
import csv
import hashlib
import json
from pathlib import Path

def sha(path):
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda : stream.read(1024 * 1024), b''):
            digest.update(chunk)
        return digest.hexdigest()

def verify_artifacts(root, hashes):
    for (name, expected) in hashes.items():
        if sha(root / name) != expected:
            raise ValueError(f'Artifact changed: {name}')

def finalize(root):
    p = Path(root)
    catalog = json.loads((p / 'catalog.json').read_text())
    if not catalog['discovered_at'].startswith('2026-10-13'):
        raise ValueError('This publication profile requires the October 13, 2026 snapshot')
    oldhash = json.loads((p / 'artifact_hashes.json').read_text())
    verify_artifacts(p, oldhash)
    manifest = json.loads((p / 'manifest.json').read_text())
    entries = {e['file_id']: e for e in manifest['files']}
    with (p / 'metadata/variables.csv').open(newline='') as f:
        variables = {(r['file_id'], r['variable']): r for r in csv.DictReader(f)}
    with (p / 'metadata/column_mapping.csv').open(newline='') as f:
        mappings = list(csv.DictReader(f))
    rows = []

    def add(path, col, fid, var):
        d = variables.get((fid, var))
        if d is None:
            raise ValueError(f'Missing dictionary definition: {fid}/{var}')
        e = entries[fid]
        rows.append(dict(output_file=path, output_column=col, cycle=manifest['cycle'], file_id=fid, variable=var, label=d['label'], description=d['description'], target=d['target'], instructions=d['instructions'], type='string' if var in e['character_columns'] else 'number', metadata_source=d['metadata_source'], codebook_url=e['doc_url']))
    for e in entries.values():
        if not e.get('data_url'):
            continue
        for col in e['column_names']:
            add(e['csv_path'], col, e['file_id'], col)
    for path in sorted({r['output_file'] for r in mappings}):
        by = {r['output_column']: r for r in mappings if r['output_file'] == path}
        with (p / path).open(newline='') as f:
            header = next(csv.reader(f))
        for col in header:
            if col == 'SEQN':
                (fid, var) = ('DEMO_L', 'SEQN')
            else:
                (fid, var) = (by[col]['file_id'], by[col]['variable'])
            add(path, col, fid, var)
    if len(rows) != len({(r['output_file'], r['output_column']) for r in rows}):
        raise ValueError('Duplicate dictionary column')
    for r in rows:
        for (k, v) in r.items():
            r[k] = ' '.join(v.replace('—', '; ').split())
    with (p / 'DATA_DICTIONARY.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    card = (p / 'README.md').read_text().replace('—', '-')
    card = card.replace('# NHANES August 2021-August 2023 - public data and codebooks', '# NHANES August 2021-August 2023\n\nCSV files, original CDC data, and codebooks for the August 2021-August 2023 survey cycle. Start with `DATA_DICTIONARY.csv` to find a column and its source.\n\n[Extractor and reproducible build](https://github.com/RileyZurrin/NHANES_Extractor)')
    card = card.replace('## Files and joins\n', '## Files and joins\n\n- `DATA_DICTIONARY.csv`: every column in all 82 source tables and all six participant/component views. Includes the source file, original variable, definition, eligible population, instructions, data type, and CDC codebook link. Filter by `output_file` and `output_column`. Response codes are in `metadata/codes.csv`.\n')
    card = card.replace('1 repeated `(SEQN, DSDPID)` pair(s) are retained', 'One repeated `(SEQN, DSDPID)` pair is retained')
    card = card.replace('## Validation\n', '## Validation\n\n`validation.json` is the final validation result. `build_report.json` records the initial source/codebook differences before review; the 51 reviewed differences are documented below.\n')
    (p / 'README.md').write_text(card)
    meta = json.loads((p / 'dataset-metadata.json').read_text())
    meta.update(title='NHANES August 2021-August 2023', subtitle='82 public tables, full data dictionary, original files and validation', description=card, keywords=['health', 'healthcare', 'nutrition'], expectedUpdateFrequency='annually', userSpecifiedSources='CDC/NCHS NHANES August 2021-August 2023. Source snapshot retrieved October 13, 2026. https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/default.aspx?Cycle=2021-2023')
    meta['resources'] = [{'path': e['csv_path'], 'description': f"{e['title']}. {e['rows']:,} rows. Grain: {e['grain']}. Definitions: DATA_DICTIONARY.csv."} for e in entries.values() if e.get('data_url')]
    meta['resources'] += [{'path': 'DATA_DICTIONARY.csv', 'description': 'Full source-aware dictionary for every source-table and participant/component-view column. Response codes are in metadata/codes.csv.'}]
    meta['description'] = meta['description'].replace('—', '-')
    (p / 'dataset-metadata.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    (p / 'VERSION_NOTES.txt').write_text('Initial public release.\nNHANES August 2021-August 2023; source snapshot retrieved October 13, 2026.\n82 public source tables, 11,933 participants, full data dictionary, codebooks, original XPT files, and validation records.\n51 reviewed source/codebook differences are retained and documented. 12 restricted or unavailable catalog entries are inventoried; their data are not included.\n')
    verify_artifacts(p, oldhash)
    if '—' in card or '—' in json.dumps(meta, ensure_ascii=False):
        raise ValueError('Unexpected em dash in publication prose')
    for path in {r['output_file'] for r in rows}:
        with (p / path).open(newline='') as f:
            header = next(csv.reader(f))
        if header != [r['output_column'] for r in rows if r['output_file'] == path]:
            raise ValueError(f'Dictionary/header mismatch: {path}')

def main(argv=None):
    import argparse
    import shutil
    import zipfile
    from .publication import prepare
    from .verification import archive_hashes, compare
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Archived validated October 13, 2026 build or unzipped Version 1')
    parser.add_argument('--destination', type=Path, required=True, help='New package directory; ZIP is written beside it')
    parser.add_argument('--reference', type=Path, required=True, help='Published per-file SHA-256 JSON')
    args = parser.parse_args(argv)
    (source, destination) = (args.source.resolve(), args.destination.resolve())
    if destination.exists() or destination.with_suffix('.zip').exists():
        raise ValueError('Destination or ZIP already exists')
    if source == destination or source in destination.parents:
        raise ValueError('Destination must be outside source')
    expected = json.loads(args.reference.read_text())
    destination.mkdir(parents=True)
    for directory in ('data', 'metadata', 'source'):
        shutil.copytree(source / directory, destination / directory)
    for name in ('catalog.json', 'manifest.json', 'build_report.json', 'validation.json', 'artifact_hashes.json'):
        shutil.copy2(source / name, destination / name)
    if json.loads((destination / 'manifest.json').read_text())['cycle'] != '2021-2023':
        raise ValueError('Expected the 2021-2023 cycle')
    prepare(destination)
    finalize(destination)
    checks = {str(f.relative_to(destination)): sha(f) for f in sorted(destination.rglob('*')) if f.is_file()}
    (destination / 'checksums.json').write_text(json.dumps(checks, indent=2) + '\n')
    zip_path = destination.with_suffix('.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(destination.rglob('*')):
            if file.is_file():
                archive.write(file, file.relative_to(destination))
    report = compare(expected, archive_hashes(zip_path))
    report_path = destination.with_name(destination.name + '-verification.json')
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for (k, v) in report.items() if k != 'file_sha256'}, indent=2))
    return 0 if report['passed'] else 1
if __name__ == '__main__':
    raise SystemExit(main())
