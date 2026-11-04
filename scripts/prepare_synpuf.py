"""Derive the small, committed DE-SynPUF extract used by the healthcare incidents.

Source (public domain, U.S. Government work, synthetic, no PHI): CMS 2008-2010 Data Entrepreneurs'
Synthetic Public Use File (DE-SynPUF), Sample 1: 2009 Beneficiary Summary and 2008-2010 Inpatient Claims.
https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files

Usage: python scripts/prepare_synpuf.py   (raw zips in data/private/synpuf/, which is git-ignored)
Writes examples/synpuf/inpatient_extract.json with claims whose service start falls in two windows
around May and November 2009, plus the beneficiary attributes those incidents need.
"""

import csv
import io
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "private" / "synpuf"
WINDOWS = [("20090425", "20090606"), ("20091025", "20091206")]


def _rows(name):
    with zipfile.ZipFile(RAW / name) as archive:
        with archive.open(archive.namelist()[0]) as handle:
            yield from csv.DictReader(io.TextIOWrapper(handle, encoding="latin-1"))


def main():
    claims = []
    for row in _rows("de1_0_2008_to_2010_inpatient_claims_sample_1.zip"):
        start = row["CLM_FROM_DT"]
        if any(lo <= start <= hi for lo, hi in WINDOWS):
            claims.append({"clm_id": int(row["CLM_ID"]), "bene": row["DESYNPUF_ID"], "from": start,
                           "thru": row["CLM_THRU_DT"] or start,
                           "paid_cents": int(round(float(row["CLM_PMT_AMT"] or 0) * 100))})
    members = {c["bene"] for c in claims}
    benes = {}
    for row in _rows("de1_0_2009_beneficiary_summary_file_sample_1.zip"):
        if row["DESYNPUF_ID"] in members:
            benes[row["DESYNPUF_ID"]] = {"hmo_months": int(row["BENE_HMO_CVRAGE_TOT_MONS"] or 0),
                                         "death": row["BENE_DEATH_DT"] or None, "state": row["SP_STATE_CODE"]}
    out = {"source": "CMS DE-SynPUF Sample 1 (2009 Beneficiary Summary; 2008-2010 Inpatient Claims). Public domain, synthetic.",
           "windows": WINDOWS, "claims": sorted(claims, key=lambda c: c["clm_id"]), "beneficiaries": benes}
    target = ROOT / "examples" / "synpuf" / "inpatient_extract.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{len(claims)} claims, {len(benes)} beneficiaries -> {target} ({target.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
