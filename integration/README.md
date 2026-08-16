# Native Home Assistant Integration

Phase 1 provides a native REST integration under
`custom_components/factorio_assistant`.

It uses one shared `DataUpdateCoordinator` with a 30-second refresh interval.
The coordinator fetches `/api/world` and `/api/status` once per cycle; entities
do not create independent polling loops.

Phase 1 entities:

- World tick and game speed
- Current research and research progress
- Enemy evolution
- Rockets launched
- Save and installed-mod counts
- Factorio server running
- Factorio Assistant bridge health

The integration also exposes Home Assistant services for AAI vehicle control:
`get_aai_vehicle_summary`, `follow_aai_vehicle`, `drive_aai_vehicle`, and
`mine_aai_vehicle`.

Copy `integration/custom_components/factorio_assistant` into Home Assistant's
`custom_components` directory, restart Home Assistant, and add **Factorio
Assistant** from Settings > Devices & services. The default test endpoint is
`homeassistant.local` on REST port `8098`. Supply the add-on API
token when the endpoint is reached through that hostname; unauthenticated
requests return `403` outside the trusted Home Assistant network.

MQTT discovery remains unchanged. Dynamic players, surfaces, event entities,
commands, and factory controls are deferred to later phases.