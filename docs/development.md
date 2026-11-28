# Development and validation

Use Python 3.14 for the test environments and Node.js for the card tests
and specification validator. The validated Home Assistant Core 2026.11.2
environment uses Python 3.14.2 or later.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest --cov=custom_components.roomba_home.core --cov-branch
.venv/bin/ruff check custom_components tools tests scripts
python3 scripts/validate_specs.py
python3 scripts/check_privacy.py
```

Offline tests use synthetic responses, controlled clocks, and fake
transports. They run without production credentials. The API reference
links to the recorded contract evidence.

## Home Assistant test environment

Install the Home Assistant test environment separately and apply its
dependency constraints.

```sh
python3.14 -m venv .venv-ha
.venv-ha/bin/python -m pip install 'homeassistant==2026.11.2'
.venv-ha/bin/python -m pip install \
  -c .venv-ha/lib/python3.14/site-packages/homeassistant/package_constraints.txt \
  -e '.[test,ha-test]'
.venv-ha/bin/python -m pytest -p pytest_homeassistant --timeout=30 \
  --cov=custom_components.roomba_home --cov-branch --cov-fail-under=100
node --test tests/frontend/map-card.test.cjs
```

The constraints path assumes the displayed macOS or Linux environment.
The Home Assistant tests load the integration with simulated Roomba
responses and temporary configuration. They verify entity identity,
reauthentication, reload and unload, confirmed actions, and live map
behavior. The card tests exercise the JavaScript controls and display.

To run hassfest for the same version, clone its tag into a temporary
directory and install the validator in the test environment.

```sh
git clone --depth 1 --branch 2026.11.2 \
  https://github.com/home-assistant/core.git /tmp/ha-core-validator
.venv-ha/bin/python -m pip install /tmp/ha-core-validator/packages/hassfest tqdm
```

From `/tmp/ha-core-validator`, use the absolute path to `.venv-ha/bin/python`
to run `-m script.hassfest --action validate --integration-path
<absolute_path>/custom_components/roomba_home`. GitHub Actions runs the same
validation without account credentials. [CI configuration](../.github/workflows/validate.yml)

## Private inputs for live validation

Create a local JSON file outside the checkout with `username` and
`password` keys and file mode 0600. Pass the filename to the validator.
Keep credential values out of command arguments, terminal examples,
and reports.

Generate a dedicated native client profile.

```sh
.venv/bin/python tools/bootstrap_profile.py --out /private/path/profile.json
```

Optionally verify the profile against an authorized capture.

```sh
.venv/bin/python tools/bootstrap_profile.py \
  --capture /private/path/reference.har \
  --out /private/path/profile.json
```

The profile uses the observed native settings and generates its own
`app_id` and `device_id`. Keep the profile and any identity assertion
outside the repository.

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

The optional reference capture supplies additional previously successful
JSON GET requests from an approved provider host. Without it, the HTTP
validator checks sign-in, inventory, and session replacement. Review the
reduced reports before using them as evidence in the repository.

The MQTT validator reads the known named shadows for each authorized
robot. A correlated 404 indicates an unavailable document. Concurrent
clients using the same `client_id` can replace each other's broker
connection.

The coordinator reads fast and slow shadow groups on different cadences.
Synthetic tests cover field mappings and error handling. Add a type,
source, and translation when exposing a new field. [Telemetry](telemetry.md)

## Physical command validation

`tools/send_command.py` operates a physical robot. Supply a valid session,
a private target file containing `robot_id`, and a supported command such
as `start`, `pause`, `stop`, or `dock`. Check the device state and its
supported actions before dispatch. [Usage](usage.md)

```sh
.venv/bin/python tools/send_command.py \
  --session-file /private/path/session.json \
  --target-file /private/path/target.json \
  --command pause
```

The receipt confirms broker acceptance. Observe the robot's reported
state to verify its physical response. The CLI sends one command.

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

The first command regenerates the readable catalog. The second validates
its evidence paths and the specification structure. Record implementation
and physical verification in each capability before marking it complete.
[Upstream validator attribution](../THIRD_PARTY_NOTICES.md)
