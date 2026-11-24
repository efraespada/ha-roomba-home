# Documentation

Roomba Home provides [telemetry, progress, and problem events](telemetry.md),
cleaning modes, maps, history, dock actions, and default mopping settings where
the robot reports the required capabilities. The first local release introduced
the native client, the Home Assistant integration, and research tools. The
validation report distinguishes the evidence for each release.

| Task | Document |
|---|---|
| Check what works and what still needs verification | [Validation and limits](validation.md) |
| Review the implementation | [Implementation report](implementation-report.md) |
| Check functions by model | [Capability matrix](capabilities.md) |
| Install and configure Home Assistant | [Installation](installation.md) |
| Check the icon and its formats | [Branding](branding.md) |
| Use entities and actions | [Usage](usage.md) |
| Understand authentication, HTTP reads, and MQTT | [API reference](api.md) |
| Understand the design and planned changes | [Architecture](architecture.md) |
| Set up tools and repeat tests | [Development](development.md) |
| Protect credentials, maps, and captures | [Privacy](../SECURITY.md) |
| Review contracts and acceptance criteria | [SDD catalog](../specs/CATALOG.md) |
| Review the SDD standard and template | [SDD standard](../specs/README.md) |

The [Home Assistant integration SDD](../specs/003-home-assistant.md) documents
the integration contract. The catalog identifies pending work separately.
