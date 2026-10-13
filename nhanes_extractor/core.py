from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import numpy as np
import pandas as pd
import pyreadstat
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG = logging.getLogger(__name__)
BASE = 'https://wwwn.cdc.gov/nchs/nhanes/'
COMPONENTS = ('Demographics', 'Dietary', 'Examination', 'Laboratory', 'Questionnaire', 'LimitedAccess')
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?'


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    temp.replace(path)


def text(node):
    return ' '.join(node.stripped_strings) if node else ''


class Fetcher:
    """Atomic downloads, bounded retries, content validation, checksum-verified cache."""
    def __init__(self, refresh=False):
        self.refresh = refresh
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'NHANES-Extractor/2.0 (public research data archive)'
        retry = Retry(total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=['GET'])
        self.session.mount('https://', HTTPAdapter(max_retries=retry))

    def get(self, url, path, kind='html'):
        path = Path(path)
        receipt = path.with_suffix(path.suffix + '.receipt.json')
        if not self.refresh and path.exists() and receipt.exists():
            old = json.loads(receipt.read_text())
            if old['url'] == url and old['sha256'] == sha256(path):
                return old
        if urlparse(url).scheme != 'https' or not (urlparse(url).hostname or '').endswith('.cdc.gov'):
            raise ValueError(f'Unexpected data host: {url}')
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + '.part')
        try:
            with self.session.get(url, timeout=(20, 180), stream=True) as response:
                response.raise_for_status()
                with temp.open('wb') as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        stream.write(chunk)
                with temp.open('rb') as stream:
                    prefix = stream.read(160)
                if kind == 'xpt':
                    with temp.open('rb') as stream:
                        prefix = stream.read(160)
                    if not prefix.startswith(b'HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!'):
                        raise ValueError(f'Not an XPORT file (possibly an HTML error page): {url}')
                elif b'<' not in prefix:
                    raise ValueError(f'Not HTML: {url}')
                if temp.stat().st_size == 0:
                    raise ValueError(f'Empty response: {url}')
                result = {'url': url, 'resolved_url': response.url, 'retrieved_at': now(),
                          'bytes': temp.stat().st_size, 'sha256': sha256(temp),
                          'etag': response.headers.get('ETag'), 'last_modified': response.headers.get('Last-Modified')}
                temp.replace(path)
                write_json(receipt, result)
                return result
        finally:
            temp.unlink(missing_ok=True)


def parse_catalog(html, url, component):
    soup = BeautifulSoup(html, 'html.parser')
    records = []
    for tr in soup.select('tr'):
        cells = tr.find_all('td', recursive=False)
        if len(cells) < 4:
            continue
        doc_links = [a for a in cells[1].select('a[href]') if urlparse(a['href']).path.lower().endswith(('.htm', '.html'))]
        if not doc_links and text(cells[3]).lower() == 'withdrawn':
            match = re.fullmatch(r'([A-Za-z0-9_]+) Doc', text(cells[1]))
            if not match:
                raise ValueError('Unrecognized withdrawn file identifier')
            records.append({'file_id': match[1], 'component': component.lower(), 'title': text(cells[0]),
                            'doc_url': None, 'data_url': None, 'availability': 'unavailable',
                            'status': 'Withdrawn', 'published': text(cells[3]), 'catalog_url': url})
            continue
        if not doc_links:
            raise ValueError(f'Catalog row has no recognized documentation link: {text(cells[0])}')
        doc = urljoin(url, doc_links[0]['href'])
        file_id = Path(urlparse(doc).path).stem
        if not re.fullmatch(r'[A-Za-z0-9_]+', file_id):
            raise ValueError(f'Unsafe file ID {file_id}')
        links = [urljoin(url, a['href']) for a in cells[2].select('a[href]')]
        xpts = [u for u in links if urlparse(u).path.lower().endswith('.xpt')]
        if len(xpts) > 1:
            raise ValueError(f'Multiple XPT files in one catalog row: {file_id}')
        records.append({'file_id': file_id, 'component': component.lower(), 'title': text(cells[0]),
                        'doc_url': doc, 'data_url': xpts[0] if xpts else None,
                        'availability': 'public' if xpts else 'unavailable', 'status': text(cells[2]),
                        'published': text(cells[3]), 'catalog_url': url})
    if not records:
        raise ValueError(f'No catalog entries found: {url}; cycle unavailable or page structure changed')
    if len({r['file_id'] for r in records}) != len(records):
        raise ValueError(f'Duplicate file IDs in {component}')
    return records


def discover(root, cycle, refresh=False):
    if not re.fullmatch(r'\d{4}-\d{4}', cycle):
        raise ValueError('Use an explicit CDC cycle, e.g. 2021-2023 or 2017-2020')
    root = Path(root)
    fetcher = Fetcher(refresh)
    start, end = map(int, cycle.split('-'))
    legacy_cycle = end == start + 1
    home_query = f'BeginYear={start}' if legacy_cycle else f'Cycle={cycle}'
    catalog_query = f'CycleBeginYear={start}' if legacy_cycle else f'Cycle={cycle}'
    home_url = BASE + 'continuousnhanes/default.aspx?' + home_query
    home_path = root / 'source/catalogs/release.html'
    fetcher.get(home_url, home_path)
    soup = BeautifulSoup(home_path.read_text(), 'html.parser')
    title = text(soup.find('h1'))
    years = re.findall(r'\d{4}', title)
    if years != cycle.split('-'):
        raise ValueError(f'Requested {cycle} but CDC returned {title!r}')
    records = []
    for component in COMPONENTS:
        url = BASE + f'search/datapage.aspx?Component={component}&{catalog_query}'
        path = root / 'source/catalogs' / f'{component.lower()}.html'
        fetcher.get(url, path)
        records.extend(parse_catalog(path.read_text(), url, component))
    if len({r['file_id'] for r in records}) != len(records):
        raise ValueError('File IDs overlap across catalogs; explicit handling needed')
    catalog = {'schema_version': 1, 'cycle': cycle, 'title': title, 'discovered_at': now(), 'release_url': home_url, 'files': records}
    write_json(root / 'catalog.json', catalog)
    return catalog


def parse_codebook(html, allow_narrative=False):
    soup = BeautifulSoup(html, 'html.parser')
    variables, codes, sections = [], [], []
    for div in soup.select('div.pagebreak'):
        dl = div.find('dl')
        heading = div.find('h3')
        if not dl or not heading:
            continue
        fields = {}
        for dt in dl.find_all('dt'):
            dd = dt.find_next_sibling('dd')
            fields[text(dt).rstrip(':').strip()] = text(dd)
        name = fields.get('Variable Name')
        if not name:
            continue
        variables.append({'variable': name, 'label': fields.get('SAS Label', ''),
                          'description': fields.get('English Text', ''), 'instructions': fields.get('English Instructions', ''),
                          'target': fields.get('Target', ''), 'fields_json': json.dumps(fields, ensure_ascii=False)})
        for row in div.select('table.values tbody tr'):
            cells = row.find_all('td')
            if len(cells) >= 3:
                vals = [text(c) for c in cells]
                codes.append({'variable': name, 'code': vals[0], 'description': vals[1],
                              'count': vals[2], 'cumulative': vals[3] if len(vals) > 3 else '',
                              'skip_to': vals[4] if len(vals) > 4 else ''})
    if not variables:
        for table in soup.select('table'):
            headers = [text(h) for h in table.select('thead th')]
            if not {'Position', 'Variable Name', 'Type', 'Length', 'Label'}.issubset(headers):
                continue
            previous = None
            for row in table.select('tbody tr'):
                cells = [text(c) for c in row.find_all('td', recursive=False)]
                if len(cells) != len(headers):
                    continue
                fields = dict(zip(headers, cells))
                name = fields['Variable Name']
                if name:
                    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
                        raise ValueError(f'Invalid layout variable: {name}')
                    variables.append({'variable': name, 'label': fields['Label'], 'description': '',
                                      'instructions': '', 'target': '', 'fields_json': json.dumps(fields),
                                      'metadata_source': 'CDC documentation layout table'})
                    previous = name
                elif previous and '=' in fields['Label']:
                    code, description = fields['Label'].split('=', 1)
                    codes.append({'variable': previous, 'code': code.strip(), 'description': description.strip(),
                                  'count': '', 'cumulative': '', 'skip_to': ''})
    section_root = soup.find(id='Sections')
    if section_root:
        for heading in section_root.find_all('h2'):
            parts = []
            for sibling in heading.next_siblings:
                if getattr(sibling, 'name', None) == 'h2':
                    break
                if hasattr(sibling, 'stripped_strings'):
                    parts.append(text(sibling))
            sections.append({'section': text(heading), 'text': '\n'.join(parts), 'anchor': heading.get('id', '')})
    if not variables and not (allow_narrative and sections and soup.select_one('#PageHeader')):
        raise ValueError('No variable definitions found in codebook')
    if len({v['variable'] for v in variables}) != len(variables):
        raise ValueError('Duplicate variable definitions in codebook')
    dates = {text(h).split(':', 1)[0]: text(h).split(':', 1)[1].strip()
             for h in soup.select('#PageHeader h5') if ':' in text(h)}
    links = sorted({a['href'] for a in soup.select('#Sections a[href]')})
    return variables, codes, sections, dates, links


def download(root, catalog, refresh=False, workers=3):
    def one(record):
        fetcher = Fetcher(refresh)
        fid = record['file_id']
        if record['doc_url']:
            fetcher.get(record['doc_url'], root / 'source/codebooks' / f'{fid}.html')
        if record['data_url']:
            fetcher.get(record['data_url'], root / 'source/xpt' / f'{fid}.xpt', 'xpt')
        LOG.info('Downloaded/verified %s', fid)
    errors = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(one, r): r['file_id'] for r in catalog['files']}
        for job in as_completed(jobs):
            try:
                job.result()
            except Exception as exc:
                errors.append({'file_id': jobs[job], 'error': str(exc)})
                LOG.error('%s: %s', jobs[job], exc)
    write_json(root / 'download_errors.json', errors)
    if errors:
        raise ValueError(f'{len(errors)} download failures; rerun to resume')


def read_xpt(path):
    try:
        df, meta = pyreadstat.read_xport(str(path), encoding='UTF-8', disable_datetime_conversion=True)
        meta.file_encoding = 'UTF-8'
    except UnicodeDecodeError:
        # Legacy CDC XPORT labels and supplement strings contain Windows-1252 bytes.
        df, meta = pyreadstat.read_xport(str(path), encoding='WINDOWS-1252', disable_datetime_conversion=True)
        meta.file_encoding = 'WINDOWS-1252'
    if len(df.columns) != len(set(df.columns)):
        raise ValueError('Duplicate source columns')
    return df, meta


def grain(df):
    if 'SEQN' not in df:
        return 'lookup'
    if df.SEQN.isna().any() or not np.equal(df.SEQN, np.floor(df.SEQN)).all():
        raise ValueError('Invalid or missing participant ID')
    return 'participant_repeated' if df.SEQN.duplicated().any() else 'participant'


def frequency_checks(df, codes, file_id):
    """Compare published bins/counts against raw values; never recode source data."""
    issues, checked = [], 0
    grouped = {}
    for code in codes:
        grouped.setdefault(code['variable'], []).append(code)
    for name, rows in grouped.items():
        if name not in df:
            continue
        series = df[name]
        counts = [r['count'].replace(',', '') for r in rows]
        if all(c.isdigit() for c in counts):
            total = sum(map(int, counts))
            checked += 1
            if total != len(df):
                issues.append(f'{file_id}.{name}: codebook total {total} != rows {len(df)}')
        for row in rows:
            code = row['code'].strip()
            count = row['count'].replace(',', '')
            if not count.isdigit():
                continue
            observed = None
            if code == '.' or re.sub(r'\s+', '', code).lower() == '<blank>':
                observed = int((series.isna() | series.eq('')).sum())
            elif row['description'].lower() == 'value was recorded':
                special = [r['code'] for r in rows if r['description'].lower() != 'value was recorded'
                           and r['code'] != '.' and re.sub(r'\s+', '', r['code']).lower() != '<blank>']
                observed = int((series.notna() & series.ne('') & ~series.isin(special)).sum())
            elif pd.api.types.is_numeric_dtype(series) and re.fullmatch(NUMBER, code):
                observed = int(series.eq(float(code)).sum())
            elif pd.api.types.is_numeric_dtype(series):
                match = re.fullmatch(f'({NUMBER})\\s+to\\s+({NUMBER})', code, flags=re.I)
                if match:
                    lo, hi = map(float, match.groups())
                    # Published endpoints can round the original measurement.
                    observed = int(series.between(lo - max(abs(lo), 1)*1e-10, hi + max(abs(hi), 1)*1e-10).sum())
            elif row['description'].lower() != 'range of values' and code not in ('', 'Value was recorded'):
                observed = int(series.eq(code).sum())
            if observed is not None:
                checked += 1
                if observed != int(count):
                    issues.append(f'{file_id}.{name} [{code}]: observed {observed}, documented {count}')
    return checked, issues


def save_csv(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator='\n')


def merge_participants(tables, index):
    """No row multiplication and no first-non-null conflict resolution."""
    counts = Counter(c for _, frame in tables for c in frame if c != 'SEQN')
    pieces, mapping = [], []
    for fid, frame in tables:
        if grain(frame) != 'participant':
            raise ValueError(f'{fid}: repeated/lookup table cannot enter a participant join')
        rename = {c: f'{fid}__{c}' if counts[c] > 1 else c for c in frame if c != 'SEQN'}
        pieces.append(frame.set_index('SEQN').rename(columns=rename).reindex(index))
        mapping.extend({'file_id': fid, 'variable': c, 'output_column': out} for c, out in rename.items())
    merged = pd.concat(pieces, axis=1) if pieces else pd.DataFrame(index=index)
    if not merged.columns.is_unique:
        raise ValueError('Namespaced output columns collide')
    merged.index.name = 'SEQN'
    return merged.reset_index(), mapping


def relationship_checks(root, file_ids):
    """Validate documented food/product links without inventing a supplement row key."""
    findings, errors = [], []
    suffixes = sorted({fid.rsplit('_', 1)[1] for fid in file_ids if fid.startswith('DR1IFF_') or fid.startswith('DSQIDS_')})
    pairs = [('DSII', 'DSDPID', 'DSPI', 'DSDPID')]
    for suffix in suffixes:
        pairs.extend([(f'DR1IFF_{suffix}', 'DR1IFDCD', f'DRXFCD_{suffix}', 'DRXFDCD'),
                      (f'DR2IFF_{suffix}', 'DR2IFDCD', f'DRXFCD_{suffix}', 'DRXFDCD'),
                      (f'DSQIDS_{suffix}', 'DSDPID', 'DSPI', 'DSDPID')])
    for source, key, lookup, target in pairs:
        if source not in file_ids or lookup not in file_ids:
            continue
        left = pd.read_csv(root / 'data/tables' / f'{source}.csv', usecols=[key])[key]
        right = pd.read_csv(root / 'data/tables' / f'{lookup}.csv', usecols=[target])[target]
        if right.isna().any() or right.duplicated().any():
            errors.append(f'{lookup}.{target}: lookup key not unique/nonmissing')
        missing = left[left.notna() & ~left.isin(right)]
        codes = sorted({str(int(v)) for v in missing})
        documented_unknowns = source.startswith('DSQIDS_') and all(c.startswith('666666') for c in codes)
        if codes and not documented_unknowns:
            errors.append(f'{source}.{key}: unmatched lookup IDs {codes[:10]}')
        findings.append({'source_file': source, 'key': key, 'lookup_file': lookup, 'lookup_key': target,
                         'unmatched_rows': len(missing), 'unmatched_ids': codes,
                         'note': 'CDC unknown-product IDs intentionally have no product lookup entry; preserve them.' if codes and documented_unknowns else 'All nonmissing keys matched.'})
    candidates = [(f'{base}_{suffix}', keys) for suffix in suffixes for base, keys in
                  [('DR1IFF', ['SEQN', 'DR1ILINE']), ('DR2IFF', ['SEQN', 'DR2ILINE']), ('DSQIDS', ['SEQN', 'DSDPID'])]]
    for fid, keys in candidates:
        if fid not in file_ids:
            continue
        df = pd.read_csv(root / 'data/tables' / f'{fid}.csv', usecols=keys)
        duplicates = int(df.duplicated(keys).sum())
        if not fid.startswith('DSQIDS_') and (duplicates or df.isna().any().any()):
            errors.append(f'{fid}: invalid participant/food-line key')
        findings.append({'source_file': fid, 'candidate_key': keys, 'duplicate_rows': duplicates,
                         'note': 'Supplement product IDs are not guaranteed to distinguish every reported record; no deduplication.' if fid.startswith('DSQIDS_') else 'Participant and food-line key checked.'})
    return findings, errors


def build(root, catalog):
    out = root / 'data'
    marker = root / '.nhanes-generated'
    if out.exists() and not marker.exists():
        raise ValueError('Refusing to replace an unmarked data directory')
    marker.write_text('Generated NHANES export; data/ is rebuilt from source XPT files.\n')
    if out.exists():
        shutil.rmtree(out)  # Generated files only, to prevent stale exports on a refreshed catalog.
    metadata = root / 'metadata'
    metadata.mkdir(exist_ok=True)
    variables, codes, sections, summaries, validation_errors = [], [], [], [], []
    participant_tables = []
    manifest = []
    frequency_count = 0
    for record in catalog['files']:
        fid = record['file_id']
        LOG.info('Converting %s', fid)
        identity = {'cycle': catalog['cycle'], 'component': record['component'], 'file_id': fid}
        doc_path = root / 'source/codebooks' / f'{fid}.html'
        kind = None
        if record['data_url']:
            raw_path = root / 'source/xpt' / f'{fid}.xpt'
            df, meta = read_xpt(raw_path)
            kind = grain(df)
        if record['doc_url']:
            v, c, s, dates, links = parse_codebook(doc_path.read_text(), allow_narrative=kind == 'lookup')
        else:
            v, c, s, dates, links = [], [], [], {}, []
        sections.extend({**identity, **row} for row in s)
        entry = {**record, **dates, 'doc_sha256': sha256(doc_path) if record['doc_url'] else None, 'reference_links': [urljoin(record['doc_url'], u) for u in links]}
        if record['data_url']:
            table_path = out / 'tables' / f'{fid}.csv'
            save_csv(df, table_path)
            actual_names = {name.casefold(): name for name in df.columns}
            if len(actual_names) != len(df.columns):
                raise ValueError(f'{fid}: case-insensitive source column collision')
            for row in v + c:
                row['documented_variable'] = row['variable']
                row['variable'] = actual_names.get(row['variable'].casefold(), row['variable'])
            var_names = {row['variable'] for row in v}
            if len(var_names) != len(v):
                raise ValueError(f'{fid}: codebook variable names collide after case normalization')
            missing_docs = sorted(set(df.columns) - var_names)
            if missing_docs:
                validation_errors.append(f'{fid}: undocumented columns {missing_docs}')
                for name in missing_docs:
                    v.append({'variable': name, 'documented_variable': '', 'label': meta.column_names_to_labels.get(name, ''),
                              'description': '', 'instructions': '', 'target': '', 'fields_json': '{}',
                              'metadata_source': 'XPT label only; absent from CDC codebook'})
            for row in v:
                row.setdefault('metadata_source', 'CDC codebook')
            entry['documented_only_variables'] = sorted(var_names - set(df.columns))
            for row in v:
                row['in_data'] = row['variable'] in df
            n, issues = frequency_checks(df, c, fid)
            frequency_count += n
            validation_errors.extend(issues)
            entry.update({'grain': kind, 'rows': len(df), 'columns': len(df.columns),
                          'unique_participants': int(df.SEQN.nunique()) if 'SEQN' in df else None,
                          'raw_sha256': sha256(raw_path), 'raw_bytes': raw_path.stat().st_size,
                          'csv_sha256': sha256(table_path), 'csv_path': str(table_path.relative_to(root)),
                          'column_names': list(df.columns), 'character_columns': [c for c in df if df[c].dtype == object],
                          'source_encoding': meta.file_encoding, 'sas_labels': meta.column_names_to_labels})
            for name in df:
                col = df[name]
                summaries.append({**identity, 'variable': name, 'dtype': str(col.dtype), 'rows': len(df),
                                  'missing': int((col.isna() | col.eq('')).sum()), 'unique': int(col.nunique()),
                                  'negative': int((col < 0).sum()) if pd.api.types.is_numeric_dtype(col) else None})
            if kind == 'participant':
                participant_tables.append((fid, record['component'], df))
        else:
            entry['grain'] = 'unavailable'
            for row in v:
                row['in_data'] = False
        variables.extend({**identity, **row} for row in v)
        codes.extend({**identity, **row} for row in c)
        manifest.append(entry)
    demo = [df for _, component, df in participant_tables if component == 'demographics']
    if len(demo) != 1:
        raise ValueError('Expected one demographics participant roster')
    index = pd.Index(demo[0].SEQN, name='SEQN')
    for entry in manifest:
        if entry.get('data_url') and entry['grain'].startswith('participant'):
            ids = pd.read_csv(root / entry['csv_path'], usecols=['SEQN']).SEQN
            outside = set(ids) - set(index)
            if outside:
                validation_errors.append(f'{entry["file_id"]}: {len(outside)} IDs outside demographics')
    mappings = []
    for component in [c.lower() for c in COMPONENTS[:5]]:
        tables = [(fid, df) for fid, comp, df in participant_tables if comp == component]
        merged, mapping = merge_participants(tables, index)
        path = out / 'components' / f'{component}.csv'
        save_csv(merged, path)
        mappings.extend({**row, 'output_file': str(path.relative_to(root))} for row in mapping)
    merged, mapping = merge_participants([(fid, df) for fid, _, df in participant_tables], index)
    path = out / 'participants.csv'
    save_csv(merged, path)
    mappings.extend({**row, 'output_file': str(path.relative_to(root))} for row in mapping)
    for name, rows in [('variables', variables), ('codes', codes), ('sections', sections), ('profiles', summaries), ('column_mapping', mappings)]:
        save_csv(pd.DataFrame(rows), metadata / f'{name}.csv')
    relations, relationship_errors = relationship_checks(root, {r['file_id'] for r in manifest if r['data_url']})
    validation_errors.extend(relationship_errors)
    write_json(metadata / 'relationships.json', relations)
    write_json(root / 'manifest.json', {'cycle': catalog['cycle'], 'built_at': now(), 'files': manifest})
    from .audit import audit
    independent = audit(root, manifest)
    write_json(metadata / 'independent_readers.json', independent)
    validation_errors.extend(f"{r['file_id']}: independent reader mismatch: {r['error']}" for r in independent['files'] if not r['passed'])
    report = {'independent_reader_files': len(independent['files']), 'frequency_checks': frequency_count, 'errors': validation_errors, 'participants': len(index),
              'participant_columns': len(merged.columns), 'public_files': sum(bool(r['data_url']) for r in manifest),
              'unavailable_files': sum(not r['data_url'] for r in manifest), 'grains': dict(Counter(r['grain'] for r in manifest))}
    write_json(root / 'build_report.json', report)
    inventory = {str(p.relative_to(root)): sha256(p) for folder in ('data', 'metadata')
                 for p in sorted((root / folder).rglob('*')) if p.is_file() and p.name != 'source_discrepancies.json'}
    for name in ('catalog.json', 'manifest.json', 'build_report.json'):
        inventory[name] = sha256(root / name)
    write_json(root / 'artifact_hashes.json', inventory)
    return report


def classify_source_issues(issues, manifest, cycle, rules=None):
    """Only exact investigated discrepancies on exact source bytes become warnings."""
    if rules is None:
        rules = json.loads(Path(__file__).with_name('source_exceptions.json').read_text())
    files = {r['file_id']: r for r in manifest}
    accepted = {}
    for rule in rules:
        entry = files.get(rule['file_id'], {})
        if (rule['cycle'] == cycle and entry.get('raw_sha256') == rule['raw_sha256']
                and entry.get('doc_sha256') == rule['doc_sha256']):
            for issue in rule['issues']:
                accepted[issue] = rule
    errors, warnings = [], []
    for issue in issues:
        if issue in accepted:
            rule = accepted[issue]
            warnings.append({'issue': issue, 'file_id': rule['file_id'], 'explanation': rule['explanation'],
                             'raw_sha256': rule['raw_sha256'], 'doc_sha256': rule['doc_sha256']})
        else:
            errors.append(issue)
    return errors, warnings


def validate(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    report = json.loads((root / 'build_report.json').read_text())
    errors, source_warnings = classify_source_issues(report['errors'], manifest['files'], manifest['cycle'])
    inventory = json.loads((root / 'artifact_hashes.json').read_text())
    for relative, expected in inventory.items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            errors.append(f'{relative}: artifact missing or checksum changed')
    catalog = json.loads((root / 'catalog.json').read_text())
    if {r['file_id'] for r in catalog['files']} != {r['file_id'] for r in manifest['files']}:
        errors.append('Catalog and manifest file coverage differ')
    roundtrips = 0
    for entry in manifest['files']:
        fid = entry['file_id']
        doc_path = root / 'source/codebooks' / f'{fid}.html'
        if entry['doc_url'] and (not doc_path.exists() or sha256(doc_path) != entry['doc_sha256']):
            errors.append(f'{fid}: documentation checksum changed')
        if not entry['data_url']:
            continue
        raw_path = root / 'source/xpt' / f'{fid}.xpt'
        csv_path = root / entry['csv_path']
        if sha256(raw_path) != entry['raw_sha256'] or sha256(csv_path) != entry['csv_sha256']:
            errors.append(f'{fid}: raw/export checksum changed')
        raw, _ = read_xpt(raw_path)
        # Character codes such as NA and leading zeros must not become numbers/nulls.
        dtypes = {col: str if raw[col].dtype == object else 'float64' for col in raw}
        exported = pd.read_csv(csv_path, dtype=dtypes, keep_default_na=False,
                               na_values={col: [''] for col in raw if raw[col].dtype != object}, float_precision='round_trip')
        try:
            pd.testing.assert_frame_equal(raw, exported, check_dtype=False, check_exact=True)
        except AssertionError as exc:
            errors.append(f'{fid}: CSV roundtrip differs: {str(exc)[:250]}')
        roundtrips += 1
    # Verify every merged column against its source, including added missing participant rows.
    mapping = pd.read_csv(root / 'metadata/column_mapping.csv', keep_default_na=False)
    schemas = {r['file_id']: r for r in manifest['files']}
    for output_file, rows in mapping.groupby('output_file'):
        chars = [r.output_column for r in rows.itertuples() if r.variable in schemas[r.file_id].get('character_columns', [])]
        numeric = [r.output_column for r in rows.itertuples() if r.output_column not in chars] + ['SEQN']
        merged = pd.read_csv(root / output_file, float_precision='round_trip', keep_default_na=False,
                             dtype={c: str for c in chars}, na_values={c: [''] for c in numeric})
        if merged.SEQN.duplicated().any() or len(merged) != report['participants']:
            errors.append(f'{output_file}: participant cardinality changed')
        merged = merged.set_index('SEQN')
        for fid, cols in rows.groupby('file_id'):
            source, _ = read_xpt(root / 'source/xpt' / f'{fid}.xpt')
            source = source.set_index('SEQN').reindex(merged.index)
            for row in cols.itertuples():
                try:
                    pd.testing.assert_series_equal(source[row.variable].fillna('') if row.output_column in chars else source[row.variable], merged[row.output_column], check_names=False, check_dtype=False, check_exact=True)
                except AssertionError as exc:
                    errors.append(f'{output_file}.{row.output_column}: merged values differ: {str(exc)[:150]}')
    result = {**report, 'source_warnings': source_warnings, 'validated_at': now(), 'raw_csv_roundtrips': roundtrips, 'errors': errors, 'passed': not errors}
    write_json(root / 'validation.json', result)
    write_json(root / 'metadata/source_discrepancies.json', source_warnings)
    if errors:
        LOG.error('Validation failed with %d issues; see validation.json', len(errors))
    return result


def package(root, destination):
    result = validate(root)
    if not result['passed']:
        raise ValueError('Publication blocked: validation did not pass')
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Package destination already exists; choose a new path')
    required = ('catalog.json', 'manifest.json', 'build_report.json', 'validation.json', 'artifact_hashes.json', 'README.md', 'dataset-metadata.json')
    for filename in required:
        if not (root / filename).is_file():
            raise ValueError(f'Missing publication file: {filename}')
    if destination == root.resolve() or root.resolve() in destination.parents:
        raise ValueError('Package destination must be outside the source release directory')
    destination.mkdir(parents=True)
    # Include all source evidence, all tables, metadata and validation. No credentials or executable code.
    for directory in ('data', 'metadata', 'source'):
        shutil.copytree(root / directory, destination / directory)
    for filename in required:
        source = root / filename
        if not source.exists():
            raise ValueError(f'Missing publication file: {filename}')
        shutil.copy2(source, destination / filename)
    for filename in ('DATA_DICTIONARY.csv', 'MIGRATION.md', 'VERSION_NOTES.txt'):
        if (root / filename).is_file():
            shutil.copy2(root / filename, destination / filename)
    checksums = {str(p.relative_to(destination)): sha256(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    write_json(destination / 'checksums.json', checksums)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['discover', 'run', 'build', 'validate', 'prepare', 'package'])
    parser.add_argument('--cycle', default='2021-2023')
    parser.add_argument('--output', type=Path, default=None)
    parser.add_argument('--refresh', action='store_true', help='Re-fetch catalogs, documentation and raw files')
    parser.add_argument('--workers', type=int, default=3, choices=range(1, 7))
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    root = args.output or Path('artifacts') / args.cycle
    try:
        if args.command in ('discover', 'run'):
            catalog = discover(root, args.cycle, args.refresh)
            if args.command == 'discover':
                print(json.dumps(Counter(r['component'] for r in catalog['files']), indent=2))
                return 0
            download(root, catalog, args.refresh, args.workers)
        else:
            catalog = json.loads((root / 'catalog.json').read_text())
        if args.command in ('run', 'build'):
            build(root, catalog)
        if args.command in ('run', 'build', 'validate'):
            result = validate(root)
            print(json.dumps({k: v for k, v in result.items() if k not in ('errors', 'source_warnings')}, indent=2))
            return 0 if result['passed'] else 1
        if args.command == 'prepare':
            result = validate(root)
            if not result['passed']:
                raise ValueError('Publication blocked: validation did not pass')
            from .publication import prepare
            prepare(root)
        if args.command == 'package':
            if not args.destination:
                raise ValueError('--destination is required')
            print(package(root, args.destination))
        return 0
    except Exception as exc:
        LOG.exception('Extraction failed: %s', exc)
        return 1
