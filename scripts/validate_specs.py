"""Validate SDD structure and run the upstream catalog/evidence validator."""

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    errors = []
    excluded = {"README.md", "_template.md", "CATALOG.md"}
    for file in sorted((ROOT / "specs").glob("*.md")):
        if file.name in excluded:
            continue
        text = file.read_text()
        sections = re.findall(r"^## (\d+)\.", text, re.M)
        if sections != [str(i) for i in range(1, 21)]:
            errors.append(f"{file.name}: the 20 ordered SDD sections are required")
        for field in [
            "Status",
            "Date",
            "Catalog capability ID",
            "Last verified",
            "Owners",
            "Scope",
            "Related issues/PRs",
            "Required review gates",
            "Open decisions blocking readiness",
        ]:
            if not re.search(rf"^- {re.escape(field)}: .+", text, re.M):
                errors.append(f"{file.name}: missing metadata {field}")
    if errors:
        print("\n".join(errors))
        return 1
    command = ["node", str(ROOT / "scripts/validate-specifications.cjs")]
    if args.generate:
        command.append("--write")
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
