"""Read-only Kaggle downloads and exact archive-content verification."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
import zipfile

import requests


def archive_hashes(path):
    """Hash members without extracting or trusting archive paths."""
    with zipfile.ZipFile(path) as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        duplicates = [name for name, count in Counter(names).items() if count > 1]
        if duplicates:
            raise ValueError(f'Duplicate archive members: {duplicates}')
        result = {}
        for name in names:
            if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or '\\' in name:
                raise ValueError(f'Unsafe archive member: {name}')
            digest = hashlib.sha256()
            with archive.open(name) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            result[name] = digest.hexdigest()
        return result


def compare(expected, actual):
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    changed = sorted(name for name in expected.keys() & actual.keys() if expected[name] != actual[name])
    return {'passed': not (missing or extra or changed), 'expected_files': len(expected),
            'downloaded_files': len(actual), 'missing_files': missing,
            'extra_files': extra, 'changed_files': changed, 'file_sha256': actual}


def download(dataset, version, destination):
    """Download an explicitly selected public version. Never upload or authenticate."""
    parts = dataset.split('/')
    if len(parts) != 2 or any(not p or not all(c.isalnum() or c in '-_' for c in p) for p in parts):
        raise ValueError('Expected dataset owner/slug')
    if version < 1:
        raise ValueError('Version must be positive')
    url = f'https://www.kaggle.com/api/v1/datasets/download/{dataset}'
    with requests.get(url, params={'datasetVersionNumber': version}, stream=True, timeout=(15, 120)) as response:
        response.raise_for_status()
        with Path(destination).open('wb') as stream:
            for chunk in response.iter_content(1024 * 1024):
                stream.write(chunk)
    # HTTP 200 alone is not proof of a valid archive.
    if not zipfile.is_zipfile(destination):
        raise ValueError('Kaggle did not return a ZIP archive')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected', type=Path, required=True, help='Reference ZIP or per-file SHA-256 JSON')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--actual', type=Path, help='Downloaded ZIP')
    source.add_argument('--dataset', help='Public Kaggle owner/slug')
    parser.add_argument('--version', type=int, help='Required with --dataset')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.dataset and args.version is None:
        parser.error('--dataset requires an explicit --version')
    expected = json.loads(args.expected.read_text()) if args.expected.suffix == '.json' else archive_hashes(args.expected)
    with tempfile.TemporaryDirectory() as temporary:
        actual = args.actual or Path(temporary) / 'download.zip'
        if args.dataset:
            download(args.dataset, args.version, actual)
        report = compare(expected, archive_hashes(actual))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'file_sha256'}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
