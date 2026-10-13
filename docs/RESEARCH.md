# NHANES 2021–2023 research and engineering decisions

Research date: 2026-10-13. Source catalogs are archived with each extraction.

## What “complete” can mean

The [cycle landing page](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/default.aspx?Cycle=2021-2023) links five public component catalogs plus limited access. On the research date these contain 82 downloadable tables: 1 demographics, 10 dietary, 4 examination, 32 laboratory, and 35 questionnaire. Another 12 files are RDC-only. Release notes explicitly describe staggered component releases; do not advertise all collected measurements as released. August 2026 additions include PFAS, cotinine/hydroxycotinine, and butyrylcholinesterase.

The [2017–March 2020 release](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/default.aspx?Cycle=2017-2020) combines the incomplete 2019–2020 cycle with 2017–2018. It is not an independent additional sample to append to 2017–2018. The 2025–2027 landing page currently has placeholder data links.

## File structure and parser rules

Catalog rows, not constructed suffixes or year arithmetic, are authoritative for URLs. Explicit cycle identifiers handle the two unusual periods. Query strings, relative links, shared reference files, updated dates and unavailable rows all need preservation. A requested cycle returning another page or an empty catalog is an error.

SAS XPORT is the raw format. Store original bytes with SHA-256 and retrieval receipts. Check XPORT magic before parsing: CDC can return an HTML response instead of data. Fail downloads rather than publish an incomplete set. Cache only files whose URL and checksum match; `--refresh` gets new snapshots.

Three table shapes matter: unique SEQN participant tables, repeated-SEQN tables, and lookup tables without SEQN. Infer shape from data, not filenames. The individual food records, dietary supplement records and reference dictionaries all belong in an exhaustive export. Duplicate names in merged views are namespaced to retain both source columns, even if their values happen to match. No forced many-to-many merges or first-non-null precedence.

The [general codebook documentation](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/doccontents.aspx) explains labels, English text, instructions, eligibility, hard edits, codes, counts and skip logic. Parse named `dt` fields, not positional assumptions. Preserve the full field dictionary and all code rows as strings, including ranges, decimals, negatives, character codes and missing tokens. Qualify metadata by file and cycle. Preserve full HTML plus narrative analytic sections and links to protocols.

## Material analytic changes

- [Sampling and weights](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/overviewbrief.aspx?Cycle=2021-2023): changed oversampling, declining response rates, additional phlebotomy weights, and a collection gap before this cycle. Keep design variables and every weight; do not select one globally.
- [PFAS](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/PFAS_L.htm): one-half subsample age 12+, its own WTSPF2YR weight, and detection-limit flags. Values below the detection limit already receive CDC fill values. Flags carry information and must survive.
- [Dietary totals](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/DR1TOT_L.htm) and [dietary mode-change paper](https://wwwn.cdc.gov/Nchs/data/Nhanes/Public/2021/Whitepapers/Aug2023-What-We-Eat-In-America-Dietary-Data-Whitepaper.pdf): recalls moved to telephone after the MEC exam. Use dietary weights and reliability fields.
- [Supplements](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/DSQIDS_L.htm): 30-day questions moved to the Day 1 phone interview; 24-hour supplement interviews were dropped. Individual and total tables differ in grain. DSBI/DSII/DSPI are cross-cycle product references served under 1999, deliberately linked from this cycle.
- [Prescription medications](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/RXQ_RX_L.htm): use and number categories remain, but names/duration/reasons are absent. The old dictionary exclusion silently lost these fields.
- [Limited access](https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=LimitedAccess&Cycle=2021-2023): youth depression/alcohol, sexual behavior and other restricted records have documentation but no public data. Inventory them without claiming to download them.

## Problems in the original implementation

The old scraper skips large and repeated-record files, omits lookup tables, drops lab comment codes, overwrites all values below a positive threshold (including legitimate negatives), coalesces duplicate columns without conflict checks, and logs per-file failures while still writing apparently finished output. Its dictionary has separate filename exclusions and infers a two-calendar-year folder name. The replacement uses one shared catalog and explicit validation gates.

## Validation strategy

Offline tests cover real HTML, URL variants, restricted rows, repeated records, conflicting columns, negative/tiny numbers, missing values, character codes and HTML masquerading as XPT. The full release run verifies source-codebook coverage, published categorical/range counts, participant membership, exact raw-to-CSV parsed values and every merged column. Failures must be investigated individually. Document any confirmed CDC inconsistency with narrowly scoped evidence rather than weakening checks globally.

## Kaggle landscape and publication

Kaggle's public dataset search already returns [CKD-NHANES 2021–2023: Staged Kidney Disease](https://www.kaggle.com/datasets/alitaqishah/ckd-nhanes-2021-2023-staged-kidney-disease), a kidney-focused derivative. Search results are not proof that no comprehensive mirror exists. Our distinguishing scope is preservation of all public tables, codebooks, original source files, explicit provenance, and reproducible validation.

Prepare a new dataset rather than silently replacing the 2017–2018 release. Metadata uses “other” and links the NCHS data-use terms instead of claiming that an export waives them. Include attribution, source availability, snapshot date and no-endorsement text. Upload/publishing is a separate action; no command in this extractor uploads to Kaggle.

## Full-run findings

The export contains 75 unique-SEQN source tables, three repeated-SEQN source tables, four lookup tables, and 12 restricted documentation entries. The combined participant view contains 11,933 rows and 1,112 columns, including the SEQN key.

The raw/codebook comparisons found 51 investigated source findings across DSBI, DSII, DSPI and FOLFMS_L (50 frequency/total disagreements plus one missing variable definition). An independent pandas XPORT reader confirmed the relevant row counts and values produced by ReadStat. Pandas strips trailing whitespace in some supplement character fields; the primary ReadStat export retains those characters. The exact two source hashes and individual findings are pinned in source_exceptions.json. They remain visible warnings in validation and the dataset description. An updated source invalidates these exceptions.

MCQ_L's codebook spells some variable names with lowercase suffixes while XPT uses uppercase. Match names case-insensitively to the actual schema and retain the original documented spelling. Three MCQ_L fields appear only in its codebook; preserve those definitions with in_data=false. FOLFMS_L's WTPH2YR definition is absent from its codebook: preserve the data column and its XPT label, clearly flagging the metadata source rather than inventing a definition.

Free-text codebook rows use “Value was recorded” and `< blank >` bins rather than literal category labels. Recorded counts exclude explicitly enumerated special string codes. All categories and original codebook text are retained.

Food-line keys are unique and all food IDs match the food lookup table. All supplement ingredient product IDs match the product table. The individual-supplement table has 165 rows with 147 distinct unknown-product identifiers that lack product lookup rows, consistent with the codebook's unknown-product conventions. It also has one duplicate `(SEQN, DSDPID)` pair for a don't-know record; do not use that pair as an assumed unique row key or deduplicate it. The exported relationship report documents these cases.

All 82 public files were also compared between ReadStat and pandas. This reproduced [pandas GH#50670](https://github.com/pandas-dev/pandas/issues/50670): pandas 2.3.3 decodes canonical IBM zero values as approximately 5.3976e-79. The audit corrects only exact encoded-zero bytes in its secondary reader, never a numerical magnitude range. After that narrow correction and normalization of trailing whitespace for the comparison only, all files agree (numeric relative tolerance 1e-12 and absolute tolerance zero). The primary exports use ReadStat and retain trailing character whitespace. This explains the likely motivation for the old threshold workaround while eliminating its negative-value corruption.

## 2017–2018 regression run

The [older release landing page](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/default.aspx?BeginYear=2017) and catalog use BeginYear/CycleBeginYear, unlike the newer Cycle parameter. A mismatched route can return a soft-404 with HTTP 200; the release-heading check correctly rejected it. SSEVD_J is explicitly withdrawn with disabled source links. Preserve that catalog row instead of guessing a download URL.

DRXFCD_J has narrative documentation rather than structured variable definitions. Preserve its sections and all three XPT variable labels, visibly marked as fallback metadata. RXQ_DRUG defines variables in a Position/Variable Name/Type/Length/Label table and inline category rows; parse those without pretending frequency counts exist.

All 133 public files pass independent-reader comparisons and exact CSV roundtrips. The 9,254-person combined view contains 2,623 columns. There are 19,176 codebook checks, with 71 reviewed source warnings: 46 from the same exact DSBI/DSII/DSPI source bytes seen in 2021–2023, 24 from DLQ_J, and one missing-definition finding covering DRXFCD_J's three fields. The DLQ_J XPT has 8,897 unique respondents, while all twelve response-variable frequency tables total 8,898. Both decoders agree on every value; the historical export has no nonempty disability responses outside the current roster. No respondent is fabricated to force agreement with the codebook. Exceptions remain exact-message, cycle- and two-hash-bound.

The full comparison to the original five component CSVs has no unmatched historical participants or omitted historical variable names. With legacy byte-string literals decoded only for comparison and coalesced names matched against their preserved source columns, all other differences are explained by 10,924 negative values previously zeroed and 12,772 previously blank hepatitis results now supplied by the public source. These are comparisons of historical exports with the current CDC snapshot, not claims that CDC data remained unchanged. The new laboratory view preserves 271 additional variable names. Comparison normalization never changes the actual export.

Both food recalls have unique participant/line keys and complete food-code lookup coverage. DSQIDS_J has 231 rows with unknown-product identifiers lacking lookup entries, consistent with its documented 6666666XXX convention, and two repeated participant/product pairs; retain these records unchanged.
