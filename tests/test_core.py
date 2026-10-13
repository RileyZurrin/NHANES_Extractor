from pathlib import Path
import json
import pandas as pd
import pytest
import pyreadstat
from nhanes_extractor.core import (parse_catalog, parse_codebook, grain, merge_participants,
                                   frequency_checks, read_xpt, Fetcher, sha256)


def test_live_demographics_fixture():
    variables, codes, sections, dates, links = parse_codebook((Path(__file__).parent / 'fixtures/DEMO_L.html').read_text())
    assert len(variables) == 27
    assert variables[0]['variable'] == 'SEQN'
    assert next(c for c in codes if c['variable'] == 'SDDSRVYR' and c['code'] == '12')['count'] == '11933'
    assert any(s['section'] == 'Analytic Notes' for s in sections)
    assert dates['First Published'] == 'September 2024'


def test_catalog_handles_query_strings_and_restricted_rows():
    html = '''<table><tr><td>Public</td><td><a href="/docs/X.htm">Doc</a></td>
    <td><a href="/data/X.XPT?download=1">Data</a></td><td>Updated April 2025</td></tr>
    <tr><td>Private</td><td><a href="/docs/Y.htm">Doc</a></td><td>RDC Only</td><td>2024</td></tr></table>'''
    rows = parse_catalog(html, 'https://wwwn.cdc.gov/catalog', 'Dietary')
    assert rows[0]['data_url'].endswith('X.XPT?download=1')
    assert rows[1]['data_url'] is None
    with pytest.raises(ValueError, match='No catalog'):
        parse_catalog('<h1>Error</h1>', 'https://wwwn.cdc.gov', 'Dietary')


def test_conflicting_columns_are_preserved_and_rows_do_not_multiply():
    a = pd.DataFrame({'SEQN': [1., 2.], 'WT': [1., 2.], 'X': [-3., 1e-35]})
    b = pd.DataFrame({'SEQN': [2., 3.], 'WT': [99., 4.]})
    merged, mapping = merge_participants([('A', a), ('B', b)], pd.Index([1., 2., 3., 4.]))
    assert len(merged) == 4
    assert merged.loc[1, 'A__WT'] == 2 and merged.loc[1, 'B__WT'] == 99
    assert merged.loc[0, 'X'] == -3 and merged.loc[1, 'X'] == 1e-35
    assert pd.isna(merged.loc[3, 'X'])
    with pytest.raises(ValueError, match='repeated'):
        merge_participants([('R', pd.DataFrame({'SEQN': [1., 1.]}))], pd.Index([1.]))


def test_grain_not_filename():
    assert grain(pd.DataFrame({'SEQN': [1, 1], 'FOOD': [2, 3]})) == 'participant_repeated'
    assert grain(pd.DataFrame({'PRODUCT': [1, 1]})) == 'lookup'
    assert grain(pd.DataFrame({'SEQN': [1, 2]})) == 'participant'
    with pytest.raises(ValueError, match='Invalid'):
        grain(pd.DataFrame({'SEQN': [1, None]}))


def test_frequency_validator_catches_value_and_row_loss():
    df = pd.DataFrame({'A': [-1., 2., None]})
    codes = [{'variable': 'A', 'code': c, 'description': '', 'count': n} for c, n in [('-1','1'), ('2','1'), ('.','1')]]
    assert frequency_checks(df, codes, 'X')[1] == []
    df.loc[0, 'A'] = 0
    assert any('[-1]' in e for e in frequency_checks(df, codes, 'X')[1])
    assert any('total' in e for e in frequency_checks(df.iloc[:2], codes, 'X')[1])


def test_xport_preserves_negatives_tiny_numbers_and_character_codes(tmp_path):
    df = pd.DataFrame({'SEQN': [1., 2., 3.], 'VALUE': [-2.5, 1e-35, float('nan')], 'CODE': ['001', 'NA', '']})
    path = tmp_path / 'test.xpt'
    pyreadstat.write_xport(df, str(path), file_format_version=5)
    result, _ = read_xpt(path)
    assert result.VALUE.iloc[0] == -2.5
    assert result.VALUE.iloc[1] == pytest.approx(1e-35, rel=1e-14, abs=0)
    assert result.CODE.tolist() == ['001', 'NA', '']
    assert pd.isna(result.VALUE.iloc[2])


def test_bad_download_does_not_replace_existing_file(tmp_path):
    class Response:
        url = 'https://wwwn.cdc.gov/bad.xpt'
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, size): yield b'<html>Temporarily unavailable</html>'
    class Session:
        def get(self, *args, **kwargs): return Response()
    fetcher = Fetcher(refresh=True)
    fetcher.session = Session()
    path = tmp_path / 'test.xpt'
    path.write_bytes(b'old')
    with pytest.raises(ValueError, match='Not an XPORT'):
        fetcher.get(Response.url, path, 'xpt')
    assert path.read_bytes() == b'old'
    assert not path.with_suffix('.xpt.part').exists()


def test_checksum_cache_requires_matching_url_and_bytes(tmp_path):
    path = tmp_path / 'doc.html'
    path.write_text('<html>verified</html>')
    receipt = {'url': 'https://wwwn.cdc.gov/doc.html', 'sha256': sha256(path)}
    path.with_suffix('.html.receipt.json').write_text(json.dumps(receipt))
    fetcher = Fetcher()
    assert fetcher.get(receipt['url'], path) == receipt


def test_legacy_windows_label_decodes_without_replacement(tmp_path):
    path = tmp_path / 'legacy.xpt'
    pyreadstat.write_xport(pd.DataFrame({'X': [1.]}), str(path), file_format_version=5, column_labels={"X": "Person's value"})
    path.write_bytes(path.read_bytes().replace(b"Person's value", b'Person\x92s value'))
    frame, meta = read_xpt(path)
    assert meta.file_encoding == 'WINDOWS-1252'
    assert meta.column_names_to_labels['X'] == 'Person’s value'


def test_character_codebook_recorded_and_blank_bins():
    frame = pd.DataFrame({'TIME': ['22:00', '23:10', '77777', '']})
    codes = [{'variable': 'TIME', 'code': code, 'description': desc, 'count': n} for code, desc, n in [
        ('Usual sleep time', 'Value was recorded', '2'), ('77777', 'Refused', '1'), ('< blank >', 'Missing', '1')]]
    assert frequency_checks(frame, codes, 'SLEEP')[1] == []


def test_source_exceptions_are_exact_and_bound_to_both_hashes():
    from nhanes_extractor.core import classify_source_issues
    rule = {'file_id': 'F', 'cycle': '2021-2023', 'raw_sha256': 'raw', 'doc_sha256': 'doc', 'issues': ['F.X: mismatch'], 'explanation': 'independently verified'}
    entry = {'file_id': 'F', 'raw_sha256': 'raw', 'doc_sha256': 'doc'}
    errors, warnings = classify_source_issues(['F.X: mismatch', 'F.Y: new mismatch'], [entry], '2021-2023', [rule])
    assert errors == ['F.Y: new mismatch'] and len(warnings) == 1
    for key in ('raw_sha256', 'doc_sha256'):
        altered = {**entry, key: 'changed'}
        errors, warnings = classify_source_issues(['F.X: mismatch'], [altered], '2021-2023', [rule])
        assert errors == ['F.X: mismatch'] and warnings == []


def test_offline_release_roundtrip_and_tamper_gate(tmp_path):
    from nhanes_extractor.core import build, validate, write_json, package
    def documentation(names):
        return '<div id="Codebook">' + ''.join(
            f'<div class="pagebreak"><h3>{name}</h3><dl><dt>Variable Name:</dt><dd>{name}</dd><dt>SAS Label:</dt><dd>{name}</dd></dl></div>' for name in names) + '</div>'
    sources = [
        ('DEMO', 'demographics', pd.DataFrame({'SEQN': [1.,2.,3.], 'AGE': [20.,30.,40.]})),
        ('EXAM', 'examination', pd.DataFrame({'SEQN': [1.,2.], 'CODE': ['001','NA'], 'NEG': [-2.,1e-35]})),
        ('FOOD', 'dietary', pd.DataFrame({'SEQN': [1.,1.], 'VALUE': [2.,3.]})),
        ('LOOKUP', 'dietary', pd.DataFrame({'KEY': ['001','NA'], 'VALUE': [2.,3.]})),
    ]
    (tmp_path/'source/xpt').mkdir(parents=True)
    (tmp_path/'source/codebooks').mkdir()
    records=[]
    for fid, component, frame in sources:
        pyreadstat.write_xport(frame, str(tmp_path/'source/xpt'/f'{fid}.xpt'), file_format_version=5)
        (tmp_path/'source/codebooks'/f'{fid}.html').write_text(documentation(frame.columns))
        records.append({'file_id':fid,'component':component,'data_url':f'https://wwwn.cdc.gov/{fid}.xpt','doc_url':f'https://wwwn.cdc.gov/{fid}.htm'})
    records.append({'file_id':'WITHDRAWN','component':'laboratory','data_url':None,'doc_url':None,'status':'Withdrawn'})
    catalog={'cycle':'2021-2023','files':records}
    write_json(tmp_path/'catalog.json',catalog)
    report=build(tmp_path,catalog)
    assert report['grains'] == {'participant':2,'participant_repeated':1,'lookup':1,'unavailable':1}
    assert validate(tmp_path)['passed']
    # Mutating even metadata must block packaging, not merely source CSV mutations.
    with (tmp_path/'metadata/codes.csv').open('a') as stream:stream.write('corrupt\n')
    result=validate(tmp_path)
    assert not result['passed']
    assert any('codes.csv' in e for e in result['errors'])
    with pytest.raises(ValueError,match='Publication blocked'):
        package(tmp_path,tmp_path.parent/'must-not-be-published')
    assert not (tmp_path.parent/'must-not-be-published').exists()


def test_withdrawn_catalog_entry_has_no_download_urls():
    from nhanes_extractor.core import parse_catalog
    html = '<table><tr><td>Withdrawn assay</td><td>SSEVD_J Doc</td><td>SSEVD_J Data</td><td>Withdrawn</td></tr></table>'
    record = parse_catalog(html, 'https://wwwn.cdc.gov/catalog', 'Laboratory')[0]
    assert record['file_id'] == 'SSEVD_J'
    assert record['doc_url'] is None and record['data_url'] is None
    assert record['status'] == 'Withdrawn'
    with pytest.raises(ValueError):
        parse_catalog(html.replace('Withdrawn</td>', 'Updated</td>'), 'https://wwwn.cdc.gov/catalog', 'Laboratory')


@pytest.mark.parametrize('cycle,home,catalog', [('2017-2018','BeginYear=2017','CycleBeginYear=2017'), ('2021-2023','Cycle=2021-2023','Cycle=2021-2023')])
def test_discovery_cycle_routing(tmp_path, monkeypatch, cycle, home, catalog):
    import nhanes_extractor.core as core
    urls = []
    def get(self, url, path, kind='html'):
        urls.append(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        if 'default.aspx' in url:
            path.write_text(f'<h1>NHANES {cycle}</h1>')
        else:
            fid = str(len(urls))
            path.write_text(f'<table><tr><td>Assay</td><td><a href="/{fid}.htm">Doc</a></td><td>RDC Only</td><td>2020</td></tr></table>')
    monkeypatch.setattr(core.Fetcher, 'get', get)
    result = core.discover(tmp_path, cycle)
    assert urls[0].endswith(home)
    assert all(url.endswith(catalog) for url in urls[1:])
    assert len(result['files']) == 6


def test_legacy_food_relationships(tmp_path):
    from nhanes_extractor.core import relationship_checks
    folder = tmp_path/'data/tables'
    folder.mkdir(parents=True)
    pd.DataFrame({'SEQN':[1,1], 'DR1ILINE':[1,2], 'DR1IFDCD':[10,99]}).to_csv(folder/'DR1IFF_J.csv',index=False)
    pd.DataFrame({'DRXFDCD':[10]}).to_csv(folder/'DRXFCD_J.csv',index=False)
    findings, errors = relationship_checks(tmp_path, {'DR1IFF_J','DRXFCD_J'})
    assert any('unmatched lookup IDs' in error for error in errors)
    assert findings[0]['unmatched_rows'] == 1


def test_legacy_layout_and_narrative_metadata():
    html = '<table><thead><tr><th>Position</th><th>Variable Name</th><th>Type</th><th>Length</th><th>Label</th></tr></thead><tbody><tr><td>1</td><td>FLAG</td><td>Num</td><td>8</td><td>Flag label</td></tr><tr><td></td><td></td><td></td><td></td><td>0=Unspecified</td></tr></tbody></table>'
    variables, codes, *_ = parse_codebook(html)
    assert variables[0]['variable'] == 'FLAG'
    assert variables[0]['metadata_source'] == 'CDC documentation layout table'
    assert codes[0]['code'] == '0' and codes[0]['count'] == ''
    narrative = '<div id="PageHeader">Lookup</div><div id="Sections"><h2>Documentation</h2><p>Food codes.</p></div>'
    assert parse_codebook(narrative, allow_narrative=True)[0] == []
    with pytest.raises(ValueError): parse_codebook(narrative)
    with pytest.raises(ValueError): parse_codebook('<h1>Error page</h1>', allow_narrative=True)
