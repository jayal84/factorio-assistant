# Roadmap

Planned improvements for the Factorio Home Assistant add-on.

## Home Assistant Integration

Build a native Home Assistant integration that exposes Factorio controls, telemetry, and catalog queries as typed services and entities. The existing MQTT/RCON bridge will remain the initial transport while the integration is developed.

## Telemetry Performance

Explore cached or incremental pollution aggregation so pollution telemetry can become more frequent without adding broad simulation-thread work.
