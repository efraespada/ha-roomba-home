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
    "docs/screenshots/roomba-device-settings.jpg": (
        "ab9b7e8a634df1282d381cf3e43ee4f8b13b374b1d96bfc905a2656815066f0d"
    ),
    "docs/screenshots/roomba-voice-download.jpg": (
        "5ffd8bad839f7ec0fa7ebe19e6edcf980c6722ce6d09945904266c1c33ea06ca"
    ),
    "docs/screenshots/roomba-robot-actions.jpg": (
        "632a681802b62d88c76e129c7a2120ebaa246dad90126b54b1d4390f3b90f3fc"
    ),
    "docs/screenshots/roomba-connection-details.jpg": (
        "544316da040b6199e256eb87cd52ec5ca60a8c89f7a10965d777fcc2b466f321"
    ),
    "docs/screenshots/roomba-recorded-map-layers.jpg": (
        "49b39d6f85912f28d5de6088e7015637b9e6274e346bff31fdf75587d3b7ee2a"
    ),
    "docs/screenshots/roomba-floor-activity.jpg": (
        "9319441373038cf7548c18a7c860f9fd6bd51afd8215d1b569673f176caf6cf9"
    ),
    "docs/screenshots/roomba-dock-controls.jpg": (
        "b403707827720f2c4b31db72ee923364d04885c9ea8ae876d553096c96e94d1b"
    ),
    "docs/screenshots/roomba-robot-status.jpg": (
        "bc7a794485e0d3e6123d213b75ff7ef33cbd6caf6fe0ccceadcaa11f7a9b9a13"
    ),
    "docs/screenshots/roomba-maintenance-reset.jpg": (
        "c2cc136586b003f95ed554ae0c7f3d99faf5f4902af5f1bd22c836338c8709fc"
    ),
    "docs/screenshots/roomba-maintenance-reminder.jpg": (
        "6adcb00a7c173af32654ddf6407be8292c14a4a82747ce102529183fedec1c10"
    ),
    "docs/screenshots/roomba-part-guidance.jpg": (
        "1a2b642c1e246ef168409ca74830706c8ead7bfa840f3a4b69d1f35769f2245c"
    ),
    "docs/screenshots/roomba-activation-date.jpg": (
        "c0ca1a16d70dfd84c313cf2aee3fdaaaefe744e970091c4ad22f425e4fa15fa8"
    ),
    "docs/screenshots/roomba-robot-software.jpg": (
        "a0d409afb8bd52df7dc739c004e01b73d5d18191b47a8de23a8b1a202a0f8368"
    ),
    "docs/screenshots/roomba-robot-help.png": (
        "7cbacb2ad7b4aa5b9db65243a4e275eea8637063e29e3d34c44f7ab5dc349f28"
    ),
    "docs/screenshots/roomba-first-clean.png": (
        "53bd01c803ff9eb5eaf01571cef145c2497efb52d3288ce14a5bfa94ae4dcfc5"
    ),
    "docs/screenshots/roomba-history-emptying.png": (
        "e9ebac75c5ade96376e79c7dcedd24cb936f1ef45d19069bebe6a41485812808"
    ),
    "docs/screenshots/roomba-recommended-rooms-key.png": (
        "8b57e6761f893c4e0f571a1cdc614c0350e85285264dc329876681f16c8aa319"
    ),
    "docs/screenshots/roomba-expanded-history-filter.png": (
        "008a0bea894f4bf1cc0e754b91e71219e8553cfbebc1e924f470d7e93b61ace3"
    ),
    "docs/screenshots/roomba-local-route-recording.jpg": (
        "f632d2b304de5ac432ce3d6f26327127a04bc01a85ddd7f5eba6b5f5c2e01aa7"
    ),
    "docs/screenshots/roomba-archived-mopping.jpg": (
        "387527de342f74933e55af35ed68529281fb5734acfa62f247f0b30e28343587"
    ),
    "docs/screenshots/roomba-live-mopping.jpg": (
        "5bdabc2fa21e79a7d3faac4b6a48b25f2a8a4b6af7f8be8c6f19cd2789a4e3e8"
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
    "docs/screenshots/roomba-floor-removal-programs.jpg": (
        "888623b9e4eadd39f73058df68d59125edc8c1e04fdb9f7590d855b68a97db92"
    ),
    "docs/screenshots/roomba-rebuild-program-destinations.jpg": (
        "6501783003a27fc300b73dfb9012f0dc863790213f1613c333205c4e6ac208b9"
    ),
    "docs/screenshots/roomba-paused-cleaning-estimate.jpg": (
        "a0494f6dfd555ada1794303792f79ea9a6c121dfbe7a3d9c08e12440646cc2a6"
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
