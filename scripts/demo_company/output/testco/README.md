# TestCo Demo Company

A complete synthetic demo company for Tablescope: structured datasets plus
unstructured business documents spanning every department. Everything is
generated from seeded pseudo-random data and is fully reproducible.

> All names, financials, employees, suppliers, and documents are fictional and
> for demonstration only.

## Profile
- **Company:** TestCo Demo Company
- **Industry:** Manufacturing
- **Size:** Enterprise (~820 employees, 4 sites)
- **Seed:** 42

## Contents
- **81 CSV datasets** (12,157 rows) under `data/<Department>/`
- **121 documents** under `docs/` (policies, procedures, executive
  reviews, and department business reports)

## Date Coverage
- Monthly tables run through **2026-07-01**.
- Weekly tables run through **2026-07-06**.
- Budget / forecast tables run through **2027-12-01**.

## Regenerate
```bash
python scripts/install_demo_company.py --company TestCo \
    --industry Manufacturing --size Enterprise --seed 42 \
    --generate-only
```

## Load into Tablescope
```bash
# Preview without calling the API
python scripts/install_demo_company.py --dry-run

# Small sample first, then everything (needs API base URL + owner credentials)
python scripts/install_demo_company.py --sample
python scripts/install_demo_company.py --all
```
The loader creates one Tablescope project per department (owned by the
configured user), uploads each CSV as a data source (which auto-creates a
saved query and triggers AI processing), and uploads each document as an
AI-processed business asset. It is idempotent and prints a summary report.

## Documentation
- `data_dictionary.md` — every dataset, its columns, row count and date range.
- `documents_dictionary.md` — every policy / procedure / review / report.
- `answer_key.md` — the planted AI-discoverable scenarios and how to find them.
