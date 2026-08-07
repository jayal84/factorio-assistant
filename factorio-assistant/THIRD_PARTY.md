# Third-Party Components

## Factorio

The add-on bundles and uses Factorio headless server `2.0.77`, including its
game data and installed mod assets. These materials remain subject to the
licenses and terms provided by Wube Software and the respective mod authors.

## wube/factorio-data

This project includes a version-pinned snapshot of the Factorio data
repository at `2.0.77` for reference metadata, changelog information, and
source inspection. The container image also downloads selected files from the
same pinned revision at build time.

- Upstream repository: https://github.com/wube/factorio-data
- Pinned revision: https://github.com/wube/factorio-data/tree/2.0.77
- Repository description: https://github.com/wube/factorio-data/blob/2.0.77/README.md

The repository is automatically generated and made publicly available by Wube
Software for tracking Factorio Lua prototype definitions. No separate license
file is included in that repository; users should consult Wube Software for
the applicable terms governing its contents and Factorio game data.

## DQOL Resource Monitor

The Factorio Assistant mod includes an integrated and modified copy of the
DQOL Resource Monitor functionality, based on version `1.6.5`. This includes
the resource-monitor UI, site tracking, resource processing, settings,
localization, and supporting assets. The original `dqol-*` identifiers remain
in the integrated code for save and compatibility purposes.

- Upstream project: https://github.com/devdot/dqol-resource-monitor
- Factorio Mod Portal: https://mods.factorio.com/mod/dqol-resource-monitor
- Author: devdot
- License: MIT: https://opensource.org/licenses/MIT

The standalone `dqol-resource-monitor` mod is disabled when the integrated
Factorio Assistant mod is enabled, so both implementations do not run against
the same save.