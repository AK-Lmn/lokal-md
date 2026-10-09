"""Import a reference bundle (JSON) into the app database from the command line.

    python scripts/import_reference.py bundle.json [--activate]

Large bundles (hundreds of thousands of rules) are easier to import here than through the browser.
The dataset is stored as 'awaiting review': it cannot back clinical mode until a DIFFERENT qualified
person approves it in Settings -> Medication reference. --activate only makes it the active dataset in
demonstration mode.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rhuscribe import bootstrap, db  # noqa: E402
from rhuscribe.safety import refdata  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    t0 = time.time()
    bundle = refdata.parse_bundle_json(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(f"validated in {time.time() - t0:.0f}s: {len(bundle.ingredients)} ingredients, {len(bundle.interactions)} interactions, "
          f"{len(bundle.contraindications)} contraindications, {len(bundle.age_warnings)} age warnings")
    conn = db.connect()
    bootstrap.init(conn)
    ds = refdata.save_bundle(conn, bundle, kind="imported", imported_by=None)
    if "--activate" in sys.argv:
        refdata.set_active(conn, ds)
    print(f"imported as dataset {ds} (status: awaiting review{', ACTIVE' if '--activate' in sys.argv else ''}) in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
