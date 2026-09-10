"""One-shot check that the Google Sheet wiring works.

Run after SETUP_GOOGLE_SHEET.md is done and .streamlit/secrets.toml is filled:

    python scripts/smoke_test_sheet.py

Writes 3 tiny rows to the configured worksheet, reads them back, edits one,
saves, verifies, then clears the worksheet. Prints each step.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import loader  # noqa: E402
import store  # noqa: E402

SECRETS = ROOT / ".streamlit" / "secrets.toml"


def main() -> int:
    if not SECRETS.exists():
        print(f"missing {SECRETS} — copy secrets.toml.example and fill it in")
        return 1
    secrets = tomllib.loads(SECRETS.read_text(encoding="utf-8"))

    print("connecting ...")
    backend = store.backend_from_secrets(secrets)

    sample = pd.DataFrame(
        {
            "Subject Code": ["TEST0001", "TEST0001", "TEST0002"],
            "Subject Title": ["Smoke Test A"] * 2 + ["Smoke Test B"],
            "Program Code": ["9999", "9999", "9999"],
            "Assessment Number": ["1", "2", "1"],
            "Assessment Type": ["Quiz", "Report", "Quiz"],
            "Learning Outcomes": ["SLO1"] * 3,
            "Weighting": ["50", "50", "100"],
            "Conditions": ["-"] * 3,
            "Inspire Score": ["6", "4", "8"],
            "Assure Score": ["7", "9", "3"],
            "Notes/Comments": [""] * 3,
            "Source File": ["smoke - 2026.01"] * 3,
            "Confirmed_R1": [True, False, True],
            "Quadrant_R1": ["Inspire", "Assure", "Inspire"],
        }
    )
    sample["RowKey"] = [
        loader.row_key(sf, pc, an)
        for sf, pc, an in zip(
            sample["Source File"], sample["Program Code"], sample["Assessment Number"]
        )
    ]

    print("seeding 3 rows ...")
    store.seed(backend, sample)

    loaded = store.load(backend)
    print(f"read back {len(loaded)} rows; columns ok: "
          f"{set(store.STORED_COLUMNS).issubset(loaded.columns)}")

    key = loaded.iloc[0]["RowKey"]
    loaded.loc[loaded["RowKey"] == key, "AssureBand"] = "Assured"
    loaded.loc[loaded["RowKey"] == key, "Confirmed_R2"] = "TRUE"
    after = store.save(backend, loaded, changed_keys=[key], reviewer="smoke-test")
    row = after[after["RowKey"] == key].iloc[0]
    ok = row["AssureBand"] == "Assured" and row["Confirmed_R2"] == "TRUE" and row["last_saved_by"] == "smoke-test"
    print(f"save round-trip ok: {ok}  (last_saved_at={row['last_saved_at']})")

    print("clearing worksheet ...")
    backend.write_all(store.STORED_COLUMNS, [])

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
