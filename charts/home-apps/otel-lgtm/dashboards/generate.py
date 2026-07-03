#!/usr/bin/env python3
"""Render every dashboard module to a GrafanaDashboard CR YAML file.

Usage:
    python generate.py            # regenerate all CRs into ../templates/generated/

Add a dashboard:
    1. drop a new module in dashboards/ exposing `build() -> dash.Dashboard`,
       `UID` and `CR_NAME` (see dashboards/vymalo_mobile.py);
    2. register it in DASHBOARDS below;
    3. run `python generate.py` (or `make dashboards`).

Never hand-edit the generated YAML — edit the .py and re-run.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# dashboards/ modules import the sibling `lib` module by bare name.
sys.path.insert(0, str(HERE))

import lib  # noqa: E402

# Output lands in the chart's templates so Argo/Helm ship the CRs. A `generated`
# subdir keeps them visually distinct from hand-written templates.
OUTPUT_DIR = HERE.parent / "templates" / "generated"

# Registry: module name (under dashboards/) -> output filename stem.
DASHBOARDS: dict[str, str] = {
    "vymalo_mobile": "dashboard-vymalo-mobile",
    "global_errors": "dashboard-global-errors",
}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    for module_name, out_stem in DASHBOARDS.items():
        mod = importlib.import_module(f"dashboards.{module_name}")
        dashboard_json = lib.dashboard_to_dict(mod.build())
        cr_yaml = lib.wrap_cr(
            cr_name=mod.CR_NAME,
            module=module_name,
            dashboard_json=dashboard_json,
        )
        out_path = OUTPUT_DIR / f"{out_stem}.yaml"
        out_path.write_text(cr_yaml, encoding="utf-8")
        written.append(str(out_path.relative_to(HERE.parent.parent.parent)))
        print(f"  wrote {out_path.name}  (uid={mod.UID})")

    print(f"\nGenerated {len(written)} GrafanaDashboard CR(s):")
    for w in written:
        print(f"  - {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
