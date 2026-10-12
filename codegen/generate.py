"""Generate the Python and TypeScript SDK code from `spec/openapi.json`.

    python codegen/generate.py            # write the generated files
    python codegen/generate.py --check    # exit 1 if they are not up to date (CI)
    python codegen/generate.py --update-spec   # download the public contract first
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import emit_python  # noqa: E402
import emit_typescript  # noqa: E402
import model  # noqa: E402

ROOT = model.ROOT
SPEC_URL = "https://api.bytnode.com/openapi.json"


def update_spec() -> None:
    with urllib.request.urlopen(SPEC_URL, timeout=60) as resp:  # noqa: S310 (fixed https URL)
        spec = json.loads(resp.read().decode("utf-8"))
    model.SPEC_PATH.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"spec/openapi.json updated: contract {spec['info']['version']}, {len(spec['paths'])} paths")


def generate() -> list[Path]:
    api = model.load()
    prefix = json.loads(model.OVERRIDES_PATH.read_text(encoding="utf-8"))["field_prefix_for_leading_digit"]
    files = emit_python.write(api, ROOT, prefix) + emit_typescript.write(api, ROOT)
    print(f"generated {len(files)} files: {len(api.routes)} routes, {len(api.models)} models (contract {api.version})")
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the generated code is not up to date")
    ap.add_argument("--update-spec", action="store_true", help="download the public contract first")
    args = ap.parse_args()
    if args.update_spec:
        update_spec()
    files = generate()
    if args.check:
        rel = [str(p.relative_to(ROOT)) for p in files]
        diff = subprocess.run(["git", "status", "--porcelain", "--", *rel], cwd=ROOT, capture_output=True, text=True)
        if diff.stdout.strip():
            print("generated code is out of date — run `make generate` and commit:\n" + diff.stdout)
            return 1
        print("generated code is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
