"""Read named shadows without persisting or printing device identifiers or payloads."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.roomba_home.core.errors import RoombaError  # noqa: E402
from custom_components.roomba_home.core.models import CloudSession  # noqa: E402
from custom_components.roomba_home.core.mqtt import MqttProfile, MqttShadowReader  # noqa: E402
from tools.validate_api import private_json  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-file", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.report.resolve() == args.session_file.resolve():
            raise ValueError("The report must not replace the private session.")
        value = private_json(args.session_file)
        session = CloudSession.parse(value["session"], value["discovery"])
        replies = []
        for index in range(len(session.raw["connection_tokens"])):
            replies.extend(MqttShadowReader(MqttProfile.from_session(session, index)).read())
        counts = Counter((r.shadow, r.accepted, r.document.get("code")) for r in replies)
        report = {
            "connections": len(session.raw["connection_tokens"]),
            "responses": len(replies),
            "shadows": [
                {"shadow": s, "accepted": a, "code": c, "count": n}
                for (s, a, c), n in sorted(counts.items())
            ],
        }
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
        return 0
    except (RoombaError, ValueError, KeyError, OSError, TimeoutError) as error:
        print(json.dumps({"result": "failed", "error": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
