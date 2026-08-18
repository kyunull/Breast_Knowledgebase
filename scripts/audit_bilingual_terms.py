from __future__ import annotations

import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.terminology import audit_bilingual_dictionary


GLOSSARY_PATH = PROJECT_ROOT / "data" / "retrieval" / "bilingual_terms.json"


def main() -> int:
    try:
        payload = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"cannot read glossary: {exc}")
        return 1

    terms = payload.get("terms") if isinstance(payload, dict) else None
    if not isinstance(terms, dict):
        print("glossary does not contain a terms object")
        return 1
    malformed = []
    for source, values in terms.items():
        if not isinstance(source, str):
            malformed.append(f"term key {source!r} is not a string")
            continue
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            malformed.append(f"term values for {source!r} must be a list of strings")
    if malformed:
        print("malformed glossary:")
        for message in malformed:
            print(message)
        return 1

    directed_pair_count = sum(
        len(values) for values in terms.values() if isinstance(values, list)
    )
    unique_pairs = {
        tuple(sorted((str(source), str(target)), key=lambda value: value.casefold()))
        for source, values in terms.items()
        if isinstance(values, list)
        for target in values
    }
    errors = audit_bilingual_dictionary(terms)
    print(f"term_count={len(terms)}")
    print(f"directed_pair_count={directed_pair_count}")
    print(f"unique_pair_count={len(unique_pairs)}")
    print(f"error_count={len(errors)}")
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
