# Changelog

## 0.1.8 - Sender naming and signal units

- Name Home Assistant devices `Factorio Assistant Sender: <description>`.
- Remove the misleading `signals` unit of measurement from signal sensors.

## 0.1.7 - Sender input connectors

- Changed the Sender prototype from a constant combinator to an arithmetic
	combinator so it exposes circuit-network input connectors.
- Read the configured red and green input connectors while preserving the
	telemetry and Home Assistant contracts.
- Renamed the player-facing device to Factorio Assistant Sender.

## 0.1.6 - Combinator naming and diagnostics

- Use the native combinator description as the Home Assistant device name.
- Fall back to the entity name tag when no description is set.
- Log rate-limited circuit connector read failures for live troubleshooting.

## 0.1.5 - Factorio 2.0.77 compatibility

- Read combinator signals with `get_signals` and the valid
	`combinator_output_red` and `combinator_output_green` connector IDs.
- Removed the obsolete two-argument `get_circuit_network` call that silently
	produced empty signal snapshots on Factorio 2.0.77.
- Removed custom entity GUI handlers so the native constant-combinator property
	window remains entirely under Factorio's control.

## 0.1.4 - Telemetry crash fix

- Fixed the combinator telemetry crash caused by `reader_snapshot` calling `position_data` before the local helper was declared.

## 0.1.3 - Blue combinator render

- Tint only the cloned combinator's main render sprite blue while preserving the base activity LEDs, shadows, and circuit connection data.

## 0.1.2 - Combinator UI compatibility

- Removed unsupported `icon_tint` fields from the cloned entity and item prototypes. The bundled Factorio 2.0.77 reference data does not use this field for either prototype type.
- Added explicit localized descriptions for the combinator entity and item so the Factoriopedia and prototype description UI has valid localization targets.
- Kept the 0.1.1 circuit-network API correction and combinator telemetry safety switch.

## 0.1.1 - Combinator stability and configurable telemetry

- Attempted to fix the Factorio Assistant Combinator crash by calling the Factorio 2.0 circuit-network API with the shared `combinator_output` connector and the red or green wire type as separate arguments. The previous implementation selected color-specific connector IDs and did not use its connector argument.
- Added a per-save combinator telemetry safety switch, disabled by default while compatibility is validated.
- Added per-save controls for scan interval, wire selection, signal limits, event telemetry, world snapshots, and inventory details.
- Added defensive limits around combinator signal snapshots and retained protected circuit-network reads.

## 0.1.0 - Initial release

- Added structured player, world, research, and factory telemetry.
- Added player join, leave, death, surface-change, and enemy-attack events.
- Added the Factorio Assistant Combinator for circuit-network signal reading.
- Added validated remote-interface commands for the Home Assistant bridge.
- Added optional support for toggling pollution and enemy evolution at runtime.
