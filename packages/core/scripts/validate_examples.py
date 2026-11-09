#!/usr/bin/env python
"""Validate the ```json examples in docs/schemas.md against the Pydantic models.

    uv run python packages/core/scripts/validate_examples.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))
from physlab_core.schemas import MODELS  # noqa: E402

text = (ROOT / "docs" / "schemas.md").read_text()
found = dict(re.findall(r"<!-- example: (\w+) -->\s*```json\n(.*?)\n```", text, re.S))
missing = set(MODELS) - set(found)
if missing:
    sys.exit(f"missing examples: {sorted(missing)}")
for name, model in MODELS.items():
    obj = model.model_validate(json.loads(found[name]))
    print(f"OK {name}: {type(obj).__name__}")
