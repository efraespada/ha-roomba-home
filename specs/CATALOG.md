# Product capability specification catalog

> Generated from [`catalog.json`](./catalog.json). Do not edit this table by hand.
> Regenerate this view after metadata changes using verified repository specification tooling.

This catalog answers which product contract owns a capability and where its
implementation, verification, workflow, and user-documentation evidence lives.
An **As-built baseline** records verified current behavior; it does not hide known
debt or convert unknown historic intent into a design decision.

| Capability ID | Status | Scope | Primary SDD | Evidence |
|---|---|---|---|---|
| `native-api` | As-built baseline | Research client, authentication, signing, and reads without Home Assistant | [Native access and HTTP reads](./001-native-api.md) | 12 paths · 2026-11-23 |
| `mqtt-state` | As-built baseline | Bounded reads of named shadows | [Modern robot state via MQTT](./002-mqtt-state.md) | 7 paths · 2026-11-23 |
| `native-commands` | As-built baseline | Single experimental command submission and evidence from an authorized physical cycle | [Native commands and physical validation](./004-command-validation.md) | 8 paths · 2026-11-23 |
| `home-assistant` | As-built baseline | Account setup and options, per-robot entities, polling, and confirmed commands | [Home Assistant integration and confirmed control](./003-home-assistant.md) | 23 paths · 2026-11-23 |
| `telemetry-and-problems` | Proposed | Typed telemetry, consumables, problem events, provider connectivity timestamps, and mission results | [Telemetry&#44; progress&#44; and problem events](./005-telemetry-and-problems.md) | 21 paths · 2026-11-23 |
| `cleaning-profiles` | Proposed | Capability-based mode and parameter combinations, next-cleaning controls, and physical confirmation | [Cleaning modes and profiles](./006-cleaning-profiles.md) | 25 paths · 2026-11-23 |
| `device-capabilities` | Proposed | Shared discovery, device coordination, dock actions, regions, recovery, and live map position | [Capability&#45;driven integration](./007-device-capabilities.md) | 38 paths · 2026-11-23 |
| `mission-detail-and-map-card` | Proposed | Per-room history, live progress, dashboard selection, and household checks | [Mission Detail and Interactive Floor Maps](./008-mission-detail-and-map-card.md) | 17 paths · 2026-11-24 |

## Evidence map

### `native-api` — Native access and HTTP reads

- Owner: ha-roomba-home maintainer
- Last verified: 2026-11-23
- Specifications: [`specs/001-native-api.md`](./001-native-api.md)
- Workflows: Not applicable for this capability.
- Entrypoints: [`tools/validate_api.py`](../tools/validate_api.py) · [`tools/bootstrap_profile.py`](../tools/bootstrap_profile.py)
- Core code: [`custom_components/roomba_home/core/client.py`](../custom_components/roomba_home/core/client.py) · [`custom_components/roomba_home/core/models.py`](../custom_components/roomba_home/core/models.py) · [`custom_components/roomba_home/core/transport.py`](../custom_components/roomba_home/core/transport.py)
- Tests: [`tests/test_api_client.py`](../tests/test_api_client.py) · [`tests/test_transport_and_tools.py`](../tests/test_transport_and_tools.py) · [`tests/test_architecture_and_privacy.py`](../tests/test_architecture_and_privacy.py)
- User documentation: [`docs/api.md`](../docs/api.md) · [`docs/development.md`](../docs/development.md) · [`docs/validation.md`](../docs/validation.md) · [`SECURITY.md`](../SECURITY.md)

### `mqtt-state` — Modern robot state via MQTT

- Owner: ha-roomba-home maintainer
- Last verified: 2026-11-23
- Specifications: [`specs/002-mqtt-state.md`](./002-mqtt-state.md)
- Workflows: Not applicable for this capability.
- Entrypoints: [`tools/validate_mqtt.py`](../tools/validate_mqtt.py)
- Core code: [`custom_components/roomba_home/core/mqtt.py`](../custom_components/roomba_home/core/mqtt.py)
- Tests: [`tests/test_mqtt.py`](../tests/test_mqtt.py)
- User documentation: [`docs/api.md`](../docs/api.md) · [`docs/architecture.md`](../docs/architecture.md) · [`docs/development.md`](../docs/development.md) · [`docs/validation.md`](../docs/validation.md)

### `native-commands` — Native commands and physical validation

- Owner: ha-roomba-home maintainer
- Last verified: 2026-11-23
- Specifications: [`specs/004-command-validation.md`](./004-command-validation.md)
- Workflows: Not applicable for this capability.
- Entrypoints: [`tools/send_command.py`](../tools/send_command.py)
- Core code: [`custom_components/roomba_home/core/commands.py`](../custom_components/roomba_home/core/commands.py)
- Tests: [`tests/test_commands.py`](../tests/test_commands.py)
- User documentation: [`docs/api.md`](../docs/api.md) · [`docs/development.md`](../docs/development.md) · [`docs/validation.md`](../docs/validation.md) · [`docs/architecture.md`](../docs/architecture.md) · [`docs/evidence/2026-11-23-control.json`](../docs/evidence/2026-11-23-control.json)

### `home-assistant` — Home Assistant integration and confirmed control

- Owner: ha-roomba-home maintainer
- Last verified: 2026-11-23
- Specifications: [`specs/003-home-assistant.md`](./003-home-assistant.md)
- Workflows: [`.github/workflows/validate.yml`](../.github/workflows/validate.yml)
- Entrypoints: [`custom_components/roomba_home/__init__.py`](../custom_components/roomba_home/__init__.py) · [`custom_components/roomba_home/config_flow.py`](../custom_components/roomba_home/config_flow.py)
- Core code: [`custom_components/roomba_home/coordinator.py`](../custom_components/roomba_home/coordinator.py) · [`custom_components/roomba_home/core/state.py`](../custom_components/roomba_home/core/state.py) · [`custom_components/roomba_home/vacuum.py`](../custom_components/roomba_home/vacuum.py) · [`custom_components/roomba_home/sensor.py`](../custom_components/roomba_home/sensor.py) · [`custom_components/roomba_home/binary_sensor.py`](../custom_components/roomba_home/binary_sensor.py) · [`custom_components/roomba_home/diagnostics.py`](../custom_components/roomba_home/diagnostics.py) · [`custom_components/roomba_home/brand/icon.png`](../custom_components/roomba_home/brand/icon.png) · [`custom_components/roomba_home/brand/icon@2x.png`](../custom_components/roomba_home/brand/icon%402x.png)
- Tests: [`tests/ha/test_flow.py`](../tests/ha/test_flow.py) · [`tests/ha/test_coordinator.py`](../tests/ha/test_coordinator.py) · [`tests/ha/test_entities.py`](../tests/ha/test_entities.py) · [`tests/test_state.py`](../tests/test_state.py)
- User documentation: [`docs/index.md`](../docs/index.md) · [`docs/architecture.md`](../docs/architecture.md) · [`docs/validation.md`](../docs/validation.md) · [`docs/installation.md`](../docs/installation.md) · [`docs/usage.md`](../docs/usage.md) · [`docs/evidence/2026-11-23-home-assistant.json`](../docs/evidence/2026-11-23-home-assistant.json) · [`docs/evidence/2026-11-23-quality.json`](../docs/evidence/2026-11-23-quality.json) · [`docs/branding.md`](../docs/branding.md)

### `telemetry-and-problems` — Telemetry&#44; progress&#44; and problem events

- Owner: ha-roomba-home maintainer
- Last verified: 2026-11-23
- Specifications: [`specs/005-telemetry-and-problems.md`](./005-telemetry-and-problems.md)
- Workflows: [`.github/workflows/validate.yml`](../.github/workflows/validate.yml)
- Entrypoints: [`custom_components/roomba_home/sensor.py`](../custom_components/roomba_home/sensor.py) · [`custom_components/roomba_home/binary_sensor.py`](../custom_components/roomba_home/binary_sensor.py) · [`custom_components/roomba_home/event.py`](../custom_components/roomba_home/event.py)
- Core code: [`custom_components/roomba_home/core/telemetry.py`](../custom_components/roomba_home/core/telemetry.py) · [`custom_components/roomba_home/core/problems.py`](../custom_components/roomba_home/core/problems.py) · [`custom_components/roomba_home/core/history.py`](../custom_components/roomba_home/core/history.py) · [`custom_components/roomba_home/coordinator.py`](../custom_components/roomba_home/coordinator.py) · [`custom_components/roomba_home/entity.py`](../custom_components/roomba_home/entity.py)
- Tests: [`tests/test_telemetry.py`](../tests/test_telemetry.py) · [`tests/test_problems.py`](../tests/test_problems.py) · [`tests/test_history.py`](../tests/test_history.py) · [`tests/ha/test_dock_and_history.py`](../tests/ha/test_dock_and_history.py) · [`tests/ha/test_telemetry_entities.py`](../tests/ha/test_telemetry_entities.py)
- User documentation: [`docs/telemetry.md`](../docs/telemetry.md) · [`docs/usage.md`](../docs/usage.md) · [`docs/architecture.md`](../docs/architecture.md) · [`docs/validation.md`](../docs/validation.md) · [`docs/evidence/2026-11-23-telemetry.json`](../docs/evidence/2026-11-23-telemetry.json) · [`docs/evidence/2026-11-23-telemetry-quality.json`](../docs/evidence/2026-11-23-telemetry-quality.json) · [`docs/evidence/2026-11-23-temporary-zone-history.json`](../docs/evidence/2026-11-23-temporary-zone-history.json)

### `cleaning-profiles` — Cleaning modes and profiles

- Owner: ha-roomba-home maintainer
- Last verified: 2026-11-23
- Specifications: [`specs/006-cleaning-profiles.md`](./006-cleaning-profiles.md)
- Workflows: Not applicable for this capability.
- Entrypoints: [`custom_components/roomba_home/select.py`](../custom_components/roomba_home/select.py) · [`custom_components/roomba_home/number.py`](../custom_components/roomba_home/number.py) · [`custom_components/roomba_home/switch.py`](../custom_components/roomba_home/switch.py) · [`custom_components/roomba_home/button.py`](../custom_components/roomba_home/button.py)
- Core code: [`custom_components/roomba_home/core/actions.py`](../custom_components/roomba_home/core/actions.py) · [`custom_components/roomba_home/core/application.py`](../custom_components/roomba_home/core/application.py) · [`custom_components/roomba_home/core/cleaning.py`](../custom_components/roomba_home/core/cleaning.py) · [`custom_components/roomba_home/core/cleaning_protocol.py`](../custom_components/roomba_home/core/cleaning_protocol.py) · [`custom_components/roomba_home/core/preferences.py`](../custom_components/roomba_home/core/preferences.py) · [`custom_components/roomba_home/core/commands.py`](../custom_components/roomba_home/core/commands.py) · [`custom_components/roomba_home/coordinator.py`](../custom_components/roomba_home/coordinator.py)
- Tests: [`tests/test_cleaning.py`](../tests/test_cleaning.py) · [`tests/test_application.py`](../tests/test_application.py) · [`tests/test_commands.py`](../tests/test_commands.py) · [`tests/ha/test_coordinator.py`](../tests/ha/test_coordinator.py) · [`tests/ha/test_cleaning_controls.py`](../tests/ha/test_cleaning_controls.py) · [`tests/test_architecture_and_privacy.py`](../tests/test_architecture_and_privacy.py)
- User documentation: [`docs/usage.md`](../docs/usage.md) · [`docs/architecture.md`](../docs/architecture.md) · [`docs/validation.md`](../docs/validation.md) · [`docs/evidence/2026-11-23-cleaning-modes.json`](../docs/evidence/2026-11-23-cleaning-modes.json) · [`docs/evidence/2026-11-23-default-suction.json`](../docs/evidence/2026-11-23-default-suction.json) · [`docs/evidence/2026-11-23-persistent-cleaning-options.json`](../docs/evidence/2026-11-23-persistent-cleaning-options.json) · [`docs/capabilities.md`](../docs/capabilities.md) · [`docs/evidence/2026-11-23-cleaning-quality.json`](../docs/evidence/2026-11-23-cleaning-quality.json)

### `device-capabilities` — Capability&#45;driven integration

- Owner: ha-roomba-home maintainer
- Last verified: 2026-11-23
- Specifications: [`specs/007-device-capabilities.md`](./007-device-capabilities.md)
- Workflows: Not applicable for this capability.
- Entrypoints: [`custom_components/roomba_home/vacuum.py`](../custom_components/roomba_home/vacuum.py) · [`custom_components/roomba_home/button.py`](../custom_components/roomba_home/button.py) · [`custom_components/roomba_home/services.py`](../custom_components/roomba_home/services.py) · [`custom_components/roomba_home/services.yaml`](../custom_components/roomba_home/services.yaml)
- Core code: [`custom_components/roomba_home/core/capabilities.py`](../custom_components/roomba_home/core/capabilities.py) · [`custom_components/roomba_home/core/capability_protocol.py`](../custom_components/roomba_home/core/capability_protocol.py) · [`custom_components/roomba_home/core/dock.py`](../custom_components/roomba_home/core/dock.py) · [`custom_components/roomba_home/core/maps.py`](../custom_components/roomba_home/core/maps.py) · [`custom_components/roomba_home/core/point_maps.py`](../custom_components/roomba_home/core/point_maps.py) · [`custom_components/roomba_home/core/history.py`](../custom_components/roomba_home/core/history.py) · [`custom_components/roomba_home/core/application.py`](../custom_components/roomba_home/core/application.py) · [`custom_components/roomba_home/core/commands.py`](../custom_components/roomba_home/core/commands.py) · [`custom_components/roomba_home/coordinator.py`](../custom_components/roomba_home/coordinator.py) · [`custom_components/roomba_home/robot_updates.py`](../custom_components/roomba_home/robot_updates.py) · [`custom_components/roomba_home/sensor.py`](../custom_components/roomba_home/sensor.py) · [`custom_components/roomba_home/binary_sensor.py`](../custom_components/roomba_home/binary_sensor.py) · [`custom_components/roomba_home/core/schedules.py`](../custom_components/roomba_home/core/schedules.py) · [`custom_components/roomba_home/core/live_maps.py`](../custom_components/roomba_home/core/live_maps.py) · [`custom_components/roomba_home/image.py`](../custom_components/roomba_home/image.py)
- Tests: [`tests/test_maps_and_capabilities.py`](../tests/test_maps_and_capabilities.py) · [`tests/test_point_maps.py`](../tests/test_point_maps.py) · [`tests/test_dock_operations.py`](../tests/test_dock_operations.py) · [`tests/test_history.py`](../tests/test_history.py) · [`tests/ha/test_areas.py`](../tests/ha/test_areas.py) · [`tests/ha/test_dock_and_history.py`](../tests/ha/test_dock_and_history.py) · [`tests/test_cloud_schedules.py`](../tests/test_cloud_schedules.py) · [`tests/test_live_maps.py`](../tests/test_live_maps.py) · [`tests/ha/test_live_map_entities.py`](../tests/ha/test_live_map_entities.py)
- User documentation: [`docs/capabilities.md`](../docs/capabilities.md) · [`docs/api.md`](../docs/api.md) · [`docs/architecture.md`](../docs/architecture.md) · [`docs/validation.md`](../docs/validation.md) · [`docs/usage.md`](../docs/usage.md) · [`docs/telemetry.md`](../docs/telemetry.md) · [`docs/evidence/2026-11-23-cleaning-modes.json`](../docs/evidence/2026-11-23-cleaning-modes.json) · [`docs/evidence/2026-11-23-point-clean.json`](../docs/evidence/2026-11-23-point-clean.json) · [`docs/evidence/2026-11-23-spot-and-live-map.json`](../docs/evidence/2026-11-23-spot-and-live-map.json) · [`docs/evidence/2026-11-24-live-progress.json`](../docs/evidence/2026-11-24-live-progress.json)

### `mission-detail-and-map-card` — Mission Detail and Interactive Floor Maps

- Owner: ha-roomba-home maintainer
- Last verified: 2026-11-24
- Specifications: [`specs/008-mission-detail-and-map-card.md`](./008-mission-detail-and-map-card.md)
- Workflows: [`.github/workflows/validate.yml`](../.github/workflows/validate.yml)
- Entrypoints: [`custom_components/roomba_home/__init__.py`](../custom_components/roomba_home/__init__.py)
- Core code: [`custom_components/roomba_home/core/history.py`](../custom_components/roomba_home/core/history.py) · [`custom_components/roomba_home/core/live_maps.py`](../custom_components/roomba_home/core/live_maps.py) · [`custom_components/roomba_home/core/point_maps.py`](../custom_components/roomba_home/core/point_maps.py) · [`custom_components/roomba_home/core/mqtt.py`](../custom_components/roomba_home/core/mqtt.py) · [`custom_components/roomba_home/map_api.py`](../custom_components/roomba_home/map_api.py) · [`custom_components/roomba_home/frontend/roomba-home-map-card.js`](../custom_components/roomba_home/frontend/roomba-home-map-card.js)
- Tests: [`tests/test_history.py`](../tests/test_history.py) · [`tests/test_mqtt.py`](../tests/test_mqtt.py) · [`tests/ha/test_live_map_entities.py`](../tests/ha/test_live_map_entities.py) · [`tests/ha/test_roomba_map_api.py`](../tests/ha/test_roomba_map_api.py)
- User documentation: [`README.md`](../README.md) · [`docs/usage.md`](../docs/usage.md) · [`docs/telemetry.md`](../docs/telemetry.md) · [`docs/validation.md`](../docs/validation.md) · [`docs/evidence/2026-11-24-live-progress.json`](../docs/evidence/2026-11-24-live-progress.json)

## Maintenance contract

1. Read the relevant SDD before changing a catalogued capability.
2. Change the SDD, catalog evidence, tests, and user documentation together when
   behavior or an architecture boundary changes.
3. Use repository-relative paths in `catalog.json`; each path is validated and every
   top-level product SDD must have exactly one capability owner.
4. Validate specification structure, catalog ownership/evidence, and this generated
   view with tooling verified for the selected repository. Command declarations
   and structural validation are not proof that product tests have executed.
