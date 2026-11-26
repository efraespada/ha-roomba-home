"""Scan Git candidate files without printing matching sensitive content."""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Exact, reviewed artwork, upstream font, and screenshots. New binary files
# still require review regardless of their name or extension.
REVIEWED_BINARY_ASSETS = {
    "custom_components/roomba_home/brand/icon.png": (
        "90bc9097044bc5c7aa3ef38d92e2595d3f02559cf3bed763ae4647774233e2ab"
    ),
    "custom_components/roomba_home/brand/icon@2x.png": (
        "d838bf0533c1942e7992bede3ea2c8a783f52cf430b45a5ca7f822a57b7756d8"
    ),
    "custom_components/roomba_home/fonts/NotoSans-Regular.ttf": (
        "478c558ea716033cd60c03438f628dfa75694dcf6b5f6d505a2f05fd2b4f3823"
    ),
    "docs/screenshots/roomba-map-live.png": (
        "a7e82c1574a9947e275224bdee59466b39e3210267124f79f5c893f49f45ec97"
    ),
    "docs/screenshots/roomba-map-confirm.png": (
        "8bc74fd82e18b57133bb8ffb5913c5c59e7c69610c376f84fe15ce364ea9c11b"
    ),
    "docs/screenshots/roomba-routines.png": (
        "3b89e794cea1855c7f05c22b1ace8ae7abf676ea573428a8d20d63854a33dbac"
    ),
    "docs/screenshots/roomba-dock-auto-empty.png": (
        "a0472d6416143cea7b1ca3eb089197c1b35356d5a456337b192b58d654486db6"
    ),
    "docs/screenshots/roomba-robot-help.png": (
        "7cbacb2ad7b4aa5b9db65243a4e275eea8637063e29e3d34c44f7ab5dc349f28"
    ),
    "docs/screenshots/roomba-first-clean.png": (
        "53bd01c803ff9eb5eaf01571cef145c2497efb52d3288ce14a5bfa94ae4dcfc5"
    ),
    "docs/screenshots/roomba-room-editor.jpg": (
        "db26543768c3549e2406489e02ea8b65662ec16a7e4432ff8baee5856d7438cb"
    ),
    "docs/screenshots/roomba-floor-rotation.jpg": (
        "473092a91fb80bc3d34dcae1a3032af36835b205a5dae99947af95496c940517"
    ),
    "docs/screenshots/roomba-room-name-editor.jpg": (
        "d57e1e4464d12faa2ec1f29de2278758022b1f3083e57ab343240977a5680723"
    ),
    "docs/screenshots/roomba-zone-editor.jpg": (
        "68118a0b4a5279ac5abbef5945fafa303cd2281f11859d9aa30f9b13d2a99505"
    ),
    "docs/screenshots/roomba-restriction-editor.jpg": (
        "436591edfa367a2896f6fa82d96655dddbfb85c9b98ab8d509d7766631c69e5f"
    ),
    "docs/screenshots/roomba-furniture-editor.jpg": (
        "7d39aca8c6a11f6b08fe67aa8c1f4ecb56ffeb798d33507bfb6054c35435aaa1"
    ),
    "docs/screenshots/roomba-furniture-routine.jpg": (
        "920dc36c3a489f80ebcf69ecd3cdaaeb5248dd867cdad45cca850c38dce60fb8"
    ),
}
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    "personal-email": re.compile(r"\b[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b"),
}


def findings(text, denied=()):
    for name, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            if name == "personal-email" and match.group() == "icon@2x.png":
                # Home Assistant's fixed retina artwork filename is not an address.
                continue
            if name == "personal-email" and match.group().rsplit("@", 1)[1] in {
                "example.com",
                "example.test",
                "example.invalid",
            }:
                continue
            yield name, text.count("\n", 0, match.start()) + 1
    for value in denied:
        if value and value in text:
            yield "private-input-value", text.count("\n", 0, text.index(value)) + 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-deny-file", type=Path)
    args = parser.parse_args()
    denied = []
    if args.private_deny_file:
        # This optional file stays outside Git; only scalar string values are compared.
        def collect(value):
            if isinstance(value, str) and len(value) >= 8:
                denied.append(value)
            elif isinstance(value, dict):
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(json.loads(args.private_deny_file.read_text()))
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    )
    failed = False
    count = 0
    for relative in output.decode().split("\0"):
        if not relative:
            continue
        file = ROOT / relative
        if file.is_symlink() or not file.is_file():
            continue
        raw = file.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            if hashlib.sha256(raw).hexdigest() == REVIEWED_BINARY_ASSETS.get(relative):
                count += 1
                continue
            print(f"{relative}: binary file requires private-data review")
            failed = True
            continue
        count += 1
        for kind, line in findings(text, denied):
            print(f"{relative}:{line}: {kind}")
            failed = True
    if not failed:
        print(f"privacy scan: PASS ({count} candidate files; no matching values printed)")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
