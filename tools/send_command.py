"""Send one explicit robot command; this operates a physical robot, without retry."""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.roomba_home.core.commands import Command, MqttCommandSender  # noqa: E402
from custom_components.roomba_home.core.errors import ProtocolError, RoombaError  # noqa: E402
from custom_components.roomba_home.core.models import CloudSession  # noqa: E402
from tools.validate_api import private_json  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-file", type=Path, required=True)
    parser.add_argument(
        "--target-file",
        type=Path,
        required=True,
        help="Private JSON containing the exact associated robot_id.",
    )
    parser.add_argument(
        "--command",
        choices=[c.value for c in Command if c is not Command.POINT_CLEAN],
        required=True,
    )
    args = parser.parse_args()
    try:
        value = private_json(args.session_file)
        session = CloudSession.parse(value["session"], value["discovery"])
        if session.expiring(datetime.now(UTC)):
            raise ProtocolError("Renew the private session before sending a command.")
        target = private_json(args.target_file)["robot_id"]
        result = MqttCommandSender(session, target).send(Command(args.command))
        print(json.dumps(asdict(result)))
        return 0
    except (RoombaError, ValueError, KeyError, OSError, TimeoutError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "result": "failed",
                    "error": type(error).__name__,
                    "physical_result": "unconfirmed",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
