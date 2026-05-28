#!/usr/bin/env python3
"""Compact JSON payloads before sending to a model."""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any


def token_estimate(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / 4)


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def truncate_str(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return value[:max_len] + f"…[+{len(value) - max_len}]"


def slim_value(value: Any, max_str: int, drop_nulls: bool) -> Any:
    if isinstance(value, str):
        return truncate_str(value, max_str)
    if isinstance(value, dict):
        return _slim_obj(value, max_str=max_str, keep=None, drop=set(), drop_nulls=drop_nulls)
    if isinstance(value, list):
        return [slim_value(item, max_str, drop_nulls) for item in value]
    return value


def _slim_obj(
    obj: dict[str, Any],
    *,
    max_str: int,
    keep: set[str] | None,
    drop: set[str],
    drop_nulls: bool,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in obj.items():
        if key in drop:
            continue
        if keep is not None and key not in keep:
            continue
        if drop_nulls and is_empty(value):
            continue
        out[key] = slim_value(value, max_str, drop_nulls)
    return out


def slim_payload(
    data: Any,
    *,
    max_str: int,
    keep: set[str] | None,
    drop: set[str],
    drop_nulls: bool,
    max_items: int | None,
) -> Any:
    if isinstance(data, list):
        items = data[:max_items] if max_items is not None else data
        omitted = len(data) - len(items) if max_items is not None else 0
        result: list[Any] = []
        for item in items:
            if isinstance(item, dict):
                result.append(_slim_obj(item, max_str=max_str, keep=keep, drop=drop, drop_nulls=drop_nulls))
            else:
                result.append(slim_value(item, max_str, drop_nulls))
        if omitted > 0:
            result.append({"_omitted": omitted, "_note": f"{omitted} items not shown (use --max-items to raise limit)"})
        return result
    if isinstance(data, dict):
        return _slim_obj(data, max_str=max_str, keep=keep, drop=drop, drop_nulls=drop_nulls)
    return data


def field_token_costs(data: Any) -> dict[str, int]:
    """Aggregate token cost per top-level key across all records."""
    if isinstance(data, list):
        totals: dict[str, int] = {}
        for item in data:
            if isinstance(item, dict):
                for k, v in item.items():
                    totals[k] = totals.get(k, 0) + token_estimate(json.dumps(v, ensure_ascii=False))
        return totals
    if isinstance(data, dict):
        return {k: token_estimate(json.dumps(v, ensure_ascii=False)) for k, v in data.items()}
    return {}


def print_field_report(data: Any, before_tokens: int, label: str) -> None:
    costs = field_token_costs(data)
    top = sorted(costs.items(), key=lambda x: -x[1])[:20]
    print(f"\nfield costs ({label}):", file=sys.stderr)
    for field, cost in top:
        pct = cost / before_tokens * 100 if before_tokens else 0
        print(f"  {field}: {cost:,} tokens ({pct:.1f}%)", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", metavar="FILE", help="Input JSON file (default: stdin)")
    parser.add_argument(
        "--keep",
        metavar="KEYS",
        help="Comma-separated top-level keys to keep (all others dropped)",
    )
    parser.add_argument(
        "--drop",
        metavar="KEYS",
        help="Comma-separated top-level keys to always remove",
    )
    parser.add_argument(
        "--max-str",
        type=int,
        default=200,
        metavar="N",
        help="Truncate strings longer than N chars (default: 200)",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        metavar="N",
        help="Limit array length to first N items",
    )
    parser.add_argument(
        "--no-drop-nulls",
        action="store_true",
        help="Keep null/empty fields (dropped by default)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Output single-line compact JSON",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print before/after token count to stderr",
    )
    parser.add_argument(
        "--field-report",
        action="store_true",
        help="Print top fields by token cost (before and after) to stderr",
    )
    args = parser.parse_args()

    try:
        if args.input:
            with open(args.input) as fh:
                raw = fh.read()
        else:
            raw = sys.stdin.read()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    keep = {k.strip() for k in args.keep.split(",") if k.strip()} if args.keep else None
    drop = {k.strip() for k in args.drop.split(",") if k.strip()} if args.drop else set()
    # normalize to compact for fair comparison (whitespace-independent)
    before_tokens = token_estimate(json.dumps(data, ensure_ascii=False))

    if args.field_report:
        print_field_report(data, before_tokens, "before")

    result = slim_payload(
        data,
        max_str=args.max_str,
        keep=keep,
        drop=drop,
        drop_nulls=not args.no_drop_nulls,
        max_items=args.max_items,
    )

    indent = None if args.compact else 2
    output = json.dumps(result, ensure_ascii=False, indent=indent)
    # always compare compact representations so whitespace doesn't skew the report
    after_tokens = token_estimate(json.dumps(result, ensure_ascii=False))

    if args.field_report:
        print_field_report(result, after_tokens, "after")

    if args.report or args.field_report:
        saved = before_tokens - after_tokens
        pct = saved / before_tokens * 100 if before_tokens else 0
        record_count = f", {len(data)} records" if isinstance(data, list) else ""
        print(
            f"\ntokens: {before_tokens:,} → {after_tokens:,}  saved {saved:,} ({pct:.0f}%){record_count}",
            file=sys.stderr,
        )

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
