#!/usr/bin/env python3
"""Show what a client seed actually turns into, without running the bot.

Validates the seed, then prints the things a config decides: the products, the
CSV columns leads land in, the qualification steps *with the wording the model
receives*, and the full system instruction for one language. Nothing is sent
anywhere and no API key is needed — this reads the config and renders it.

    ./venv/bin/python scripts/preview_seed.py                    # seeds/tvs.json
    ./venv/bin/python scripts/preview_seed.py seeds/acme.json
    ./venv/bin/python scripts/preview_seed.py seeds/acme.json --language Hindi
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from admin_config import (  # noqa: E402
    active_campaign_text,
    campaign_is_active,
    csv_columns,
    fill_missing_defaults,
    flow_steps,
    today_ist,
    validate_config,
)
from conversation_engine import (  # noqa: E402
    FLOW_STEP_GUIDANCE,
    build_system_instruction,
)


def rule(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m\n" + "─" * len(title))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seed", nargs="?", default="seeds/tvs.json")
    parser.add_argument("--language", default="English")
    parser.add_argument(
        "--prompt-only",
        action="store_true",
        help="print just the system instruction, for diffing between seeds",
    )
    args = parser.parse_args()

    path = Path(args.seed)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"no such seed: {path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"invalid JSON in {path}: {e}", file=sys.stderr)
        return 1

    config = fill_missing_defaults(config)
    try:
        validate_config(config)
    except ValueError as e:
        print(f"\033[31minvalid seed\033[0m {path}: {e}", file=sys.stderr)
        return 1

    prompt = build_system_instruction(config, args.language)
    if args.prompt_only:
        print(prompt)
        return 0

    print(f"\033[32mvalid\033[0m  {path}")

    rule("Identity")
    print(f"  bot_name     {config['bot_name']}")
    print(f"  languages    {', '.join(l['code'] for l in config['languages'])}")
    print(f"  voice        {config['voice_policy']}")

    rule("Products")
    documents = config.get("documents") or {}
    if not documents:
        print("  (none configured — this bot sends no brochures)")
    for name, entry in documents.items():
        extras = []
        if entry.get("fuel"):
            extras.append(f"{len(entry['fuel'])} fuel variants")
        if entry.get("support"):
            extras.append(f"{len(entry['support'])} support docs")
        print(f"  {name}" + (f"  ({', '.join(extras)})" if extras else ""))

    rule("Campaign")
    active = campaign_is_active(config)
    text = active_campaign_text(config)
    window = (config.get("campaign_starts_on"), config.get("campaign_ends_on"))
    print(f"  active today ({today_ist()})  {active}")
    print(f"  window       {window[0] or 'no start'} → {window[1] or 'never expires'}")
    if text:
        print(f"  first line   {text.splitlines()[0]}")

    rule("Qualification steps (the wording the model receives)")
    # build_system_instruction indents the flow steps by three spaces, which is
    # what separates them from the engine's own numbered rules.
    steps = [
        line.strip()
        for line in prompt.splitlines()
        if line.startswith("   ") and line.strip()[:1].isdigit()
    ]
    for step in steps:
        number, _, guidance = step.partition(". ")
        wrapped = textwrap.fill(
            guidance, width=88, initial_indent="", subsequent_indent=" " * 6
        )
        print(f"  {number:>2}. {wrapped}")
    ids = [step_id for step_id, _ in flow_steps(config)]
    print(f"\n  configured ids: {', '.join(ids)}")
    missing = [
        step_id
        for step_id, guidance in flow_steps(config)
        if not guidance.strip() and step_id not in FLOW_STEP_GUIDANCE
    ]
    if missing:
        print(
            "\n  \033[31mno guidance\033[0m: "
            + ", ".join(missing)
            + "\n  These reach the model as a bare name. Give each a `guidance` "
            "string."
        )

    rule("Lead CSV columns")
    columns = csv_columns(config)
    print("  " + ", ".join(columns))
    required = [f["id"] for f in config["capture_fields"] if f.get("required")]
    print(f"  required: {', '.join(required) or '(none)'}")

    rule(f"System instruction ({args.language}, {len(prompt)} chars)")
    print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
