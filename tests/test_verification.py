import hashlib
import json
import zipfile

import pytest

from nhanes_extractor.verification import archive_hashes, compare, main


def make_zip(path, files, compression=zipfile.ZIP_STORED):
    with zipfile.ZipFile(path, 'w', compression) as archive:
        for name, contents in files:
            archive.writestr(name, contents)


def test_recompression_does_not_change_verification(tmp_path):
    files = [('data/table.csv', 'SEQN,x\n1,0.001\n'), ('DATA_DICTIONARY.csv', 'name\nx\n')]
    a, b = tmp_path/'a.zip', tmp_path/'b.zip'
    make_zip(a, files)
    make_zip(b, files[::-1], zipfile.ZIP_DEFLATED)
    assert a.read_bytes() != b.read_bytes()
    assert compare(archive_hashes(a), archive_hashes(b))['passed']


def test_reports_missing_extra_and_changed_and_exits_nonzero(tmp_path):
    a, b, report = tmp_path/'a.zip', tmp_path/'b.zip', tmp_path/'report.json'
    make_zip(a, [('missing', 'x'), ('changed', 'old')])
    make_zip(b, [('extra', 'x'), ('changed', 'new')])
    assert main(['--expected', str(a), '--actual', str(b), '--report', str(report)]) == 1
    result = json.loads(report.read_text())
    assert result['missing_files'] == ['missing']
    assert result['extra_files'] == ['extra']
    assert result['changed_files'] == ['changed']


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'data\\escape'])
def test_unsafe_member_rejected_without_extraction(tmp_path, name):
    path = tmp_path/'bad.zip'
    make_zip(path, [(name, 'bad')])
    with pytest.raises(ValueError, match='Unsafe'):
        archive_hashes(path)


def test_duplicate_members_rejected(tmp_path):
    path = tmp_path/'duplicate.zip'
    with pytest.warns(UserWarning):
        make_zip(path, [('same', 'a'), ('same', 'b')])
    with pytest.raises(ValueError, match='Duplicate'):
        archive_hashes(path)


def test_json_reference_and_success_exit(tmp_path):
    path, reference, report = tmp_path/'a.zip', tmp_path/'reference.json', tmp_path/'report.json'
    make_zip(path, [('file', 'hello')])
    reference.write_text(json.dumps({'file': hashlib.sha256(b'hello').hexdigest()}))
    assert main(['--expected', str(reference), '--actual', str(path), '--report', str(report)]) == 0
