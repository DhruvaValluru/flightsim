"""Regenerate docs/TRACEABILITY.md from docs/REQUIREMENTS.yaml, the
requirement ids the tests cite and the mutation guards
(core/validation/traceability.py).

    python scripts/traceability.py           # write the table
    python scripts/traceability.py --check   # exit 1 when the committed table is stale

A refusal (a test citing an unknown id, a requirement with no test or no
guard and no stated reason) prints its name and exits 2; nothing is
written.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main(argv=None) -> int:
    from core.validation.traceability import TABLE_FILE, TraceabilityError, generate

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="compare with the committed table instead of writing it")
    args = parser.parse_args(argv)
    try:
        text = generate()
    except TraceabilityError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 2
    if args.check:
        current = TABLE_FILE.read_text(encoding="utf-8") if TABLE_FILE.is_file() else ""
        if current != text:
            print(f"{TABLE_FILE} is stale: run python scripts/traceability.py")
            return 1
        print(f"{TABLE_FILE} is current")
        return 0
    TABLE_FILE.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TABLE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
