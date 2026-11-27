# Test development and repetition

Research requirements: Python 3.14 and Node.js for the SDD validator. The Python version is
that of the validated environment. The adapter will be tested about Home Assistant
2026.11.2, whose run requires Python 3.14.2 or later.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest --cov=custom_components.roomba_home.core --cov-branch
.venv/bin/ruff check custom_components tools tests scripts
python3 scripts/validate_specs.py
python3 scripts/check_privacy.py
```

Unconnected testing uses synthetic responses, controlled watches and false transport. Do not
load local credentials or automatically detect an environment account. The API reference
does not replace contract evidence.

## Test for the adapter Home Assistant

The official Harness remains in a separate environment and HA package restrictions are
applied to avoid conflicts with other integrations:

```sh
python3.14 -m venv .venv-ha
.venv-ha/bin/python -m pip install 'homeassistant==2026.11.2'
.venv-ha/bin/python -m pip install \
  -c .venv-ha/lib/python3.14/site-packages/homeassistant/package_constraints.txt \
  -e '.[test,ha-test]'
.venv-ha/bin/python -m pytest --timeout=30 \
  --cov=custom_components.roomba_home --cov-branch --cov-fail-under=100
```

The constraints path shown corresponds to macOS / Linux with this environment. The HA tests
load actual integration with simulated supplier data, create the original and enlarged
entities for three robots as well to check reauth. Recharge) download (partially available
or problem events without duplicating.3 Test configuration files are written in temporary
directories.

To run hassfest from the same version, clone an official tag into a temporary directory and
install your package with that checkout:

```sh
git clone --depth 1 --branch 2026.11.2 \
  https://github.com/home-assistant/core.git /tmp/ha-core-validator
.venv-ha/bin/python -m pip install /tmp/ha-core-validator/packages/hassfest tqdm
```

From `/tmp/ha-core-validator`, use the absolute path to `.venv-ha/bin/python`
to run `-m script.hassfest --action validate --integration-path
<absolute_path>/custom_components/roomba_home`. GitHub Actions runs the same
validation without account credentials. [CI configuration](../.github/workflows/validate.yml)

## Private entrance for actual testing

Creates, with a local editor and an external file to checkout using keys `username` and
`password` and applying `chmod 600` To the file. Do not copies here actual data and passes
into arguments, registered variables or terminal examples.

It generates an own client's identity with the non-secret configuration observed:

```sh
.venv/bin/python tools/bootstrap_profile.py --out /private/path/profile.json
```

Optional, contrasts with an authorized capture:

```sh
.venv/bin/python tools/bootstrap_profile.py \
  --capture /private/path/reference.har \
  --out /private/path/profile.json
```

The profile preserves observed and generates client configuration `app_id` and `device_id`
his own. Do not copy the Gigya assertion and an app's name. The profile remains a private
entrance and isn't distributed in the repository.

```sh
.venv/bin/python tools/validate_api.py \
  --account-file /private/path/account.json \
  --profile-file /private/path/profile.json \
  --reference-capture /private/path/reference.har \
  --private-session-out /private/path/session.json \
  --report /private/path/http-report.json

.venv/bin/python tools/validate_mqtt.py \
  --session-file /private/path/session.json \
  --report /private/path/mqtt-report.json
```

`--reference-capture` is optional: without it we have been tested login, catalogue and
session replacement. It only reproduces JSON GET requests with previous success from an authenticated
observed host. POST, telemetry and app logs are not reproduced. The reports are low and have
them reviewed before they can be moved to public documentation.

The reader MQTT orders the nine known shadows for each device authorized by a token. Some
old models may be missing. A rejection 404 of a Shadow remains as an rejected response,
without treating it with access failure. Do not run two tools with it `client_id`
simultaneously: the broker can replace its previous connection.

The coordinator uses two quick and four slow shadows with separate cadences. Telemetry tests exclusively use synthetic data and do not result in actual robot malfunctions. The inventory of fields, conversions and boundaries are at [telemetry](telemetry.md). A new entity requires type, provenance and translation.

## Extent of an investigation order

`tools/send_command.py` modifies a physical robot. He receives an actual session and a private destination file with the key `robot_id`, never arbitrary issue. The order's one of `start`, `pause`, `stop` or `dock`. First look at the status and [attested context matrix](usage.md).

```sh
.venv/bin/python tools/send_command.py \
  --session-file /private/path/session.json \
  --target-file /private/path/target.json \
  --command pause
```

The receipt only attests acceptance of the broker. CLI does not substitute for physical
confirmation by HA coordinator and doesn't automatically repeat an order

## Capture with an emulator

Use Proxyman to inspect the official Roomba Home app on a dedicated
Android emulator. Keep SSL rules scoped to the service hosts under test
and keep Google Play sign-in outside the capture. A cold stock boot can
remove the temporary system trust that Proxyman needs for HTTPS. Verify
an actual `GET /v1/p2maps` response in Proxyman before starting a live-map
trial. A successful VPN connection confirms routing. The decoded map
response confirms that the app trusts the proxy for that host.
[Proxyman emulator setup](https://proxyman.com/docs/debug-devices/android-device/google-play-android-emulator-with-magisk) ·
[Verified capture recovery](validation.md#physical-confirmation-on-0861)

Publish only sanitized routes, counts, and relative timing. Keep traffic
archives, APKs, floor data, and account screenshots out of the repository.
For a physical command, record the requested action and the provider's
observed state transition. Verify the robot is back at its dock after the
trial.

## Maintenance of SDDs

Edit the specification and `specs/catalog.json` together.

```sh
python3 scripts/validate_specs.py --generate
python3 scripts/validate_specs.py
```

The first command generates a visible catalogue and the second checks an analysis of its catalogue, evidence or structure. 3 original models of the vypdev / copilot validator are included with an assignment at [Announcements](../THIRD_PARTY_NOTICES.md). No actions or review agents have been put into place. A proposed SDD does not prove that functionality is implemented.
