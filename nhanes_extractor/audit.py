"""Independent reader audit; does not alter the exported ReadStat data."""
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pandas.io.sas.sas_xport as pandas_xport

from .core import read_xpt, sha256


def audit(root, files):
    root = Path(root)
    results = []
    original_decoder = pandas_xport._parse_float_vec
    zero_count = 0

    def decode_exact_zero(vec):
        nonlocal zero_count
        result = original_decoder(vec)
        raw = np.ascontiguousarray(vec).view('u1').reshape(-1, 8)
        # pandas GH#50670. Test encoded zero bytes, never a magnitude threshold.
        zero = (raw[:, 1:] == 0).all(axis=1) & ((raw[:, 0] == 0) | (raw[:, 0] == 128))
        zero_count += int(zero.sum())
        result[zero] = np.copysign(0.0, np.where(raw[zero, 0] == 128, -1.0, 1.0))
        return result

    # The CLI is single-threaded at the conversion/audit stage; restore even on error.
    pandas_xport._parse_float_vec = decode_exact_zero
    try:
        for entry in files:
            if not entry['data_url']:
                continue
            fid = entry['file_id']
            path = root / 'source/xpt' / f'{fid}.xpt'
            left, meta = read_xpt(path)
            zero_count = 0
            right = pd.read_sas(path, format='xport', encoding=meta.file_encoding)
            whitespace = {}
            for column in left.select_dtypes('object'):
                whitespace[column] = int(left[column].ne(right[column]).sum())
                # pandas strips trailing whitespace; primary exports retain it.
                left[column] = left[column].str.rstrip()
                right[column] = right[column].str.rstrip()
            try:
                pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=False, rtol=1e-12, atol=0)
                passed, error = True, None
            except AssertionError as exc:
                passed, error = False, str(exc)[:500]
            results.append({'file_id': fid, 'rows': len(left), 'columns': len(left.columns), 'passed': passed,
                            'error': error, 'raw_sha256': sha256(path), 'pandas_exact_zero_encodings_corrected': zero_count,
                            'character_trailing_whitespace_differences': {k: v for k, v in whitespace.items() if v}})
            logging.getLogger(__name__).info('Independent reader check %s: %s', fid, passed)
    finally:
        pandas_xport._parse_float_vec = original_decoder
    return {'reader_comparison': f'ReadStat versus pandas {pd.__version__}; exact encoded-zero fix for pandas GH#50670; numeric rtol=1e-12, atol=0; trailing string whitespace normalized only for comparison',
            'passed': all(r['passed'] for r in results), 'files': results}
