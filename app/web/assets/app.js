const APP = document.getElementById('app');

const PAGE_GROUPS = [
  {
    label: 'Operations',
    items: [
      { key: 'overview', label: 'Overview', subtitle: 'Live health, world state, and alerts.' },
      { key: 'world', label: 'World', subtitle: 'Players, surfaces, and game telemetry.' },
      { key: 'logistics', label: 'Logistics', subtitle: 'LTN controls and train telemetry.' },
        { key: 'resources', label: 'Resources', subtitle: 'Pinned resource sites and extraction telemetry.' },
    ],
  },
  {
    label: 'Planning',
    items: [
      { key: 'browse', label: 'Browse', subtitle: 'Catalog search and item detail.' },
      { key: 'production', label: 'Production', subtitle: 'Recipe and machine planning.' },
    ],
  },
  {
    label: 'Administration',
    items: [
      { key: 'storage', label: 'Storage', subtitle: 'Saves, backups, and retention.' },
      { key: 'system', label: 'System', subtitle: 'Bridge, Factorio, and ingress details.' },
    ],
  },
];

const STATE = {
  page: getPageFromHash(),
  snapshot: {
    status: null,
    world: null,
    telemetry: [],
    catalogMeta: null,
    loading: true,
    error: null,
    refreshedAt: null,
  },
  ui: {
    logistics: {
      ltnAction: 'clear_all_surface_connections',
      ltnName: '',
      ltnTrainId: '0',
      ltnOldTrainId: '0',
      ltnNewTrainId: '0',
      ltnScheduleIndex: '0',
      ltnStatus: 'Ready',
    },
    browse: {
      query: '',
      kind: 'item',
      results: [],
      selected: null,
      loading: false,
      meta: 'Ready',
    },
    production: {
      goal: 'Make 60 iron plates per minute',
      itemsText: '[{"name":"iron-plate","rate":60}]',
      knownRecipesText: '[]',
      output: null,
      status: 'Ready',
    },
  },
};

function getPageFromHash() {
  const value = window.location.hash.replace(/^#/, '');
  return isKnownPage(value) ? value : 'overview';
}

function isKnownPage(value) {
  return ['overview', 'world', 'resources', 'logistics', 'browse', 'production', 'storage', 'system'].includes(value);
}

function apiUrl(path) {
  return new URL(path.replace(/^\//, ''), document.baseURI).toString();
}

async function requestJson(path, init) {
  const response = await fetch(apiUrl(path), {
    cache: 'no-store',
    ...init,
    headers: {
      ...(init && init.headers ? init.headers : {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const message = payload && typeof payload === 'object' && payload.error ? String(payload.error) : 'Request failed.';
    throw new Error(message);
  }
  return payload;
}

function getStatus() {
  return requestJson('/api/status');
}

function getWorld() {
  return requestJson('/api/world');
}

function getTelemetry(limit = 50) {
  return requestJson(`/api/telemetry/events?limit=${encodeURIComponent(String(limit))}`);
}

function getCatalog(params) {
  return requestJson(`/api/catalog?${params.toString()}`);
}

function getCatalogEntry(name, kind = '') {
  return requestJson(`/api/catalog/entry?${new URLSearchParams({ name, kind, detail: 'full' }).toString()}`);
}

function getProductionPlan(items, knownRecipes = []) {
  return requestJson('/api/catalog/production', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items, known_recipes: knownRecipes }),
  });
}

function callModRemote(method, payload) {
  const command = `/silent-command local ok,result=pcall(remote.call,${JSON.stringify('factorio_assistant')},${JSON.stringify(method)},${JSON.stringify(JSON.stringify(payload))});rcon.print(helpers.table_to_json({ok=ok,result=result}))`;
  return requestJson('/api/rcon', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command }),
  }).then((response) => {
    if (typeof response.response !== 'string' || !response.response) {
      throw new Error(response.error || 'RCON response missing.');
    }
    const envelope = JSON.parse(response.response);
    if (!envelope || envelope.ok !== true) {
      throw new Error(envelope && envelope.error ? envelope.error : 'Remote command failed.');
    }
    return envelope.result;
  });
}

function dispatchLtnCommand(payload) {
  return callModRemote('ltn_command', payload);
}

function catalogRecordLabel(entry) {
  if (!entry) return 'Unknown';
  return entry.localized_name || entry.name || 'Unknown';
}

function normalizeRecord(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function normalizePlayers(value) {
  if (Array.isArray(value)) {
    return value.filter((entry) => entry && typeof entry === 'object');
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).map(([name, details]) => ({ name, ...(details || {}) }));
  }
  return [];
}

function normalizeSurfaces(value) {
  if (!Array.isArray(value)) return [];
  return value.filter((entry) => entry && typeof entry === 'object');
}

function normalizePinnedResources(value) {
  if (!Array.isArray(value)) return [];
  return value.filter((entry) => entry && typeof entry === 'object');
}

function formatNumber(value, digits = 0) {
  const parsed = Number(value ?? 0);
  if (!Number.isFinite(parsed)) return '—';
  return parsed.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function formatPercent(value, digits = 1) {
  const parsed = Number(value ?? 0);
  if (!Number.isFinite(parsed)) return '—';
  return `${(parsed * 100).toFixed(digits)}%`;
}

function formatTime(value) {
  const seconds = Number(value ?? 0);
  if (!Number.isFinite(seconds) || seconds <= 0) return '—';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

function formatGameTime(value) {
  const raw = Number(value ?? 0);
  return Number.isFinite(raw) ? raw.toLocaleString() : String(value ?? '—');
}

function formatFileSize(value) {
  const bytes = Number(value ?? 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function factorioTag(status) {
  if (!status) return 'Loading';
  return String(status.factorio && typeof status.factorio === 'object' ? status.factorio.running ? 'Online' : 'Offline' : 'Unknown');
}

function factorioStatusLabel(status) {
  if (!status || !status.factorio || typeof status.factorio !== 'object') return 'Unknown';
  return String(status.factorio.running ? 'Online' : 'Offline');
}

function bridgeStatusLabel(status) {
  if (!status || !status.bridge || typeof status.bridge !== 'object') return 'Unknown';
  return String(status.bridge.running ? 'Connected' : 'Stopped');
}

async function refreshSnapshot() {
  try {
    const [status, world, telemetry, catalogMeta] = await Promise.all([
      getStatus(),
      getWorld(),
      getTelemetry(50),
      getCatalog(new URLSearchParams({ limit: '1', offset: '0' })),
    ]);
    STATE.snapshot = {
      status,
      world,
      telemetry: Array.isArray(telemetry.events) ? telemetry.events : [],
      catalogMeta,
      loading: false,
      error: null,
      refreshedAt: Date.now(),
    };
  } catch (error) {
    STATE.snapshot = {
      ...STATE.snapshot,
      loading: false,
      error: error instanceof Error ? error.message : 'Refresh failed.',
    };
  }
  render();
}

function render() {
  STATE.page = getPageFromHash();
  APP.innerHTML = `
    <div class="app-shell">
      <aside class="sidebar">
        ${renderSidebar()}
      </aside>
      <main class="workspace">
        ${renderPage()}
      </main>
    </div>
  `;
  bindShell();
}

function renderSidebar() {
  const status = STATE.snapshot.status;
  const title = status && status.factorio && typeof status.factorio === 'object' && status.factorio.name ? String(status.factorio.name) : 'Factorio Assistant';
  const bridgeOnline = Boolean(status && status.bridge && typeof status.bridge === 'object' && status.bridge.running);
  const factorioOnline = Boolean(status && status.factorio && typeof status.factorio === 'object' && status.factorio.running);
  const refreshedAt = STATE.snapshot.refreshedAt ? new Date(STATE.snapshot.refreshedAt).toLocaleTimeString() : 'Waiting';

  return `
    <div class="brand">
      <div class="brand-mark">⚙</div>
      <div>
        <p class="eyebrow">FACTORIO OPERATIONS CONSOLE</p>
        <h2>${escapeHtml(title)}</h2>
        <p class="sidebar-subtitle">${bridgeOnline ? 'Bridge online' : 'Bridge unavailable'} · ${factorioOnline ? 'Factorio online' : 'Factorio offline'}</p>
      </div>
    </div>
    <div class="sidebar-statuses">
      ${statusChip('Factorio', factorioOnline ? 'Online' : 'Offline', factorioOnline ? 'good' : 'bad')}
      ${statusChip('Bridge', bridgeOnline ? 'Connected' : 'Stopped', bridgeOnline ? 'good' : 'bad')}
      ${statusChip('Updated', refreshedAt, 'neutral')}
    </div>
    <nav class="sidebar-nav" aria-label="Console pages">
      ${PAGE_GROUPS.map(renderGroup).join('')}
    </nav>
    <button class="refresh-button" data-action="refresh-all">Refresh all data</button>
  `;
}

function renderGroup(group) {
  return `
    <div class="nav-group">
      <p class="nav-group-label">${escapeHtml(group.label)}</p>
      ${group.items.map((item) => `
        <button class="nav-item ${item.key === STATE.page ? 'active' : ''}" data-page="${item.key}">
          <span>
            <strong>${escapeHtml(item.label)}</strong>
            <small>${escapeHtml(item.subtitle)}</small>
          </span>
          <i></i>
        </button>
      `).join('')}
    </div>
  `;
}

function statusChip(label, value, tone) {
  return `<div class="status-chip ${tone}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function renderPage() {
  const page = STATE.page;
  const title = pageTitle(page);
  const subtitle = pageSubtitle(page);

  return `
    <section class="page-shell">
      <header class="page-header">
        <div>
          <p class="eyebrow">FACTORIO ASSISTANT</p>
          <h1>${escapeHtml(title)}</h1>
          <p class="lede">${escapeHtml(subtitle)}</p>
        </div>
        <div class="page-actions">
          <button class="ghost-button" data-action="refresh-all">Refresh page data</button>
        </div>
      </header>
      <div class="page-content">
        ${STATE.snapshot.error ? `<div class="alert">${escapeHtml(STATE.snapshot.error)}</div>` : ''}
        ${renderCurrentPage(page)}
      </div>
    </section>
  `;
}

function pageTitle(page) {
  return {
    overview: 'Overview',
    world: 'World',
    resources: 'Resources',
    logistics: 'Logistics',
    browse: 'Browse',
    production: 'Production',
    storage: 'Storage',
    system: 'System',
  }[page] || 'Overview';
}

function pageSubtitle(page) {
  return {
    overview: 'Live status, health, and the most important alerts.',
    world: 'Players, surfaces, and the latest game snapshot.',
    resources: 'Pinned resource sites and extraction telemetry.',
    logistics: 'LTN helpers and train telemetry grouped together.',
    browse: 'Catalog search with grouped results and details.',
    production: 'Build and inspect recipe plans from live catalog data.',
    storage: 'Saves, backups, restore points, and telemetry.',
    system: 'Bridge, Factorio, and ingress service diagnostics.',
  }[page] || '';
}

function renderCurrentPage(page) {
  switch (page) {
    case 'world':
      return renderWorldPage();
    case 'resources':
      return renderResourcesPage();
    case 'logistics':
      return renderLogisticsPage();
    case 'browse':
      return renderBrowsePage();
    case 'production':
      return renderProductionPage();
    case 'storage':
      return renderStoragePage();
    case 'system':
      return renderSystemPage();
    case 'overview':
    default:
      return renderOverviewPage();
  }
}

function renderOverviewPage() {
  const status = STATE.snapshot.status || {};
  const world = STATE.snapshot.world || {};
  const players = normalizePlayers(world.players || status.players || []);
  const connectedPlayers = players.filter((player) => player.connected);
  const visibleTelemetry = STATE.snapshot.telemetry.filter((event) => event.event !== 'state_snapshot');
  const recentEvents = visibleTelemetry.slice(-1).reverse();
  const storage = status.storage && typeof status.storage === 'object' ? status.storage : {};
  const diagnostics = status.diagnostics && typeof status.diagnostics === 'object' ? status.diagnostics : {};

  return `
    <div class="page-stack">
      ${metricGrid([
        ['Active players', formatNumber(world.players_online ?? connectedPlayers.length), `${players.length} known profiles`],
        ['Game time', formatGameTime(world.game_time), `Day ${formatNumber(world.game_day)}`],
        ['Research', String(world.research_localized_name || world.research || 'None'), `${formatPercent(world.research_progress ?? 0)} complete`],
        ['Events', formatNumber(STATE.snapshot.telemetry.length), `${recentEvents.length} shown`],
      ])}

      <div class="two-column-grid">
        ${card('Server', factorioTag(status), 'Game process, bridge, and connection summary.', definitionList([
          ['Factorio', factorioStatusLabel(status)],
          ['Bridge', bridgeStatusLabel(status)],
          ['Save file', storage.save_details && typeof storage.save_details === 'object' ? String(storage.save_details.configured || '—') : '—'],
          ['RCON', status.connection && typeof status.connection === 'object' ? String(status.connection.rcon_port || '—') : '—'],
        ]))}
        ${card('Diagnostics', 'Health', 'Current bridge and system health.', definitionList([
          ['CPU', `${formatNumber(diagnostics.cpu_usage, 1)}%`],
          ['Memory', `${formatNumber(diagnostics.mem_usage, 1)}%`],
          ['Uptime', formatTime(diagnostics.uptime)],
          ['Watchdog', status.watchdog && typeof status.watchdog === 'object' ? (status.watchdog.healthy ? 'Healthy' : 'Problem') : '—'],
        ]))}
      </div>

      <div class="two-column-grid">
        ${card('World snapshot', 'Live', 'World totals and the latest state snapshot.', definitionList([
          ['Tick', formatNumber(world.tick)],
          ['Speed', formatNumber(world.speed, 2)],
          ['Surface count', formatNumber(world.surface_count)],
          ['Rockets launched', formatNumber(world.rockets_launched)],
        ]) + compactList(normalizeSurfaces(world.surfaces).slice(0, 3).map((surface) => compactRow(String(surface.name || 'Unknown surface'), `${formatNumber(surface.pollution, 1)} pollution`)), 'No surface telemetry reported yet.'))}
        ${card('Recent events', `${recentEvents.length} shown`, 'The latest structured telemetry from the mod.', compactList(recentEvents.map((event) => eventRow(event)), 'No telemetry events yet.'))}
      </div>

      <div class="two-column-grid">
        ${card('Players', `${players.length} known`, 'Merged into the world view so player state stays with live telemetry.', playerGrid(players))}
        ${card('Storage summary', 'Quick view', 'The detailed backup tools live in the Storage page.', definitionList([
          ['Saves', formatNumber(storage.save_count)],
          ['Mods', formatNumber(storage.mod_count)],
          ['Configured save', storage.save_details && typeof storage.save_details === 'object' ? String(storage.save_details.configured || '—') : '—'],
          ['Directory', storage.save_details && typeof storage.save_details === 'object' ? String(storage.save_details.directory || '—') : '—'],
        ]) + `<button class="inline-button" data-action="refresh-all">Update overview</button>`)}
      </div>
    </div>
  `;
}

function renderWorldPage() {
  const world = STATE.snapshot.world || {};
  const players = normalizePlayers(world.players || (STATE.snapshot.status && STATE.snapshot.status.players) || []);
  const connectedPlayers = players.filter((player) => player.connected).sort(sortByName);
  const offlinePlayers = players.filter((player) => !player.connected).sort(sortByName);
  const surfaces = normalizeSurfaces(world.surfaces);

  return `
    <div class="page-stack">
      ${metricGrid([
        ['Tick', formatNumber(world.tick), `Speed ${formatNumber(world.speed, 2)}`],
        ['Game day', formatNumber(world.game_day), formatGameTime(world.game_time)],
        ['Research', String(world.research_localized_name || world.research || 'None'), `${formatPercent(world.research_progress ?? 0)} complete`],
        ['Surfaces', formatNumber(world.surface_count ?? surfaces.length), String(world.surface_names || 'No surface list')],
      ])}

      <div class="two-column-grid">
        ${card('Players online', formatNumber(connectedPlayers.length), 'Connected players stay grouped above offline profiles.', `${playerGrid(connectedPlayers, true)}<h3 class="subheading">Offline profiles</h3>${playerGrid(offlinePlayers, false)}`)}
        ${card('Surface summary', `${surfaces.length} surfaces`, 'Pollution and surface-level resource totals.', compactList(surfaces.slice().sort(sortByName).map((surface) => compactRow(String(surface.name || 'Unknown surface'), `${formatNumber(surface.pollution, 1)} pollution`)), 'No surface telemetry reported yet.'))}
      </div>

    </div>
  `;
}

function renderResourcesPage() {
  const world = STATE.snapshot.world || {};
  const resourceMonitor = normalizeRecord(world.resource_monitor);
  const hasResourceMonitor = Array.isArray(resourceMonitor.surfaces) || Object.keys(resourceMonitor).length > 0;
  const monitoredSurfaces = normalizeSurfaces(resourceMonitor.surfaces);
  const surfaces = hasResourceMonitor ? monitoredSurfaces : normalizeSurfaces(world.surfaces);
  const resources = surfaces.flatMap((surface) => normalizePinnedResources(surface.tracked_resources || surface.pinned_resources).map((resource) => ({ ...resource, surface: String(surface.name || 'Unknown') })));
  const sortedResources = resources.slice().sort((left, right) => Number(right.amount || 0) - Number(left.amount || 0));

  return `
    <div class="page-stack">
      ${metricGrid([
        ['Sites', formatNumber(resources.length), `${surfaces.length} surfaces`],
        ['Largest site', String(sortedResources[0]?.name || '—'), resources.length ? `${formatNumber(sortedResources[0]?.amount)} remaining` : 'No pinned resources'],
        ['Surfaces', formatNumber(surfaces.length), 'Tracked across the map'],
        ['Telemetry', String(world.tick ? `Tick ${formatNumber(world.tick)}` : 'Waiting'), String(world.game_time || '—')],
      ])}

      ${card('Pinned resources', `${resources.length} sites`, 'Grouped across all surfaces with the most important numbers first.', resourceGrid(sortedResources))}
    </div>
  `;
}

function renderLogisticsPage() {
  const world = STATE.snapshot.world || {};
  const ltn = normalizeRecord(world.ltn);
  const ltnTrains = Array.isArray(ltn.trains) ? ltn.trains : [];
  const ui = STATE.ui.logistics;

  return `
    <div class="page-stack">
      ${metricGrid([
        ['LTN trains', formatNumber(ltn.train_count), `${formatNumber(ltn.scheduled_train_count)} scheduled`],
        ['Manual trains', formatNumber(ltn.manual_train_count), String(ltn.installed ? 'LTN installed' : 'LTN absent')],
      ])}

      <div class="single-column-grid">
        ${card('LTN control', ui.ltnStatus, 'Limited helpers are exposed from the bridge and grouped here with the train snapshot.', `
          ${formGrid([
            selectField('Action', 'logistics', 'ltnAction', ui.ltnAction, ['clear_all_surface_connections', 'exclude_from_fuel_schedule', 'get_or_create_next_temp_stop', 'get_next_logistic_stop', 'reassign_delivery']),
            textField('Locomotive or prototype name', 'logistics', 'ltnName', ui.ltnName, 'optional name for fuel exclusion'),
            textField('Train id', 'logistics', 'ltnTrainId', ui.ltnTrainId, '0', 'number'),
            textField('Old train id', 'logistics', 'ltnOldTrainId', ui.ltnOldTrainId, '0', 'number'),
            textField('New train id', 'logistics', 'ltnNewTrainId', ui.ltnNewTrainId, '0', 'number'),
            textField('Schedule index', 'logistics', 'ltnScheduleIndex', ui.ltnScheduleIndex, '0', 'number'),
          ])}
          <button class="primary-button" data-action="send-ltn">Run LTN action</button>
        `)}
        ${card('Train snapshot', `${formatNumber(ltnTrains.length)} trains`, 'Direct read-only discovery so the UI can stay honest about what LTN reports.', `<div class="train-list">${ltnTrains.map((train) => `
          <article class="train-card">
            <strong>Train ${formatNumber(train.id)}</strong>
            <span>${escapeHtml(String(train.surface || 'Unknown surface'))}</span>
            <small>${escapeHtml(String(train.state || 'unknown'))}</small>
            <small>${escapeHtml(String(train.manual_mode ? 'Manual' : 'Automatic'))}</small>
          </article>
        `).join('') || '<p class="empty-state">No train snapshot available.</p>'}</div>`)}
      </div>
    </div>
  `;
}

function renderBrowsePage() {
  const ui = STATE.ui.browse;
  const detailBody = ui.selected
    ? `
      <div class="detail-panel">
        <h3>${escapeHtml(catalogRecordLabel(ui.selected))}</h3>
        ${definitionList([
          ['Name', ui.selected.name],
          ['Kind', String(ui.selected.kind || ui.selected.type || 'unknown')],
          ['Description', String(ui.selected.localized_description || '—')],
        ])}
        <details class="json-block" open>
          <summary>Technical data</summary>
          <pre>${escapeHtml(JSON.stringify(ui.selected, null, 2))}</pre>
        </details>
      </div>
    `
    : '<p class="empty-state">Select an entry to inspect its data.</p>';

  return `
    <div class="page-stack">
      <div class="two-column-grid">
        ${card('Catalog search', ui.meta, 'Query names, descriptions, and internal IDs without reusing the old layout.', `
          <div class="search-row">
            ${textField('Search', 'browse', 'query', ui.query, 'iron-plate, assembling-machine-2, or any data')}
            ${selectField('Kind', 'browse', 'kind', ui.kind, ['item', 'fluid', 'recipe', 'technology', 'entity', 'module', 'equipment', 'resource', 'signal', 'tile', 'setting'])}
          </div>
          <button class="primary-button" data-action="browse-search">${ui.loading ? 'Searching...' : 'Search catalog'}</button>
          <div class="result-list">${ui.results.map((entry) => `
            <button class="result-row ${ui.selected && ui.selected.name === entry.name ? 'active' : ''}" data-catalog-name="${escapeHtml(entry.name)}" data-catalog-kind="${escapeHtml(entry.kind || '')}">
              <strong>${escapeHtml(catalogRecordLabel(entry))}</strong>
              <span>${escapeHtml(String(entry.kind || entry.type || 'unknown'))}</span>
            </button>
          `).join('')}</div>
        `)}
        ${card('Catalog detail', ui.selected ? (ui.selected.kind || 'entry') : '—', 'The right side is dedicated to details so the browser feels like a workspace, not a stacked list.', detailBody)}
      </div>
      <div class="card section-card">
        <p class="helper-text">Open a result, then use the detail pane to inspect the raw export if you need to wire production or planning controls around it.</p>
      </div>
    </div>
  `;
}

function renderProductionPage() {
  const ui = STATE.ui.production;
  return `
    <div class="page-stack">
      <div class="two-column-grid">
        ${card('Plan input', ui.status, 'Simple form inputs with JSON payloads when needed.', `
          ${formGrid([
            textField('Goal', 'production', 'goal', ui.goal, 'What should the factory produce?'),
            textAreaField('Items', 'production', 'itemsText', ui.itemsText),
            textAreaField('Known recipes', 'production', 'knownRecipesText', ui.knownRecipesText),
          ])}
          <button class="primary-button" data-action="production-plan">Plan production</button>
        `)}
        ${card('Plan output', ui.output ? String(ui.output.detail || 'Live') : 'Idle', 'The result is shown as grouped output rather than a wall of text.', ui.output ? `<pre class="json-output">${escapeHtml(JSON.stringify(ui.output, null, 2))}</pre>` : `<p class="empty-state">Run a plan to see the chain and machine breakdown.</p><p class="helper-text">Goal: ${escapeHtml(ui.goal)}</p>`)}
      </div>
      ${card('Current telemetry', 'Context', 'Production planning can inspect the current world snapshot while you work.', definitionList([
        ['Research', String(STATE.snapshot.world && STATE.snapshot.world.research || 'None')],
        ['Technologies', `${formatNumber(STATE.snapshot.world && STATE.snapshot.world.technologies_researched)} / ${formatNumber(STATE.snapshot.world && STATE.snapshot.world.technologies_total)}`],
        ['Players online', formatNumber(STATE.snapshot.world && STATE.snapshot.world.players_online)],
        ['Surfaces', formatNumber(STATE.snapshot.world && STATE.snapshot.world.surface_count)],
      ]))}
    </div>
  `;
}

function renderStoragePage() {
  const status = STATE.snapshot.status || {};
  const storage = status.storage && typeof status.storage === 'object' ? status.storage : {};
  const saveDetails = storage.save_details && typeof storage.save_details === 'object' ? storage.save_details : {};
  const files = Array.isArray(saveDetails.files) ? saveDetails.files : [];
  const autosaves = files.filter((file) => file.autosave);
  const backups = files.filter((file) => file.backup);
  const saves = files.filter((file) => !file.autosave && !file.backup);

  return `
    <div class="page-stack">
      ${metricGrid([
        ['Files', formatNumber(files.length), `${formatNumber(autosaves.length)} autosaves`],
        ['Backups', formatNumber(backups.length), `${formatNumber(saves.length)} saves`],
        ['Configured save', String(saveDetails.configured || '—'), String(saveDetails.directory || '—')],
        ['Retention', String(status.restore && typeof status.restore === 'object' ? status.restore.state || 'ready' : 'ready'), String(saveDetails.backup_max_saves || 14)],
      ])}

      <div class="three-column-grid">
        ${card('Save summary', `${formatNumber(files.length)} files`, 'Backup controls stay grouped here instead of in the main shell.', definitionList([
          ['Directory', String(saveDetails.directory || '—')],
          ['Backup mode', String(saveDetails.backup_mode || 'interval')],
          ['Interval', `${formatNumber(saveDetails.backup_interval_hours || 12)} hours`],
          ['Max saves', formatNumber(saveDetails.backup_max_saves || 14)],
        ]) + `<button class="inline-button" data-action="refresh-all">Refresh save data</button>`)}
        ${card('Autosaves', formatNumber(autosaves.length), 'Internal autosaves are shown separately so they are easy to scan.', compactList(autosaves.map((file) => compactRow(String(file.name || 'Autosave'), formatFileSize(file.size))), 'No autosaves found.'))}
        ${card('Recent telemetry', `${formatNumber(visibleTelemetry.length)} events`, 'The storage view still shows recent events, but the top-level layout is now cleaner.', compactList(visibleTelemetry.slice(-8).reverse().map((event) => eventRow(event, true)), 'No telemetry events yet.'))}
      </div>

      ${card('World files', 'Group by type', 'Configured save, backups, and autosaves are grouped into the categories that make the most sense.', `
        <div class="file-group-grid">
          ${fileGroup('Configured save', saves.filter((file) => String(file.name || '') === String(saveDetails.configured || ''))) }
          ${fileGroup('Backups', backups)}
          ${fileGroup('Autosaves', autosaves)}
        </div>
      `)}
    </div>
  `;
}

function renderSystemPage() {
  const status = STATE.snapshot.status || {};
  const factorio = status.factorio && typeof status.factorio === 'object' ? status.factorio : {};
  const bridge = status.bridge && typeof status.bridge === 'object' ? status.bridge : {};
  const processes = status.processes && typeof status.processes === 'object' ? status.processes : {};
  const diagnostics = status.diagnostics && typeof status.diagnostics === 'object' ? status.diagnostics : {};
  const restore = status.restore && typeof status.restore === 'object' ? status.restore : {};
  const connection = status.connection && typeof status.connection === 'object' ? status.connection : {};

  return `
    <div class="page-stack">
      ${metricGrid([
        ['Factorio', String(factorio.running ? 'Online' : 'Offline'), `v${String(factorio.version || '—')}`],
        ['Bridge', String(bridge.running ? 'Connected' : 'Stopped'), String(bridge.rcon_password_present ? 'RCON ready' : 'Waiting for credentials')],
        ['Web', String(processes.web ? 'Running' : 'Stopped'), String(processes.factorio ? 'Factorio online' : 'Factorio offline')],
        ['Restore', String(restore.state || 'ready'), String(restore.message || 'No active restore')],
      ])}

      <div class="two-column-grid">
        ${card('Connection', String(connection.ip || '—'), 'Ingress host, ports, and runtime connection details.', definitionList([
          ['Hostname', String(connection.hostname || '—')],
          ['IP address', String(connection.ip || '—')],
          ['Game port', String(connection.game_port || '—')],
          ['RCON port', String(connection.rcon_port || '—')],
        ]))}
        ${card('Diagnostics', 'Runtime', 'Process and bridge health in one grouped view.', definitionList([
          ['CPU usage', `${formatNumber(diagnostics.cpu_usage, 1)}%`],
          ['Memory usage', `${formatNumber(diagnostics.mem_usage, 1)}%`],
          ['Uptime', formatTime(diagnostics.uptime)],
          ['Watchdog checked', status.watchdog && typeof status.watchdog === 'object' ? String(status.watchdog.checked_at || '—') : '—'],
        ]))}
      </div>

      ${card('Persistent data', 'Grouped', 'Storage and logs stay visible here as supporting information, not as the whole interface.', `
        <div class="file-group-grid">
          ${fileGroup('Factorio files', Array.isArray(status.storage && typeof status.storage === 'object' ? status.storage.saves : []) ? status.storage.saves : [])}
          ${fileGroup('Installed mods', Array.isArray(status.storage && typeof status.storage === 'object' ? status.storage.mods : []) ? status.storage.mods : [])}
        </div>
      `)}
    </div>
  `;
}

function metricGrid(items) {
  return `<div class="metric-grid">${items.map(([label, value, detail]) => `
    <article class="card metric-card">
      <span class="metric-label">${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value))}</strong>
      ${detail ? `<span class="metric-detail">${escapeHtml(String(detail))}</span>` : ''}
    </article>
  `).join('')}</div>`;
}

function card(title, tag, description, body) {
  return `
    <article class="section-card">
      <div class="section-head">
        <div>
          <h2>${escapeHtml(title)}</h2>
          ${description ? `<p class="section-description">${escapeHtml(description)}</p>` : ''}
        </div>
        ${tag ? `<span class="tag">${escapeHtml(tag)}</span>` : ''}
      </div>
      ${body}
    </article>
  `;
}

function definitionList(items) {
  return `<dl class="definition-list">${items.map(([label, value]) => `
    <div>
      <dt>${escapeHtml(label)}</dt>
      <dd>${escapeHtml(String(value))}</dd>
    </div>
  `).join('')}</dl>`;
}

function compactList(items, empty) {
  if (!items.length) {
    return `<p class="empty-state">${escapeHtml(empty)}</p>`;
  }
  return `<div class="compact-list">${items.join('')}</div>`;
}

function compactRow(label, value) {
  return `<div class="compact-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function eventRow(event, short = false) {
  const key = `${String(event.event || 'event')}-${String(event.tick || event.bridge_received_at || '')}`;
  return `<div class="event-row ${short ? 'short' : ''}" data-key="${escapeHtml(key)}"><strong>${escapeHtml(String(event.event))}</strong><span>${escapeHtml(String(event.bridge_received_at || `tick ${event.tick ?? '—'}`))}</span>${short ? '' : `<pre>${escapeHtml(JSON.stringify(event, null, 2))}</pre>`}</div>`;
}

function playerGrid(players) {
  if (!players.length) {
    return '<p class="empty-state">No players reported yet.</p>';
  }
  return `<div class="player-grid">${players.map((player) => `
    <article class="player-card ${player.connected ? 'online' : 'offline'}">
      <strong>${escapeHtml(String(player.name || 'Unknown'))}</strong>
      <span>${escapeHtml(String(player.connected ? 'Connected' : 'Offline'))}</span>
      <small>${escapeHtml(String(player.surface || 'Unknown surface'))}</small>
      <small>${formatNumber(player.deaths)} deaths</small>
    </article>
  `).join('')}</div>`;
}

function resourceGrid(resources) {
  if (!resources.length) {
    return '<p class="empty-state">No resource sites reported yet.</p>';
  }
  return `<div class="resource-grid">${resources.slice().sort((left, right) => Number(right.amount || 0) - Number(left.amount || 0)).map((resource) => `
    <article class="resource-card">
      <div class="section-head tight">
        <div>
          <p class="eyebrow">${escapeHtml(String(resource.surface || 'Unknown surface'))}</p>
          <h3>${escapeHtml(String(resource.name || resource.type_name || resource.type || 'Resource'))}</h3>
        </div>
        <span class="tag">${escapeHtml(String(resource.type_name || resource.type || 'Resource'))}</span>
      </div>
      ${definitionList([
        ['Remaining', formatNumber(resource.amount)],
        ['Rate', `${formatNumber(resource.rate, 2)}/s`],
        ['Remaining %', formatPercent(resource.percent ?? 0)],
        ['Until depleted', resource.estimated_depletion == null ? 'No estimate' : formatTime(Number(resource.estimated_depletion || 0) / 60)],
      ])}
    </article>
  `).join('')}</div>`;
}

function fileGroup(title, items) {
  const sorted = items.slice().sort((left, right) => String(left.name || left.title || '').localeCompare(String(right.name || right.title || '')));
  return `
    <article class="sub-card">
      <div class="section-head tight">
        <h3>${escapeHtml(title)}</h3>
        <span class="tag">${formatNumber(sorted.length)}</span>
      </div>
      ${compactList(sorted.map((item) => compactRow(String(item.name || item.title || 'Unknown'), formatFileSize(item.size))), `No ${title.toLowerCase()} found.`)}
    </article>
  `;
}

function formGrid(fields) {
  return `<div class="form-grid">${fields.join('')}</div>`;
}

function textField(label, scope, key, value, placeholder = '', type = 'text') {
  return `
    <label class="field">
      <span>${escapeHtml(label)}</span>
      <input type="${escapeHtml(type)}" data-scope="${escapeHtml(scope)}" data-field="${escapeHtml(key)}" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}">
    </label>
  `;
}

function textAreaField(label, scope, key, value) {
  return `
    <label class="field field-wide">
      <span>${escapeHtml(label)}</span>
      <textarea data-scope="${escapeHtml(scope)}" data-field="${escapeHtml(key)}">${escapeHtml(value)}</textarea>
    </label>
  `;
}

function selectField(label, scope, key, value, options) {
  return `
    <label class="field">
      <span>${escapeHtml(label)}</span>
      <select data-scope="${escapeHtml(scope)}" data-field="${escapeHtml(key)}">
        ${options.map((option) => `<option value="${escapeHtml(option)}" ${option === value ? 'selected' : ''}>${escapeHtml(option)}</option>`).join('')}
      </select>
    </label>
  `;
}

function sortByName(left, right) {
  return String(left.name || '').localeCompare(String(right.name || ''));
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function bindShell() {
  APP.querySelectorAll('[data-page]').forEach((button) => {
    button.addEventListener('click', () => {
      window.location.hash = button.getAttribute('data-page');
      render();
    });
  });

  APP.querySelectorAll('[data-action="refresh-all"]').forEach((button) => {
    button.addEventListener('click', () => {
      void refreshSnapshot();
    });
  });

  APP.querySelectorAll('[data-scope][data-field]').forEach((input) => {
    input.addEventListener('input', () => {
      const scope = input.getAttribute('data-scope');
      const field = input.getAttribute('data-field');
      if (!scope || !field || !STATE.ui[scope]) return;
      STATE.ui[scope][field] = input.value;
    });
    input.addEventListener('change', () => {
      const scope = input.getAttribute('data-scope');
      const field = input.getAttribute('data-field');
      if (!scope || !field || !STATE.ui[scope]) return;
      STATE.ui[scope][field] = input.value;
    });
  });

  APP.querySelectorAll('[data-action="send-ltn"]').forEach((button) => {
    button.addEventListener('click', () => void runLtn());
  });
  APP.querySelectorAll('[data-action="browse-search"]').forEach((button) => {
    button.addEventListener('click', () => void runBrowseSearch());
  });
  APP.querySelectorAll('[data-catalog-name]').forEach((button) => {
    button.addEventListener('click', () => void openCatalogEntry(button.getAttribute('data-catalog-name') || '', button.getAttribute('data-catalog-kind') || ''));
  });
  APP.querySelectorAll('[data-action="production-plan"]').forEach((button) => {
    button.addEventListener('click', () => void runProductionPlan());
  });
}

async function runLtn() {
  const ui = STATE.ui.logistics;
  ui.ltnStatus = 'Sending...';
  render();
  try {
    const result = await dispatchLtnCommand({
      action: ui.ltnAction,
      name: ui.ltnName,
      train_id: Number(ui.ltnTrainId || 0),
      old_train_id: Number(ui.ltnOldTrainId || 0),
      new_train_id: Number(ui.ltnNewTrainId || 0),
      schedule_index: Number(ui.ltnScheduleIndex || 0),
    });
    ui.ltnStatus = `OK · ${String(normalizeRecord(result).action || 'completed')}`;
    await refreshSnapshot();
  } catch (error) {
    ui.ltnStatus = error instanceof Error ? error.message : 'Command failed';
    render();
  }
}

async function runBrowseSearch() {
  const ui = STATE.ui.browse;
  ui.loading = true;
  render();
  try {
    const response = await getCatalog(new URLSearchParams({ query: ui.query, kind: ui.kind, limit: '32', offset: '0' }));
    ui.results = Array.isArray(response.results) ? response.results : [];
    ui.selected = ui.results[0] || null;
    ui.meta = `${formatNumber(response.total)} results · ${String(response.factorio_version || 'unknown')}`;
  } catch (error) {
    ui.meta = error instanceof Error ? error.message : 'Catalog unavailable';
  } finally {
    ui.loading = false;
    render();
  }
}

async function openCatalogEntry(name, kind) {
  const ui = STATE.ui.browse;
  try {
    const response = await getCatalogEntry(name, kind);
    ui.selected = normalizeRecord(response.result);
  } catch (error) {
    ui.meta = error instanceof Error ? error.message : 'Catalog entry unavailable';
  }
  render();
}

async function runProductionPlan() {
  const ui = STATE.ui.production;
  ui.status = 'Planning...';
  render();
  try {
    const items = JSON.parse(ui.itemsText);
    const knownRecipes = JSON.parse(ui.knownRecipesText);
    const response = await getProductionPlan(items, knownRecipes);
    ui.output = response;
    ui.status = String(response.status || 'Ready');
  } catch (error) {
    ui.status = error instanceof Error ? error.message : 'Planning failed';
  }
  render();
}

window.addEventListener('hashchange', () => {
  render();
});

render();
void refreshSnapshot();

setInterval(() => {
  void refreshSnapshot();
}, 15000);
