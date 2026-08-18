#!/usr/bin/env python3
"""Write the admin API's OpenAPI spec to docs/openapi.json.

The spec is generated from the routes themselves, so it cannot drift from the
code the way a hand-written document can. Committing it means the contract is
reviewable in a diff, and importable into Postman or a codegen tool without
the server running.

Run after changing any admin route:

    ./venv/bin/python scripts/export_openapi.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from admin_config import AdminConfigStore  # noqa: E402
from web import create_admin_app  # noqa: E402

OUTPUT = ROOT / "docs" / "openapi.json"


def build_spec() -> dict:
    # A throwaway config store: generating the schema only walks the routes,
    # it never reads config, Redis, or the database.
    app = create_admin_app(
        admin_token="placeholder",
        config_store=AdminConfigStore(ROOT / "data" / "admin_config.json"),
    )
    return app.openapi()


def main() -> int:
    spec = build_spec()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    operations = sum(
        1
        for methods in spec["paths"].values()
        for method in methods
        if method in {"get", "post", "put", "delete", "patch"}
    )
    print(f"wrote {OUTPUT.relative_to(ROOT)} — {operations} operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
