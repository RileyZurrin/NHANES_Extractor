import csv
import json
from pathlib import Path
import pytest
from nhanes_extractor.publication import prepare
from nhanes_extractor.legacy_publication import DATASET_ID


def test_legacy_publication_targets_existing_dataset_and_maps_every_view_column(tmp_path):
    (tmp_path/'metadata').mkdir()
    (tmp_path/'data/tables').mkdir(parents=True)
    (tmp_path/'data/components').mkdir()
    def write_csv(relative, names, rows):
        with (tmp_path/relative).open('w',newline='') as f:
            w=csv.writer(f);w.writerow(names);w.writerows(rows)
    write_csv('data/tables/DEMO_J.csv',['SEQN','CODE'],[[1,'001']])
    write_csv('data/components/demographics.csv',['SEQN','DEMO_J__CODE'],[[1,'001']])
    write_csv('metadata/variables.csv',['file_id','variable','label','description','target','instructions','metadata_source'],[
        ['DEMO_J','SEQN','Participant ID','','','','CDC codebook'],
        ['DEMO_J','CODE','Example code','Keep leading zeros','Adults','','CDC codebook']])
    write_csv('metadata/column_mapping.csv',['output_file','output_column','file_id','variable'],[['data/components/demographics.csv','DEMO_J__CODE','DEMO_J','CODE']])
    for file in ('codes','sections','profiles'):write_csv(f'metadata/{file}.csv',['file_id','variable'],[])
    entry={'file_id':'DEMO_J','component':'demographics','data_url':'https://wwwn.cdc.gov/DEMO_J.xpt','doc_url':'https://wwwn.cdc.gov/DEMO_J.htm','character_columns':['CODE'],'column_names':['SEQN','CODE'],'csv_path':'data/tables/DEMO_J.csv','title':'Demographics','grain':'participant','rows':1}
    for file,data in [('manifest.json',{'cycle':'2017-2018','files':[entry]}),('validation.json',{'passed':True,'public_files':1,'participants':1,'participant_columns':2,'frequency_checks':3,'source_warnings':[]}),('catalog.json',{'release_url':'https://wwwn.cdc.gov/test','discovered_at':'2026-10-13'})]:
        (tmp_path/file).write_text(json.dumps(data))
    prepare(tmp_path)
    metadata=json.loads((tmp_path/'dataset-metadata.json').read_text())
    assert metadata['id']==DATASET_ID
    assert 'licenses' not in metadata  # Updating a version must not silently change the existing badge.
    resources={r['path']:r for r in metadata['resources']}
    fields=resources['data/components/demographics.csv']['schema']['fields']
    assert [f['name'] for f in fields]==['SEQN','DEMO_J__CODE']
    assert fields[1]['type']=='string' and 'Keep leading zeros' in fields[1]['description']
    with (tmp_path/'DATA_DICTIONARY.csv').open() as f: dictionary=list(csv.DictReader(f))
    assert [(r['output_column'],r['variable']) for r in dictionary]==[('SEQN','SEQN'),('DEMO_J__CODE','CODE')]
    assert 'GitHub' in metadata['description']
    assert (tmp_path/'VERSION_NOTES.txt').is_file()
    assert (tmp_path/'MIGRATION.md').is_file()


def test_publication_refuses_failed_validation(tmp_path):
    (tmp_path/'manifest.json').write_text('{"cycle":"2017-2018"}')
    (tmp_path/'validation.json').write_text('{"passed":false}')
    with pytest.raises(ValueError,match='Validate successfully'):prepare(tmp_path)
    assert not (tmp_path/'dataset-metadata.json').exists()
