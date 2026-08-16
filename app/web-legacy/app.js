const byId = (id) => document.getElementById(id);
const setText = (id, value) => { const element = byId(id); if (element) element.textContent = value; };
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
const formatBytes = (value) => { const bytes = Number(value || 0); if (!bytes) return '—'; const units = ['B', 'KB', 'MB', 'GB']; const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1); return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`; };
const formatGameTime = (value) => { const seconds = Math.max(0, Number(value || 0)); if (!seconds) return '—'; const hours = Math.floor(seconds / 3600); const minutes = Math.floor((seconds % 3600) / 60); return `${hours}h ${minutes}m`; };
const apiUrl = (path) => new URL(`./${path.replace(/^\//, '')}`, document.baseURI).toString();
function renderResourceMonitor(world) {
  const target = byId('resource-monitor-results');
  if (!target) return;
  const resourceMonitor = world?.resource_monitor && typeof world.resource_monitor === 'object' ? world.resource_monitor : {};
  const hasResourceMonitor = Array.isArray(resourceMonitor.surfaces) || Object.keys(resourceMonitor).length > 0;
  const monitoredSurfaces = Array.isArray(resourceMonitor.surfaces) ? resourceMonitor.surfaces : [];
  const surfaces = hasResourceMonitor ? monitoredSurfaces : (Array.isArray(world?.surfaces) ? world.surfaces : []);
  const sites = surfaces.flatMap((surface) => ((Array.isArray(surface.tracked_resources || surface.pinned_resources) ? surface.tracked_resources || surface.pinned_resources : [])).map((site) => ({ ...site, surface: surface.name })));
  if (!sites.length) {
    target.innerHTML = '<p class="muted">No pinned resource sites are currently available.</p>';
    return;
  }
  target.innerHTML = sites.map((site) => {
    const amount = Number(site.amount || 0).toLocaleString();
    const percentValue = Math.max(0, Math.min(100, Number(site.percent || 0) * 100));
    const percent = `${percentValue.toFixed(1)}%`;
    const rate = `${Number(site.rate || 0).toLocaleString()}/s`;
    const depletion = site.estimated_depletion == null ? 'No estimate' : formatGameTime(Number(site.estimated_depletion) / 60);
    const position = site.position || {};
    const friendlyType = site.type_name || 'Resource';
    const siteName = site.name || `${friendlyType} site`;
    return `<article class="status-card resource-monitor-card"><div class="section-heading"><div><span class="status-label">${escapeHtml(site.surface || 'Unknown surface')}</span><h3>${escapeHtml(siteName)}</h3></div><span class="panel-tag">${escapeHtml(friendlyType)}</span></div><div class="resource-monitor-progress" role="progressbar" aria-label="Ore remaining" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percentValue.toFixed(1)}"><div class="resource-monitor-progress-track"><span style="width:${percentValue.toFixed(1)}%"></span></div><strong>${escapeHtml(percent)} remaining</strong></div><dl class="resource-monitor-list"><div><dt>Amount</dt><dd>${escapeHtml(amount)}</dd></div><div><dt>Rate</dt><dd>${escapeHtml(rate)}</dd></div><div><dt>Depletion</dt><dd>${escapeHtml(depletion)}</dd></div><div><dt>Location</dt><dd>${escapeHtml(site.surface || 'Unknown')} (${escapeHtml(position.x ?? 0)}, ${escapeHtml(position.y ?? 0)})</dd></div></dl></article>`;
  }).join('');
}
let catalogOffset = 0;
let catalogTotal = 0;
let catalogResults = [];
let recipeOffset = 0;
let recipeResults = [];
let selectedEntry = null;
let detailTab = 'entity';
let catalogCategory = '';
let catalogSubcategory = '';
let recipeCategory = '';
let exploreKind = 'item';
let exploreOffset = 0;
let exploreResults = [];
let masterCatalogKind = 'item';
let technologyEntries = [];
let saveFileFilter = 'all';
let researchState = { available: false, researched: [], current: '', progress: 0, queue: [] };
let monitoredTechnologies = new Set(JSON.parse(localStorage.getItem('factorio-monitored-technologies') || '[]'));
let lastWorldMetrics = { players: null, gameTime: null };
function renderResearchSummary() {
  const currentEntry = technologyEntries.find((entry) => entry.name === researchState.current);
  const summary = byId('research-summary');
  if (!summary) return;
  summary.innerHTML = `<span><b>${researchState.available ? `${researchState.researched.length} researched` : 'Research unavailable'}</b></span><span>${currentEntry ? `Current: ${escapeHtml(currentEntry.localized_name || currentEntry.name)} · ${Number(researchState.progress || 0).toFixed(1)}%` : 'No active research'}</span><span>Queue: ${researchState.queue.length}</span><span>Monitoring: ${monitoredTechnologies.size}</span>`;
}
const catalogView = () => document.querySelector('.factoriopedia-view.active .pedia-panel-active[data-catalog-kind]');
const catalogElement = (name) => catalogView()?.querySelector(`[data-catalog-element="${name}"]`) || byId({ query: 'explore-query', previous: 'explore-previous', page: 'explore-page', next: 'explore-next', results: 'explore-results', detail: 'explore-detail' }[name]);
const catalogQuery = () => catalogElement('query').value.trim();
const recipeQuery = () => byId('recipe-query').value.trim();
const catalogKind = () => catalogView()?.dataset.catalogKind || 'item';
function switchPediaPanel(panelName) {
  document.querySelectorAll('[data-pedia-panel]').forEach((panel) => panel.classList.toggle('pedia-panel-active', panel.dataset.pediaPanel === panelName));
  document.querySelectorAll('[data-pedia-mode]').forEach((tab) => tab.classList.toggle('active', tab.dataset.pediaMode === panelName));
  if (panelName === 'items' || panelName === 'fluids') { catalogOffset = 0; catalogCategory = ''; catalogSubcategory = ''; refreshCatalogFacets(); refreshCatalog(); }
  if (panelName === 'recipes') { recipeCategory = ''; refreshRecipeFacets(); refreshRecipes(); }
  if (panelName === 'technologies') refreshTechnologies();
  if (panelName === 'explore') { exploreOffset = 0; refreshExplore(); }
}
const humanizeBrowseLabel = (value) => String(value || 'Other').replace(/[_-]+/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase());
const cleanFactorioText = (value) => String(value ?? '')
  .replace(/\[\/?(?:font|color)(?:=[^\]]+)?\]/g, '')
  .replace(/\[([^=\]]+)=([^\]]+)\]/g, '$2');
const formatValue = (value) => Array.isArray(value) ? value.map((entry) => formatValue(entry)).join('\n') : value && typeof value === 'object' ? JSON.stringify(value, null, 2) : cleanFactorioText(value);
const formatLocalizedList = (value) => Array.isArray(value) ? value.map((entry) => {
  if (typeof entry === 'string') return entry;
  if (!entry || typeof entry !== 'object') return String(entry ?? '');
  const name = entry.localized_name || entry.name || entry.type || '';
  const amount = entry.amount ?? entry.amount_min ?? '';
  return amount === '' ? name : `${name} × ${amount}`;
}).join('\n') : formatValue(value);
const formatLocalizedRefs = (value) => Array.isArray(value) ? value.map((entry) => typeof entry === 'object' ? (entry.localized_name || entry.name || '') : entry).join('\n') : formatValue(value);
const formatEffect = (effect) => {
  if (!effect || typeof effect !== 'object') return String(effect ?? '');
  if (effect.type === 'unlock-recipe' && effect.recipe) return effect.localized_name || effect.recipe;
  return [effect.type, effect.modifier, effect.ammo_category, effect.recipe].filter((value) => value !== undefined && value !== null && value !== '').join(': ');
};
const effectMarkup = (effects) => Array.isArray(effects) ? effects.map((effect) => {
  if (effect?.type === 'unlock-recipe' && effect.recipe) {
    return `<button class="catalog-reference" data-ref-kind="recipe" data-ref-name="${escapeHtml(effect.recipe)}">${escapeHtml(formatEffect(effect))}</button>`;
  }
  return escapeHtml(formatEffect(effect));
}).join('<br>') : escapeHtml(formatDetailValue('effects', effects));
const formatDetailValue = (key, value) => key === 'effects' && Array.isArray(value) ? value.map(formatEffect).join('\n') : ['ingredients', 'products', 'results', 'fluid_box'].includes(key) ? formatLocalizedList(value) : ['localized_prerequisites', 'made_in', 'used_in', 'crafted_in', 'unlocked_recipes'].includes(key) ? formatLocalizedRefs(value) : formatValue(value);
const browseReferenceKinds = new Set(['item', 'fluid', 'recipe', 'technology', 'module', 'equipment', 'vehicle', 'resource', 'weapon', 'signal', 'tile', 'achievement', 'setting', 'space', 'quality', 'entity']);
const referenceKind = (value, fallback = '') => {
  if (fallback === 'made_in' || fallback === 'used_in' || fallback === 'unlocked_recipes') return 'recipe';
  if (fallback === 'crafted_in') return 'entity';
  if (fallback === 'prerequisites') return 'technology';
  if (typeof value === 'object' && value) {
    const kind = { item: 'item', fluid: 'fluid', recipe: 'recipe', technology: 'technology', module: 'module', equipment: 'equipment', vehicle: 'vehicle', resource: 'resource', weapon: 'weapon', signal: 'signal', tile: 'tile', achievement: 'achievement', setting: 'setting', space: 'space', quality: 'quality', entity: 'entity' }[value.type] || fallback;
    return browseReferenceKinds.has(kind) ? kind : fallback;
  }
  return browseReferenceKinds.has(fallback) ? fallback : '';
};
const referenceMarkup = (key, value, localizedValues = null) => {
  const values = Array.isArray(value) ? value : [value];
  return values.map((entry, index) => {
    const name = typeof entry === 'object' && entry ? entry.name : entry;
    const kind = referenceKind(entry, key);
    if (!name || !kind || !browseReferenceKinds.has(kind)) return escapeHtml(formatDetailValue(key, entry));
    const localizedLabel = Array.isArray(localizedValues) ? localizedValues[index] : null;
    const label = localizedLabel || (typeof entry === 'object' && entry ? (entry.localized_name || entry.name) : entry);
    const amount = typeof entry === 'object' && entry ? (entry.amount ?? entry.amount_min ?? '') : '';
    return `<button type="button" class="catalog-reference" data-ref-kind="${escapeHtml(kind)}" data-ref-name="${escapeHtml(name)}">${escapeHtml(label)}</button>${amount === '' ? '' : ` <span class="reference-amount">× ${escapeHtml(amount)}</span>`}`;
  }).join('<span class="reference-entry-break"></span>');
};
const isReferenceField = (key) => ['ingredients', 'products', 'results', 'prerequisites', 'localized_prerequisites', 'made_in', 'used_in', 'crafted_in', 'unlocked_recipes'].includes(key);
function bindReferenceLinks(root = document) {
  root.querySelectorAll('[data-ref-kind]').forEach((link) => link.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    openCatalogReference(link.dataset.refKind, link.dataset.refName);
  }));
}
document.addEventListener('click', (event) => {
  const link = event.target.closest?.('[data-ref-kind]');
  if (!link) return;
  event.preventDefault();
  event.stopPropagation();
  openCatalogReference(link.dataset.refKind, link.dataset.refName);
});
async function openCatalogReference(kind, name) {
  try {
    const lookups = [kind, ''];
    let entry = null;
    for (const lookupKind of lookups) {
      const response = await fetch(apiUrl(`api/catalog/entry?${new URLSearchParams({ name, kind: lookupKind, detail: 'full' })}`), { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Catalog entry unavailable.');
      if (data.found && data.result && data.result.name === name) {
        entry = data.result;
        kind = lookupKind || kind;
        break;
      }
    }
    if (!entry) throw new Error(`Catalog entry not found: ${name}`);
    switchAppTab('browse', false);
    switchPediaPanel('explore');
    const target = byId('explore-detail');
    if (!target) return;
    showCatalogDetail(entry, target);
    if (kind === 'technology') renderTechnologyTree();
  } catch (error) {
    console.warn('Catalog reference could not be opened', { kind, name, error });
  }
}
const iconPath = (entry) => {
  const findPath = (value) => {
    if (typeof value === 'string') return value.includes('/') && /\.(png|jpg|jpeg|webp|svg)$/i.test(value) ? value : '';
    if (Array.isArray(value)) {
      for (const item of value) {
        const path = findPath(item);
        if (path) return path;
      }
      return '';
    }
    if (!value || typeof value !== 'object') return '';
    return findPath(value.icon)
      || findPath(value.filename)
      || findPath(value.path)
      || findPath(value.icons)
      || findPath(value.layers)
      || findPath(value.picture)
      || findPath(value.pictures)
      || findPath(value.animation)
      || findPath(value.animations)
      || findPath(value.hr_version)
      || findPath(value.mipmap)
      || findPath(value.mipmaps)
      || findPath(value.spritesheet)
      || findPath(value.variants)
      || '';
  };
  return findPath(entry.icon) || findPath(entry.icons) || findPath(entry.picture) || findPath(entry.pictures) || '';
};
const iconUrl = (entry) => iconPath(entry) ? `api/icon?path=${encodeURIComponent(iconPath(entry))}` : '';
const iconMarkup = (entry, className = 'catalog-icon') => {
  const label = String(entry.localized_name || entry.name || entry.type || '?');
  const fallback = `<span class="fallback-icon">${escapeHtml(label.slice(0, 1).toUpperCase())}</span>`;
  const url = iconUrl(entry);
  const slotClass = `${escapeHtml(className)}-slot`;
  if (!url) return `<span class="icon-slot ${slotClass}">${fallback}</span>`;
  return `<span class="icon-slot ${slotClass}">${fallback}<img class="${escapeHtml(className)}" src="${escapeHtml(url)}" alt="" loading="lazy" onerror="this.remove()"></span>`;
};
async function callModRemote(method, payload) {
  const command = `/silent-command local ok,result=pcall(remote.call,${JSON.stringify('factorio_assistant')},${JSON.stringify(method)},${JSON.stringify(JSON.stringify(payload))});rcon.print(helpers.table_to_json({ok=ok,result=result}))`;
  const response = await fetch(apiUrl('api/rcon'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || data.response || 'RCON request failed.');
  if (typeof data.response !== 'string' || !data.response) throw new Error(data.error || 'RCON response missing.');
  const envelope = JSON.parse(data.response);
  if (!envelope || envelope.ok !== true) throw new Error(envelope?.error || envelope?.result || 'Remote command failed.');
  return envelope.result;
}
function renderLogisticsView(world) {
  const target = byId('logistics-vehicle-counts');
  if (!target) return;
  const counts = world?.vehicle_counts && typeof world.vehicle_counts === 'object' ? world.vehicle_counts : {};
  const kinds = counts.kinds && typeof counts.kinds === 'object' ? counts.kinds : {};
  const rows = [
    ['All vehicles', counts.total ?? 0],
    ['AAI vehicles', counts.matched ?? 0],
    ['Miners', kinds.miner ?? 0],
    ['Haulers', kinds.hauler ?? 0],
    ['Wardens', kinds.warden ?? 0],
    ['Chaingunners', kinds.chaingunner ?? 0],
    ['Flame tanks', kinds.flame_tank ?? 0],
    ['Ironclads', kinds.ironclad ?? 0],
    ['Laser tanks', kinds.laser_tank ?? 0],
  ];
  target.innerHTML = rows.map(([label, value]) => `<div class="storage-row"><span>${escapeHtml(label)}</span><b>${escapeHtml(Number(value || 0).toLocaleString())}</b></div>`).join('');
  if (byId('logistics-vehicle-meta')) byId('logistics-vehicle-meta').textContent = `${Number(counts.matched || 0).toLocaleString()} AAI vehicles`;
  const surfaceSummary = world?.vehicle_counts?.surfaces && typeof world.vehicle_counts.surfaces === 'object'
    ? Object.entries(world.vehicle_counts.surfaces).map(([surface, summary]) => `${surface}: ${Number(summary?.matched || 0).toLocaleString()}`).join(' · ')
    : '';
  if (byId('logistics-vehicle-surfaces')) byId('logistics-vehicle-surfaces').textContent = surfaceSummary || 'No AAI vehicle telemetry reported yet.';
}
async function runLogisticsAaiDispatch() {
  const payload = {
    action: byId('logistics-aai-action')?.value || 'follow_player',
    unit_kind: byId('logistics-aai-unit-kind')?.value || 'any',
    player: byId('logistics-aai-player')?.value || '',
    surface: byId('logistics-aai-surface')?.value || '',
    center_x: Number(byId('logistics-aai-center-x')?.value || 0),
    center_y: Number(byId('logistics-aai-center-y')?.value || 0),
    area_size: Number(byId('logistics-aai-area-size')?.value || 32),
  };
  const status = byId('logistics-aai-status');
  if (status) status.textContent = 'SENDING';
  try {
    const result = await callModRemote('aai_dispatch', payload);
    if (status) status.textContent = `OK · ${result.action || 'dispatched'}`;
  } catch (error) {
    if (status) status.textContent = `ERROR · ${error.message || 'dispatch failed'}`;
  }
}
async function runLogisticsLtnCommand() {
  const payload = {
    action: byId('logistics-ltn-action')?.value || 'clear_all_surface_connections',
    name: byId('logistics-ltn-name')?.value || '',
    train_id: Number(byId('logistics-ltn-train-id')?.value || 0),
    old_train_id: Number(byId('logistics-ltn-old-train-id')?.value || 0),
    new_train_id: Number(byId('logistics-ltn-new-train-id')?.value || 0),
    schedule_index: Number(byId('logistics-ltn-schedule-index')?.value || 0),
  };
  const status = byId('logistics-ltn-status');
  if (status) status.textContent = 'SENDING';
  try {
    const result = await callModRemote('ltn_command', payload);
    if (status) status.textContent = `OK · ${result.action || 'completed'}`;
  } catch (error) {
    if (status) status.textContent = `ERROR · ${error.message || 'command failed'}`;
  }
}
function buildLogisticsMarkup() {
  return '<div class="pedia-header"><div><span class="eyebrow">LOGISTICS CONTROL</span><h2>Dispatch and fleet control</h2><p class="view-lede">Dispatch AAI vehicles and run the limited LTN helpers that can be driven through the bridge.</p></div><button id="logistics-refresh" class="subtle-button">Refresh logistics</button></div><div class="production-layout logistics-layout"><article class="status-card"><div class="section-heading"><h3>AAI fleet telemetry</h3><span id="logistics-vehicle-meta" class="panel-tag">—</span></div><div id="logistics-vehicle-counts" class="file-list"><p class="muted">Loading vehicle counts...</p></div><p id="logistics-vehicle-surfaces" class="status-detail">No AAI vehicle telemetry reported yet.</p></article><article class="status-card production-form"><div class="section-heading"><h3>Dispatch AAI vehicle</h3><span id="logistics-aai-status" class="panel-tag">READY</span></div><label>Action<select id="logistics-aai-action"><option value="follow_player">Follow player</option><option value="go_to_position">Go to position</option><option value="mine_area">Mine area</option></select></label><label>Vehicle kind<select id="logistics-aai-unit-kind"><option value="any">Any</option><option value="miner">Miner</option><option value="hauler">Hauler</option><option value="warden">Warden</option><option value="chaingunner">Chaingunner</option><option value="flame_tank">Flame tank</option><option value="flame_tumbler">Flame tumbler</option><option value="ironclad">Ironclad</option><option value="laser_tank">Laser tank</option></select></label><label>Player<input id="logistics-aai-player" type="text" placeholder="Player name to follow"></label><label>Surface<input id="logistics-aai-surface" type="text" placeholder="nauvis"></label><div class="save-schedule-controls"><label>X<input id="logistics-aai-center-x" type="number" step="1" value="0"></label><label>Y<input id="logistics-aai-center-y" type="number" step="1" value="0"></label><label>Area size<input id="logistics-aai-area-size" type="number" min="1" max="256" value="32"></label></div><div class="production-actions"><button id="logistics-aai-run">Send vehicle</button></div></article><article class="status-card production-form"><div class="section-heading"><h3>Control LTN</h3><span id="logistics-ltn-status" class="panel-tag">READY</span></div><label>Action<select id="logistics-ltn-action"><option value="clear_all_surface_connections">Clear all surface connections</option><option value="exclude_from_fuel_schedule">Exclude from fuel schedule</option><option value="get_or_create_next_temp_stop">Get or create next temp stop</option><option value="get_next_logistic_stop">Get next logistic stop</option><option value="reassign_delivery">Reassign delivery</option></select></label><label>Locomotive or prototype name<input id="logistics-ltn-name" type="text" placeholder="optional name for fuel exclusion"></label><div class="save-schedule-controls"><label>Train id<input id="logistics-ltn-train-id" type="number" step="1" value="0"></label><label>Old train id<input id="logistics-ltn-old-train-id" type="number" step="1" value="0"></label><label>New train id<input id="logistics-ltn-new-train-id" type="number" step="1" value="0"></label><label>Schedule index<input id="logistics-ltn-schedule-index" type="number" step="1" value="0"></label></div><div class="production-actions"><button id="logistics-ltn-run">Run LTN action</button></div><p class="production-note">The bridge can call a limited set of LTN helpers. Train-based actions need train ids from the game.</p></article></div>';
}
function bindLogisticsControls() {
  byId('logistics-refresh')?.addEventListener('click', refreshWorld);
  byId('logistics-aai-run')?.addEventListener('click', () => runLogisticsAaiDispatch());
  byId('logistics-ltn-run')?.addEventListener('click', () => runLogisticsLtnCommand());
}
function syncHomeAssistantTheme() {
  try {
    const styles = getComputedStyle(window.parent.document.documentElement);
    const themeVariables = {
      '--ink': '--primary-text-color',
      '--muted': '--secondary-text-color',
      '--paper': '--primary-background-color',
      '--panel': '--card-background-color',
      '--line': '--divider-color',
      '--green': '--primary-color',
      '--orange': '--accent-color',
      '--hover': '--secondary-background-color',
      '--detail-background': '--secondary-background-color',
      '--detail-text': '--primary-text-color',
      '--detail-heading': '--primary-text-color',
      '--detail-line': '--divider-color',
      '--detail-label': '--secondary-text-color',
      '--shadow': '--ha-card-box-shadow',
    };
    Object.entries(themeVariables).forEach(([localName, homeAssistantName]) => {
      const value = styles.getPropertyValue(homeAssistantName).trim();
      if (value) document.documentElement.style.setProperty(localName, value);
    });
  } catch {
    // Direct access does not have a Home Assistant parent document.
  }
}
async function showProductionPlan(entry, detailTarget = catalogElement('detail')) {
  if (!detailTarget || !entry) return;
  const targetName = entry.kind === 'recipe'
    ? (Array.isArray(entry.results) && entry.results[0]?.name ? entry.results[0].name : entry.name)
    : entry.name;
  detailTarget.querySelector('[data-production-plan]')?.remove();
  const panel = document.createElement('details');
  panel.className = 'technical-details';
  panel.open = true;
  panel.dataset.productionPlan = '1';
  panel.innerHTML = '<summary>Production plan</summary><div class="detail-fields"><div><b>Loading</b><pre>Building plan...</pre></div></div>';
  detailTarget.appendChild(panel);
  try {
    const response = await fetch(apiUrl('api/catalog/production'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: [{ name: targetName, rate: 60 }] }),
      cache: 'no-store',
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Production plan unavailable.');
    panel.innerHTML = `<summary>Production plan</summary><div class="detail-fields"><div><b>Raw inputs</b><pre>${escapeHtml(JSON.stringify(data.raw_inputs || [], null, 2))}</pre></div><div><b>Recipes</b><pre>${escapeHtml(JSON.stringify(data.recipes || [], null, 2))}</pre></div></div>`;
  } catch (error) {
    panel.innerHTML = `<summary>Production plan</summary><div class="detail-fields"><div><b>Error</b><pre>${escapeHtml(error.message || 'Production plan unavailable.')}</pre></div></div>`;
  }
}
function setupDashboardShell() {
  document.querySelector('[data-app-view="players"]')?.remove();
  const logisticsView = document.querySelector('[data-app-view="logs"]');
  if (logisticsView) {
    logisticsView.dataset.appView = 'logistics';
    logisticsView.classList.add('logistics-view');
    logisticsView.innerHTML = buildLogisticsMarkup();
  }
  const tabs = document.querySelector('.app-tabs');
  if (tabs && !tabs.querySelector('[data-app-tab="logistics"]')) {
    const storageTab = tabs.querySelector('[data-app-tab="storage"]');
    const logisticsTab = document.createElement('button');
    logisticsTab.className = 'app-tab';
    logisticsTab.dataset.appTab = 'logistics';
    logisticsTab.textContent = 'Logistics';
    logisticsTab.addEventListener('click', () => switchAppTab('logistics'));
    if (storageTab) tabs.insertBefore(logisticsTab, storageTab); else tabs.appendChild(logisticsTab);
  }
  const productionLayout = document.querySelector('[data-app-view="production"] .production-layout');
  if (productionLayout && !productionLayout.querySelector('.production-guide')) {
    productionLayout.insertAdjacentHTML('afterbegin', '<article class="status-card production-guide"><div class="section-heading"><h3>How to use this planner</h3><span class="panel-tag">GUIDE</span></div><div class="production-note">1. Set the goal in plain language. 2. List the items you want to produce as JSON. 3. Leave known recipes empty unless you need to lock a specific chain.</div><div class="production-note">If you opened this from a catalog entry, the item or recipe is already prefilled.</div></article>');
  }
  const storageView = document.querySelector('[data-app-view="storage"]');
  if (storageView) {
    storageView.classList.add('storage-layout');
    const autosaveCard = document.querySelector('#save-autosave-results')?.closest('.status-card');
    const saveCard = document.querySelector('#save-file-results')?.closest('.status-card');
    if (!document.querySelector('#save-autosave-results') && saveCard) {
      saveCard.insertAdjacentHTML('beforebegin', '<article class="status-card"><div class="section-heading"><h3>Internal autosaves</h3><span class="panel-tag">AUTOSAVE</span></div><div id="save-autosave-results" class="file-list"><p class="muted">Loading autosaves...</p></div></article>');
    }
    if (autosaveCard && saveCard && autosaveCard.compareDocumentPosition(saveCard) & Node.DOCUMENT_POSITION_FOLLOWING) {
      saveCard.before(autosaveCard);
    }
  }
  bindLogisticsControls();
}
function renderResourceOverview(world) {
  const surfaces = Array.isArray(world?.surfaces) ? world.surfaces : [];
  const sites = surfaces.flatMap((surface) => (Array.isArray(surface.pinned_resources) ? surface.pinned_resources : []).map((site) => ({ ...site, surface: surface.name })));
  const totalSites = sites.length;
  const totalAmount = sites.reduce((total, site) => total + Number(site.amount || 0), 0);
  const avgPercent = totalSites ? sites.reduce((total, site) => total + Number(site.percent || 0), 0) / totalSites : 0;
  const richest = [...sites].sort((left, right) => Number(right.amount || 0) - Number(left.amount || 0))[0];
  setText('overview-resource-count', totalSites);
  byId('overview-resource-summary') && (byId('overview-resource-summary').textContent = totalSites ? `${surfaces.length} surfaces · ${(avgPercent * 100).toFixed(1)}% average remaining` : 'No pinned resource sites reported');
  byId('overview-resource-top') && (byId('overview-resource-top').innerHTML = richest
    ? `<div class="storage-row"><span>${escapeHtml(richest.name || 'Resource site')}</span><b>${escapeHtml(richest.surface || 'Unknown')} · ${Number(richest.amount || 0).toLocaleString()}</b></div><div class="storage-row"><span>Total resource amount</span><b>${Number(totalAmount).toLocaleString()}</b></div>`
    : '<p class="muted">No resource sites are pinned.</p>');
}
function renderModsView(mods = []) {
  const list = Array.isArray(mods) ? mods.filter((mod) => mod && typeof mod === 'object') : [];
  const enabled = list.filter((mod) => mod.enabled !== false);
  setText('mods-meta', `${list.length} total`);
  setText('mods-count', `${enabled.length} enabled`);
  byId('mods-summary') && (byId('mods-summary').innerHTML = list.length
    ? `<div class="storage-row"><span>Installed mods</span><b>${list.length}</b></div><div class="storage-row"><span>Enabled mods</span><b>${enabled.length}</b></div><div class="storage-row"><span>Disabled mods</span><b>${Math.max(0, list.length - enabled.length)}</b></div>`
    : '<p class="muted">No mod metadata reported yet.</p>');
  byId('mods-results') && (byId('mods-results').innerHTML = list.length
    ? list.map((mod) => {
      const title = mod.title || mod.name || 'Unknown mod';
      const version = mod.version || mod.latest_version || 'Unknown version';
      const enabledState = mod.enabled === false ? 'Disabled' : 'Enabled';
      const description = mod.description || mod.summary || '';
      const path = mod.path || mod.directory || '';
      return `<article class="status-card mod-card"><div class="section-heading"><div><span class="eyebrow">${escapeHtml(enabledState)}</span><h3>${escapeHtml(title)}</h3></div><span class="panel-tag">${escapeHtml(version)}</span></div><div class="mod-card-body"><span class="status-detail">${escapeHtml(mod.name || title)}</span>${description ? `<p class="mod-description">${escapeHtml(description)}</p>` : ''}${path ? `<span class="mod-path">${escapeHtml(path)}</span>` : ''}</div></article>`;
    }).join('')
    : '<p class="muted">No installed mods were reported.</p>');
}
function productionEntryLabel(entry) {
  return entry?.localized_name || entry?.name || 'Unknown';
}
function productionStat(label, value) {
  return `<div class="production-stat"><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`;
}
function renderProductionEntries(entries, kind) {
  const list = Array.isArray(entries) ? entries.filter((entry) => entry && typeof entry === 'object') : [];
  if (!list.length) return `<p class="muted">No ${kind} reported.</p>`;
  return list.map((entry) => {
    const recipe = entry.recipe && typeof entry.recipe === 'object' ? entry.recipe : null;
    const machine = recipe?.machine && typeof recipe.machine === 'object' ? recipe.machine : null;
    const ingredients = recipe?.ingredients ? `<div><b>Ingredients</b><p>${referenceMarkup('ingredients', recipe.ingredients)}</p></div>` : '';
    const results = recipe?.results ? `<div><b>Results</b><p>${referenceMarkup('results', recipe.results)}</p></div>` : '';
    const chosenRecipe = recipe?.localized_name || recipe?.name || '';
    return `<article class="production-node"><div class="production-node-heading"><div><strong>${escapeHtml(productionEntryLabel(entry))}</strong><span>${escapeHtml(kind === 'raw input' ? 'Raw input' : kind === 'recipe' ? 'Recipe' : 'Requested item')}</span></div><b>${escapeHtml(Number(entry.rate ?? entry.target_rate ?? 0).toFixed(2))}/min</b></div><div class="production-node-grid">${productionStat('Status', entry.status || 'planned')}${productionStat('Type', entry.kind || kind)}${recipe ? productionStat('Chosen recipe', chosenRecipe || '—') : ''}${machine ? productionStat('Machine', `${machine.entity || '—'} · ${Number(machine.crafting_speed || 0).toFixed(2)} speed`) : ''}${recipe ? productionStat('Category', recipe.category || '—') : ''}${recipe ? productionStat('Machine count', Number(recipe.machine_count || 0).toFixed(2)) : ''}</div>${ingredients || results ? `<div class="production-node-details">${ingredients}${results}</div>` : ''}</article>`;
  }).join('');
}
function renderProductionOutput(plan, goalText = '') {
  const target = byId('production-output');
  if (!target) return;
  const items = Array.isArray(plan?.items) ? plan.items : [];
  const rawInputs = Array.isArray(plan?.raw_inputs) ? plan.raw_inputs : [];
  const recipes = Array.isArray(plan?.recipes) ? plan.recipes : [];
  const goalLabel = goalText || 'Production plan';
  target.innerHTML = `<div class="production-summary"><article class="status-card"><div class="section-heading"><h3>${escapeHtml(goalLabel)}</h3><span class="panel-tag">${escapeHtml(plan?.status || 'READY')}</span></div><div class="storage-row"><span>Requested items</span><b>${items.length}</b></div><div class="storage-row"><span>Raw inputs</span><b>${rawInputs.length}</b></div><div class="storage-row"><span>Recipes</span><b>${recipes.length}</b></div></article><article class="status-card"><div class="section-heading"><h3>Plan details</h3><span class="panel-tag">${escapeHtml(plan?.detail || 'CLEAN')}</span></div><div class="production-note">Use the recipe list below to compare machine counts and chain depth.</div></article></div><div class="production-panels"><article class="status-card"><div class="section-heading"><h3>Requested items</h3><span class="panel-tag">${items.length}</span></div><div class="production-list">${renderProductionEntries(items, 'requested item')}</div></article><article class="status-card"><div class="section-heading"><h3>Raw inputs</h3><span class="panel-tag">${rawInputs.length}</span></div><div class="production-list">${renderProductionEntries(rawInputs, 'raw input')}</div></article><article class="status-card"><div class="section-heading"><h3>Recipe chain</h3><span class="panel-tag">${recipes.length}</span></div><div class="production-list">${renderProductionEntries(recipes, 'recipe')}</div></article></div>`;
  bindReferenceLinks(target);
}
async function runProductionPlan() {
  const itemsText = byId('production-items')?.value || '[]';
  const recipesText = byId('production-known-recipes')?.value || '[]';
  const goalText = byId('production-goal')?.value || '';
  let items;
  let knownRecipes;
  try {
    items = JSON.parse(itemsText);
  } catch {
    window.alert('Enter valid JSON for the production items.');
    return;
  }
  try {
    knownRecipes = JSON.parse(recipesText);
  } catch {
    window.alert('Enter valid JSON for the known recipes list.');
    return;
  }
  if (!Array.isArray(items) || !items.length) {
    window.alert('Add at least one requested production item.');
    return;
  }
  const status = byId('production-status');
  if (status) status.textContent = 'PLANNING';
  try {
    const response = await fetch(apiUrl('api/catalog/production'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items, known_recipes: knownRecipes }),
      cache: 'no-store',
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Production plan unavailable.');
    if (status) status.textContent = 'READY';
    setText('production-meta', `${items.length} item${items.length === 1 ? '' : 's'} · ${Array.isArray(data.recipes) ? data.recipes.length : 0} recipes`);
    renderProductionOutput(data, goalText);
  } catch (error) {
    if (status) status.textContent = 'ERROR';
    const target = byId('production-output');
    if (target) target.innerHTML = `<p class="muted">${escapeHtml(error.message || 'Production plan unavailable.')}</p>`;
  }
}
function openProductionPlanner(entry) {
  const targetName = entry.kind === 'recipe'
    ? (Array.isArray(entry.results) && entry.results[0]?.name ? entry.results[0].name : entry.name)
    : entry.name;
  if (byId('production-items')) byId('production-items').value = JSON.stringify([{ name: targetName, rate: 60 }], null, 2);
  if (byId('production-goal')) byId('production-goal').value = `Plan ${entry.localized_name || entry.name}`;
  switchAppTab('production', false);
  runProductionPlan().catch((error) => console.warn('Production planner failed', error));
}
function showCatalogDetail(entry, detailTarget = catalogElement('detail')) {
  selectedEntry = entry;
  if (!detailTarget) return;
  if (!entry) { detailTarget.innerHTML = '<p class="muted">Select an entry to inspect its data.</p>'; return; }
  if (detailTab === 'raw') {
    detailTarget.innerHTML = `<pre class="raw-data">${escapeHtml(JSON.stringify(entry, null, 2))}</pre>`;
    return;
  }
  const hidden = new Set(['name', 'kind', 'type', 'localized_name', 'icon', 'icons', 'prerequisites']);
  const fields = Object.entries(entry).filter(([key, value]) => !hidden.has(key) && value !== null && value !== undefined && value !== '');
  const headlineFields = ['type', 'prototype_type', 'stack_size', 'max_health', 'energy', 'category', 'crafting_categories', 'ingredients', 'products', 'results', 'effects', 'localized_prerequisites', 'unit', 'made_in', 'used_in', 'unlocked_recipes'];
  const headline = headlineFields.filter((key) => entry[key] !== undefined && entry[key] !== null && entry[key] !== '').map((key) => `<div class="detail-stat"><b>${escapeHtml(key.replaceAll('_', ' '))}</b><span>${key === 'effects' ? effectMarkup(entry[key]) : isReferenceField(key) ? referenceMarkup(key === 'localized_prerequisites' ? 'prerequisites' : key, key === 'localized_prerequisites' ? entry.prerequisites : entry[key], key === 'localized_prerequisites' ? entry[key] : null) : escapeHtml(formatDetailValue(key, entry[key]))}</span></div>`).join('');
  const detailFields = fields.filter(([key]) => !headlineFields.includes(key));
  const monitorButton = entry.kind === 'technology' ? `<button class="monitor-button" title="${monitoredTechnologies.has(entry.name) ? 'Remove the local highlight for this technology' : 'Highlight this technology in this browser only'}" data-monitor-name="${escapeHtml(entry.name)}">${monitoredTechnologies.has(entry.name) ? 'Monitoring locally' : 'Monitor locally'}</button>` : '';
  const productionButton = entry.kind === 'item' || entry.kind === 'recipe' ? `<button class="monitor-button" data-production-name="${escapeHtml(entry.name)}" data-production-kind="${escapeHtml(entry.kind)}">✓ Add to production planner</button>` : '';
  detailTarget.innerHTML = `<div class="detail-hero">${iconMarkup(entry, 'detail-icon')}<div><p class="eyebrow">${escapeHtml(entry.kind)} · ${escapeHtml(entry.type)}</p><h4>${escapeHtml(entry.localized_name || entry.name)}</h4><span class="detail-id">ID: ${escapeHtml(entry.name)}</span>${monitorButton}${productionButton}</div></div>${headline ? `<div class="detail-stats">${headline}</div>` : ''}${detailFields.length ? `<details class="technical-details"><summary>Technical details</summary><div class="detail-fields">${detailFields.map(([key, value]) => `<div><b>${escapeHtml(key.replaceAll('_', ' '))}</b>${isReferenceField(key) ? `<p>${referenceMarkup(key, value)}</p>` : `<pre>${escapeHtml(formatDetailValue(key, value))}</pre>`}</div>`).join('')}</div></details>` : ''}`;
  bindReferenceLinks(detailTarget);
  detailTarget.querySelector('[data-monitor-name]')?.addEventListener('click', () => toggleMonitoredTechnology(entry.name));
  detailTarget.querySelector('[data-production-name]')?.addEventListener('click', () => openProductionPlanner(entry));
}
function toggleMonitoredTechnology(name) {
  monitoredTechnologies.has(name) ? monitoredTechnologies.delete(name) : monitoredTechnologies.add(name);
  localStorage.setItem('factorio-monitored-technologies', JSON.stringify([...monitoredTechnologies]));
  renderTechnologyTree();
  if (selectedEntry?.name === name) showCatalogDetail(selectedEntry, byId('technology-detail'));
}
function renderTechnologyTree() {
  const byName = new Map(technologyEntries.map((entry) => [entry.name, entry]));
  const prerequisiteNames = (entry) => {
    const value = entry.prerequisites;
    if (Array.isArray(value)) return value.map((item) => typeof item === 'object' && item ? item.name : item).filter(Boolean);
    if (typeof value === 'string') return value ? [value] : [];
    if (value && typeof value === 'object' && value.name) return [value.name];
    return [];
  };
  const depths = new Map();
  const depthOf = (entry, path = new Set()) => {
    if (depths.has(entry.name)) return depths.get(entry.name);
    if (path.has(entry.name)) return 0;
    const prerequisites = prerequisiteNames(entry).filter((name) => byName.has(name));
    const depth = prerequisites.length ? Math.max(...prerequisites.map((name) => depthOf(byName.get(name), new Set([...path, entry.name])))) + 1 : 0;
    depths.set(entry.name, depth);
    return depth;
  };
  technologyEntries.forEach((entry) => depthOf(entry));
  const researched = new Set(researchState.researched || []);
  const queued = new Set(researchState.queue || []);
  const lanes = [...new Set(technologyEntries.map((entry) => depths.get(entry.name)))].sort((a, b) => a - b);
  byId('technology-results').innerHTML = lanes.map((depth) => `<section class="technology-lane"><span class="technology-lane-label">TIER ${depth + 1}</span><div class="technology-lane-items">${technologyEntries.filter((entry) => depths.get(entry.name) === depth).map((entry) => { const prereqs = prerequisiteNames(entry).filter((name) => byName.has(name)); const available = prereqs.every((name) => researched.has(name)); const state = researched.has(entry.name) ? 'researched' : researchState.current === entry.name ? 'current' : queued.has(entry.name) ? 'queued' : available ? 'available' : 'locked'; return `<button class="technology-node technology-${state} ${monitoredTechnologies.has(entry.name) ? 'technology-monitored' : ''}" data-technology-name="${escapeHtml(entry.name)}">${iconMarkup(entry, 'technology-icon')}<span><b>${escapeHtml(entry.localized_name || entry.name)}</b><small>${state}${monitoredTechnologies.has(entry.name) ? ' · monitored' : ''}</small></span></button>`; }).join('')}</div></section>`).join('');
  byId('technology-results').querySelectorAll('[data-technology-name]').forEach((card) => card.addEventListener('click', () => showCatalogDetail(byName.get(card.dataset.technologyName), byId('technology-detail'))));
}
const exploreLabel = (kind) => ({ all: 'All gameplay data', item: 'Items', fluid: 'Fluids', recipe: 'Recipes', technology: 'Technologies', entity: 'Buildings & machines', resource: 'Resources', module: 'Modules', equipment: 'Equipment', weapon: 'Weapons', vehicle: 'Vehicles', space: 'Space Age', signal: 'Circuit signals', tile: 'Tiles', achievement: 'Achievements', tutorial: 'Tips & tutorials', setting: 'Mod settings' }[kind] || kind);
const exploreKinds = ['item', 'fluid', 'recipe', 'technology', 'entity', 'resource', 'module', 'equipment', 'vehicle', 'weapon', 'all'];
const masterCatalogLabels = { item: 'Find an item', production: 'Production chains', recipe: 'Make something', technology: 'Research', entity: 'Build & machines', all: 'Browse everything' };
const masterCatalogExploreKinds = { production: 'recipe' };
const masterCatalogMetaLabels = { production: 'Production chains' };
function renderMasterCatalogGroups() {
  const groups = byId('catalog-master-groups');
  if (!groups) return;
  groups.innerHTML = Object.entries(masterCatalogLabels).map(([kind, label]) => `<button class="catalog-master-tab ${kind === masterCatalogKind ? 'active' : ''}" data-master-kind="${kind}">${label}</button>`).join('');
  groups.querySelectorAll('[data-master-kind]').forEach((tab) => tab.addEventListener('click', () => selectMasterCatalogGroup(tab.dataset.masterKind)));
}
function selectMasterCatalogGroup(kind) {
  masterCatalogKind = kind;
  exploreKind = masterCatalogExploreKinds[kind] || kind;
  exploreOffset = 0;
  renderMasterCatalogGroups();
  renderExploreTabs();
  refreshExplore();
}
function masterCatalogLabel(kind) {
  return masterCatalogMetaLabels[kind] || exploreLabel(masterCatalogExploreKinds[kind] || kind);
}
function renderExploreTabs() {
  const tabs = byId('explore-kind-tabs');
  if (!tabs) return;
  tabs.innerHTML = `<label class="browse-kind-select"><span>View</span><select id="browse-kind-select">${exploreKinds.map((kind) => `<option value="${kind}" ${exploreKind === kind ? 'selected' : ''}>${escapeHtml(exploreLabel(kind))}</option>`).join('')}</select></label>`;
  byId('browse-kind-select')?.addEventListener('change', (event) => { exploreKind = event.target.value; exploreOffset = 0; renderExploreTabs(); refreshExplore(); });
}
async function refreshExplore() {
  const query = byId('explore-query')?.value.trim() || '';
  const params = new URLSearchParams({ query, kind: exploreKind, limit: '48', offset: String(exploreOffset) });
  try {
    const response = await fetch(apiUrl(`api/catalog?${params}`), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    exploreResults = data.results || [];
    byId('explore-meta').textContent = `${data.total} results · ${masterCatalogLabel(masterCatalogKind)} · Factorio ${data.factorio_version}`;
    byId('explore-results').innerHTML = exploreResults.length ? exploreResults.map((entry, index) => `<button class="catalog-card" data-explore-index="${index}">${iconMarkup(entry)}<span><b>${escapeHtml(entry.localized_name || entry.name)}</b><small>${escapeHtml(entry.kind === 'item' && entry.type === 'fluid' ? 'Fluid' : entry.prototype_type || entry.type || entry.kind)}</small></span></button>`).join('') : '<p class="muted">No matching entries. Try an internal name such as iron-plate or assembling-machine-2.</p>';
    byId('explore-page').textContent = `Page ${Math.floor(exploreOffset / 48) + 1}`;
    byId('explore-previous').disabled = exploreOffset === 0;
    byId('explore-next').disabled = exploreOffset + exploreResults.length >= data.total;
    document.querySelectorAll('[data-explore-index]').forEach((card) => card.addEventListener('click', () => showExploreDetail(exploreResults[Number(card.dataset.exploreIndex)])));
    if (exploreResults.length) showExploreDetail(exploreResults[0]);
  } catch (error) {
    byId('explore-meta').textContent = 'UNAVAILABLE';
    byId('explore-results').innerHTML = `<p class="muted">${escapeHtml(error.message || 'Expanded catalog unavailable.')}</p>`;
  }
}
async function refreshCatalogMetadata() {
  try {
    const response = await fetch(apiUrl('api/catalog?limit=1&offset=0'), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Catalog metadata unavailable.');
    const source = data.data_source_url || `https://github.com/wube/factorio-data/tree/${data.factorio_data_ref}`;
    byId('catalog-source-link')?.setAttribute('href', source);
    byId('server-data-link')?.setAttribute('href', source);
    if (byId('server-data')) {
      const modules = Array.isArray(data.modules) ? data.modules.map((module) => module.title || module.name).join(' · ') : 'Module metadata unavailable';
      byId('server-data').innerHTML = `<div class="storage-row"><span>Factorio version</span><b>${escapeHtml(data.factorio_version || '—')}</b></div><div class="storage-row"><span>Data reference</span><b>${escapeHtml(data.factorio_data_ref || '—')}</b></div><div class="storage-row"><span>Modules</span><b>${escapeHtml(modules || '—')}</b></div><div class="storage-row"><span>Release notes</span><b>${data.changelog_url ? `<a class="catalog-reference" href="${escapeHtml(data.changelog_url)}" target="_blank" rel="noreferrer">Open changelog ↗</a>` : 'Unavailable'}</b></div>`;
    }
  } catch (error) {
    if (byId('server-data')) byId('server-data').innerHTML = `<p class="muted">${escapeHtml(error.message || 'Catalog metadata unavailable.')}</p>`;
  }
}
function detailSection(title, content) {
  return content ? `<section class="wiki-detail-section"><h5>${title}</h5><div>${content}</div></section>` : '';
}
function detailLinks(key, value, localizedValues = null) {
  return Array.isArray(value) && value.length ? referenceMarkup(key, value, localizedValues) : '';
}
function showExploreDetail(entry) {
  const detail = byId('explore-detail');
  if (!entry) { detail.innerHTML = '<p class="muted">Select an entry to inspect its data.</p>'; return; }
  const label = entry.localized_name || entry.name;
  const identity = `<div class="detail-hero">${iconMarkup(entry, 'detail-icon')}<div><p class="eyebrow">${escapeHtml(exploreLabel(entry.kind))}</p><h4>${escapeHtml(label)}</h4><span class="detail-id">${escapeHtml(entry.name)}</span></div></div>`;
  const stats = [['Type', entry.type], ['Stack size', entry.stack_size], ['Health', entry.max_health ? `${entry.max_health} HP` : ''], ['Crafting time', entry.energy ? `${entry.energy}s` : ''], ['Category', entry.category]].filter(([, value]) => value !== undefined && value !== null && value !== '');
  let practical = '';
  if (entry.kind === 'item' || entry.kind === 'fluid') practical += detailSection('Production', detailLinks('made_in', entry.made_in) || '<span class="muted">No recipe data linked.</span>') + detailSection('Used in', detailLinks('used_in', entry.used_in) || '<span class="muted">Not used by indexed recipes.</span>');
  if (entry.kind === 'recipe') practical += detailSection('Ingredients', detailLinks('ingredients', entry.ingredients)) + detailSection('Produces', detailLinks('results', entry.results || entry.products)) + detailSection('Crafted in', detailLinks('crafted_in', entry.crafted_in) || '<span class="muted">No machine data linked.</span>');
  if (entry.kind === 'technology') practical += detailSection('Requires', detailLinks('prerequisites', entry.prerequisites, entry.localized_prerequisites)) + detailSection('Unlocks', effectMarkup(entry.effects));
  const description = entry.localized_description ? `<p class="wiki-description">${escapeHtml(entry.localized_description)}</p>` : '';
  const fields = Object.entries(entry).filter(([key, value]) => !['name', 'kind', 'type', 'localized_name', 'localized_description', 'icon', 'icons', 'made_in', 'used_in', 'ingredients', 'results', 'products', 'prerequisites', 'localized_prerequisites', 'effects'].includes(key) && value !== null && value !== undefined && value !== '');
  detail.innerHTML = `${identity}${description}${stats.length ? `<div class="wiki-stat-row">${stats.map(([key, value]) => `<span><b>${escapeHtml(key)}</b>${escapeHtml(value)}</span>`).join('')}</div>` : ''}${practical}<details class="technical-details"><summary>Technical data</summary><div class="detail-fields">${fields.map(([key, value]) => `<div><b>${escapeHtml(key.replaceAll('_', ' '))}</b><pre>${escapeHtml(formatDetailValue(key, value))}</pre></div>`).join('')}</div></details>`;
  bindReferenceLinks(detail);
}
async function refreshCatalog() {
  const params = new URLSearchParams({ query: catalogQuery(), kind: catalogKind(), category: catalogCategory, subcategory: catalogSubcategory, limit: '24', offset: String(catalogOffset) });
  try {
    const response = await fetch(apiUrl(`api/catalog?${params}`), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    catalogResults = data.results || [];
    catalogTotal = data.total || 0;
    const metaId = catalogKind() === 'fluid' ? 'fluids-meta' : 'items-meta';
    if (metaId !== 'items-meta') byId(metaId).textContent = `${catalogTotal} ${catalogKind().toUpperCase()} · ${data.factorio_version}`;
    catalogElement('results').innerHTML = catalogResults.length ? catalogResults.map((entry, index) => `<button class="catalog-card" data-index="${index}">${iconMarkup(entry)}<span><b>${escapeHtml(entry.localized_name || entry.name)}</b><small>${escapeHtml(entry.type || entry.kind)}</small></span></button>`).join('') : `<p class="muted">No matching ${catalogKind()} entries.</p>`;
    catalogElement('page').textContent = `Page ${Math.floor(catalogOffset / 24) + 1}`;
    catalogElement('previous').disabled = catalogOffset === 0;
    catalogElement('next').disabled = catalogOffset + catalogResults.length >= catalogTotal;
    catalogView().querySelectorAll('.catalog-card').forEach((row) => row.addEventListener('click', () => showCatalogDetail(catalogResults[Number(row.dataset.index)])));
    if (catalogResults.length) showCatalogDetail(catalogResults[0]);
  } catch (error) {
    const metaId = catalogKind() === 'fluid' ? 'fluids-meta' : 'items-meta';
    if (metaId !== 'items-meta') byId(metaId).textContent = 'UNAVAILABLE';
    catalogElement('results').innerHTML = `<p class="muted">${escapeHtml(error.message || `${catalogKind()} data unavailable.`)}</p>`;
  }
}
async function refreshCatalogFacets() {
  const view = catalogView();
  const browser = view?.querySelector('[data-catalog-element="browser"]');
  if (!browser) return;
  try {
    const response = await fetch(apiUrl(`api/catalog?facets=1&kind=${encodeURIComponent(catalogKind())}`), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    const allLabel = catalogKind() === 'fluid' ? 'All fluids' : 'All items';
    browser.querySelector('.browser-links').innerHTML = `<button class="browser-link ${!catalogCategory ? 'active' : ''}" data-browse-category="" data-browse-subcategory="">${allLabel}</button>${(data.facets || []).map((facet) => `<div class="browser-group"><button class="browser-link ${catalogCategory === facet.id && !catalogSubcategory ? 'active' : ''}" data-browse-category="${escapeHtml(facet.id)}" data-browse-subcategory="">${escapeHtml(humanizeBrowseLabel(facet.label))}<span>${facet.count}</span></button>${(facet.subcategories || []).map((child) => `<button class="browser-sublink ${catalogSubcategory === child.id ? 'active' : ''}" data-browse-category="${escapeHtml(facet.id)}" data-browse-subcategory="${escapeHtml(child.id)}">${escapeHtml(humanizeBrowseLabel(child.label))}<span>${child.count}</span></button>`).join('')}</div>`).join('')}`;
    browser.querySelectorAll('[data-browse-category]').forEach((button) => button.addEventListener('click', () => {
      catalogCategory = button.dataset.browseCategory || '';
      catalogSubcategory = button.dataset.browseSubcategory || '';
      catalogOffset = 0;
      refreshCatalogFacets();
      refreshCatalog();
    }));
  } catch {
    browser.querySelector('.browser-links').innerHTML = '<p class="muted">Categories unavailable.</p>';
  }
}
async function refreshRecipes() {
  const params = new URLSearchParams({ query: recipeQuery(), kind: 'recipe', category: recipeCategory, limit: '40', offset: String(recipeOffset) });
  try {
    const response = await fetch(apiUrl(`api/catalog?${params}`), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    recipeResults = data.results || [];
    byId('recipes-meta').textContent = `${data.total} RECIPES · ${data.factorio_version}`;
    byId('recipe-results').innerHTML = recipeResults.length ? recipeResults.map((entry, index) => `<button class="catalog-card recipe-card" data-recipe-index="${index}">${iconMarkup(entry)}<span><b>${escapeHtml(entry.localized_name || entry.name)}</b><small>${escapeHtml(entry.category || 'crafting')}</small></span></button>`).join('') : '<p class="muted">No matching recipes.</p>';
    document.querySelectorAll('[data-recipe-index]').forEach((card) => card.addEventListener('click', () => showCatalogDetail(recipeResults[Number(card.dataset.recipeIndex)], byId('recipe-detail'))));
    if (recipeResults.length) showCatalogDetail(recipeResults[0], byId('recipe-detail'));
  } catch (error) {
    byId('recipes-meta').textContent = 'UNAVAILABLE';
    byId('recipe-results').innerHTML = `<p class="muted">${escapeHtml(error.message || 'Recipe data unavailable.')}</p>`;
  }
}
async function refreshRecipeFacets() {
  const browser = byId('recipe-browser');
  if (!browser) return;
  try {
    const response = await fetch(apiUrl('api/catalog?facets=1&kind=recipe'), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    browser.querySelector('.browser-links').innerHTML = `<button class="browser-link ${!recipeCategory ? 'active' : ''}" data-recipe-category="">All recipes</button>${(data.facets || []).map((facet) => `<button class="browser-link ${recipeCategory === facet.id ? 'active' : ''}" data-recipe-category="${escapeHtml(facet.id)}">${escapeHtml(humanizeBrowseLabel(facet.label))}<span>${facet.count}</span></button>`).join('')}`;
    browser.querySelectorAll('[data-recipe-category]').forEach((button) => button.addEventListener('click', () => { recipeCategory = button.dataset.recipeCategory || ''; recipeOffset = 0; refreshRecipeFacets(); refreshRecipes(); }));
  } catch {
    browser.querySelector('.browser-links').innerHTML = '<p class="muted">Categories unavailable.</p>';
  }
}
async function refreshTechnologies() {
  try {
    const response = await fetch(apiUrl('api/catalog?kind=technology&limit=1000&offset=0'), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    technologyEntries = data.results || [];
    byId('technology-meta').textContent = `${data.total} TECHNOLOGIES · ${data.factorio_version}`;
    const researchResponse = await fetch(apiUrl('api/research'), { cache: 'no-store' });
    if (researchResponse.ok) researchState = await researchResponse.json();
    renderResearchSummary();
    renderTechnologyTree();
    if (technologyEntries.length && !selectedEntry) showCatalogDetail(technologyEntries[0], byId('technology-detail'));
  } catch (error) {
    byId('technology-meta').textContent = 'UNAVAILABLE';
    byId('technology-results').innerHTML = `<p class="muted">${escapeHtml(error.message || 'Technology data unavailable.')}</p>`;
  }
}
async function refreshStatus() {
  try {
    const response = await fetch(apiUrl('api/status'), { cache: 'no-store' });
    const responseText = await response.text();
    let data;
    try {
      data = JSON.parse(responseText);
    } catch {
      throw new Error(`API returned ${response.status} ${response.statusText || 'non-JSON response'}`);
    }
    if (!response.ok) throw new Error(data.error || `API returned ${response.status}`);
    const players = Array.isArray(data.players) ? data.players : [];
    const storage = data.storage && typeof data.storage === 'object' ? data.storage : {};
    const saveDetails = storage.save_details && typeof storage.save_details === 'object' ? storage.save_details : {};
    const processes = data.processes && typeof data.processes === 'object' ? data.processes : {};
    const bridge = data.bridge && typeof data.bridge === 'object' ? data.bridge : {};
    const factorio = data.factorio && typeof data.factorio === 'object' ? data.factorio : {};
    setText('server-name', factorio.name || 'Factory reference');
    byId('header-status')?.replaceChildren(document.createTextNode(factorio.running ? 'ONLINE' : 'OFFLINE'));
    byId('header-status-dot')?.classList.toggle('online', Boolean(factorio.running));
    byId('header-status-dot')?.classList.toggle('offline', !factorio.running);
    byId('overview-factorio-state') && (byId('overview-factorio-state').textContent = factorio.running ? 'Online' : 'Offline');
    byId('overview-players') && (byId('overview-players').textContent = players.filter((player) => player.connected).length);
    byId('overview-players-detail') && (byId('overview-players-detail').textContent = `${players.length} known profiles`);
    byId('overview-saves') && (byId('overview-saves').textContent = storage.save_count || 0);
    byId('overview-save-detail') && (byId('overview-save-detail').textContent = `Configured: ${saveDetails.configured || '—'}`);
    byId('overview-mods') && (byId('overview-mods').textContent = storage.mod_count || 0);
    byId('overview-mod-detail') && (byId('overview-mod-detail').textContent = `${storage.mod_count || 0} archives in storage`);
    byId('overview-mod-summary') && (byId('overview-mod-summary').textContent = Array.isArray(storage.mods) && storage.mods.length ? `${storage.mods.length} mod records reported` : 'No mod records available');
    setText('status-factorio', factorio.running ? 'Online' : 'Offline');
    setText('status-factorio-detail', `v${factorio.version || '—'} · UDP ${factorio.game_port || '—'}`);
    const connection = data.connection || {};
    const hostname = connection.hostname || window.location.hostname || '—';
    const hostIp = connection.ip || bridge.host || '—';
    const configuredSave = saveDetails.configured || '';
    if (!Array.isArray(saveDetails.files) && Array.isArray(storage.saves)) saveDetails.files = storage.saves;
    const backupToggle = byId('save-backups-enabled');
    if (backupToggle) backupToggle.checked = Boolean(saveDetails.backup_enabled);
    byId('save-backup-mode') && (byId('save-backup-mode').value = saveDetails.backup_mode || 'interval');
    byId('save-backup-interval') && (byId('save-backup-interval').value = saveDetails.backup_interval_hours || 12);
    byId('save-backup-daily-time') && (byId('save-backup-daily-time').value = saveDetails.backup_daily_time || '00:00');
    byId('save-backup-max-saves') && (byId('save-backup-max-saves').value = saveDetails.backup_max_saves || 14);
    byId('save-backup-max-size') && (byId('save-backup-max-size').value = saveDetails.backup_max_total_size_mb ?? 0);
    updateBackupScheduleVisibility();
    byId('save-configured-name') && (byId('save-configured-name').textContent = configuredSave || '—');
    byId('save-count-tag') && (byId('save-count-tag').textContent = `${(saveDetails.files || []).length} FILES`);
    byId('save-directory-label') && (byId('save-directory-label').textContent = saveDetails.directory || '—');
    const sizeLimit = Number(saveDetails.backup_max_total_size_mb || 0);
    const retentionSummary = `${saveDetails.backup_max_saves || 14} saves${sizeLimit ? ` · ${sizeLimit} MB` : ''}`;
    byId('save-backup-status') && (byId('save-backup-status').textContent = saveDetails.last_backup ? `Latest: ${saveDetails.last_backup} · Retention: ${retentionSummary}` : `Retention: ${retentionSummary}`);
    const restore = data.restore || {};
    byId('save-restore-status') && (byId('save-restore-status').textContent = restore.message || `Restore ${restore.state || 'ready'}`);
    renderSaveFiles(saveDetails);
    const saveFile = (saveDetails.files || []).find((file) => file.name === configuredSave);
    setText('overview-server-badge', factorio.running ? 'ONLINE' : 'OFFLINE');
    byId('overview-server-badge')?.classList.toggle('overview-badge-offline', !factorio.running);
    byId('overview-server-dot')?.classList.toggle('online', Boolean(factorio.running));
    byId('overview-server-dot')?.classList.toggle('offline', !factorio.running);
    setText('overview-hostname', hostname);
    setText('overview-ip', hostIp);
    setText('overview-game-port', connection.game_port || factorio.game_port || '—');
    byId('overview-save-name').textContent = configuredSave || '—';
    byId('overview-save-size').textContent = formatBytes(saveFile?.size);
    setText('overview-save-directory', saveDetails.directory || '—');
    setText('overview-deaths', players.reduce((total, player) => total + Number(player.deaths || 0), 0).toLocaleString());
    const monitors = data.watchdog?.monitors?.length
      ? data.watchdog.monitors.map((monitor) => [monitor.name, monitor.healthy])
      : [['Web service', processes.web], ['Bridge worker', processes.bridge], ['Factorio process', processes.factorio]];
    const healthyMonitors = monitors.filter(([, healthy]) => healthy).length;
    setText('overview-bridge-badge', `${healthyMonitors}/${monitors.length} HEALTHY`);
    byId('overview-bridge-badge')?.classList.toggle('overview-badge-offline', healthyMonitors !== monitors.length);
    const monitorElement = byId('overview-monitors');
    if (monitorElement) monitorElement.innerHTML = monitors.map(([label, healthy]) => `<div class="overview-monitor"><span class="overview-monitor-light ${healthy ? 'online' : 'offline'}"></span><span>${label}</span><b>${healthy ? 'OK' : 'PROBLEM'}</b></div>`).join('');
    setText('status-bridge', bridge.running ? 'Connected' : 'Stopped');
    setText('status-bridge-detail', bridge.rcon_password_present ? 'RCON credentials ready' : 'Waiting for RCON');
    setText('status-player-count', players.length);
    setText('status-save-count', storage.save_count || 0);
    setText('status-save-detail', `${storage.mod_count || 0} installed mods`);
    setText('status-save-file', `Configured save: ${configuredSave || '—'}`);
    const externalHost = hostname;
    const gamePort = connection.game_port || factorio.game_port || '—';
    const rconPort = connection.rcon_port || factorio.rcon_port || '—';
    setText('status-host', externalHost);
    setText('status-connection-detail', `Host ${externalHost} (${hostIp}) · Factorio UDP ${gamePort} · RCON TCP ${rconPort}`);
    setText('status-mod-detail', `${storage.mod_count || 0} mods installed`);
    byId('server-factorio') && (byId('server-factorio').textContent = factorio.running ? 'Online' : 'Offline');
    byId('server-factorio-detail') && (byId('server-factorio-detail').textContent = `v${factorio.version || '—'} · UDP ${factorio.game_port || '—'}`);
    byId('server-factorio-dot')?.classList.toggle('online', Boolean(factorio.running));
    byId('server-factorio-dot')?.classList.toggle('offline', !factorio.running);
    byId('server-bridge') && (byId('server-bridge').textContent = bridge.running ? 'Connected' : 'Stopped');
    byId('server-bridge-detail') && (byId('server-bridge-detail').textContent = bridge.rcon_password_present ? 'RCON credentials ready' : 'Waiting for RCON');
    byId('server-bridge-dot')?.classList.toggle('online', Boolean(bridge.running));
    byId('server-bridge-dot')?.classList.toggle('offline', !bridge.running);
    byId('server-web') && (byId('server-web').textContent = processes.web ? 'Running' : 'Stopped');
    byId('server-web-dot')?.classList.toggle('online', Boolean(processes.web));
    byId('server-web-dot')?.classList.toggle('offline', !processes.web);
    byId('server-connection') && (byId('server-connection').innerHTML = `<div class="storage-row"><span>Hostname</span><b>${escapeHtml(externalHost)}</b></div><div class="storage-row"><span>IP address</span><b>${escapeHtml(hostIp)}</b></div><div class="storage-row"><span>Factorio UDP</span><b>${gamePort}</b></div><div class="storage-row"><span>RCON TCP</span><b>${rconPort}</b></div>`);
    byId('server-storage') && (byId('server-storage').innerHTML = `<div class="storage-row"><span>Save directory</span><b>${escapeHtml(saveDetails.directory || '—')}</b></div><div class="storage-row"><span>Configured save</span><b>${escapeHtml(configuredSave || '—')}</b></div><div class="storage-row"><span>Installed mods</span><b>${storage.mod_count || 0}</b></div>`);
    setText('system-web-status', processes.web ? 'Running' : 'Stopped');
    setText('system-factorio-status', processes.factorio ? 'Running' : 'Stopped');
    setText('system-storage-meta', `${storage.save_count || 0} saves · ${storage.mod_count || 0} mods`);
    const systemStorage = byId('system-storage');
    if (systemStorage) systemStorage.innerHTML = `<div class="storage-row"><span>Save directory</span><b>${escapeHtml(saveDetails.directory || '—')}</b></div><div class="storage-row"><span>Configured save</span><b>${escapeHtml(configuredSave || '—')}</b></div><div class="storage-row"><span>Log lines shown</span><b>${Array.isArray(data.log) ? data.log.length : 0}</b></div>`;
    const onlinePlayers = players.filter((player) => player.connected);
    renderModsView(Array.isArray(storage.mods) ? storage.mods : []);
    renderResearchSummary();
    if (technologyEntries.length) renderTechnologyTree();
    const offlinePlayers = players.filter((player) => !player.connected);
    const playerColor = (player) => {
      const color = player.color || {};
      const channel = (value, fallback) => Math.round(Math.max(0, Math.min(1, Number(value ?? fallback))) * 255);
      return `rgb(${channel(color.r, 0.869)} ${channel(color.g, 0.5)} ${channel(color.b, 0.130)})`;
    };
    const playerAvatar = (player) => `<div class="player-avatar" style="--player-color: ${playerColor(player)}"><img class="player-avatar-image" src="/api/icon?path=__core__/graphics/icons/entity/character.png" alt="${escapeHtml(player.name)} character" onerror="this.hidden=true; this.nextElementSibling.hidden=false"><span class="player-avatar-fallback" hidden>${escapeHtml(player.name.slice(0, 1).toUpperCase())}</span></div>`;
    const playerCard = (player) => {
      if (!player.connected) {
        return `<article class="player-card player-offline">${playerAvatar(player)}<div class="player-main"><div class="player-heading"><h3>${escapeHtml(player.name)}</h3></div><span class="status-detail">Offline</span></div><strong>Offline</strong></article>`;
      }
      const armor = player.armor || {};
      const armorName = armor.name && armor.name !== 'none' ? armor.name : 'No armor';
      const maxHealth = Number(player.max_health || 0);
      const health = Number(player.health || 0);
      const healthPercent = maxHealth > 0 ? Math.max(0, Math.min(100, (health / maxHealth) * 100)) : 0;
      const inventory = player.inventory || {};
      const usedSlots = Number(inventory.used_slots || 0);
      const totalSlots = Number(inventory.total_slots || 0);
      const inventoryLabel = totalSlots > 0 ? `${usedSlots} / ${totalSlots} slots` : 'Inventory unavailable';
      const activityFlags = `${player.motion && player.connected ? '<span class="player-flag player-flag-motion" title="Moving" aria-label="Moving">↔</span>' : ''}${player.idle ? '<span class="player-flag player-flag-afk" title="Away from keyboard" aria-label="Away from keyboard">Z</span>' : ''}${player.injured ? '<span class="player-flag player-flag-injured" title="Injured" aria-label="Injured">!</span>' : ''}`;
      return `<article class="player-card player-online">${playerAvatar(player)}<div class="player-main"><div class="player-heading"><h3>${escapeHtml(player.name)}</h3><div class="player-flags">${activityFlags}</div></div><span class="status-detail">${escapeHtml(player.surface)} · ${escapeHtml(player.x)}, ${escapeHtml(player.y)}</span><div class="player-health"><div class="player-health-label"><span>${escapeHtml(health)} / ${escapeHtml(maxHealth)} HP</span><span>${escapeHtml(armorName)}</span></div><div class="player-healthbar" aria-label="Health ${Math.round(healthPercent)} percent"><span style="width:${healthPercent.toFixed(1)}%"></span></div></div><span class="player-stats">${escapeHtml(armorName)} · ${escapeHtml(armor.equipment_count || 0)} equipment · ${escapeHtml(inventoryLabel)} · ${player.idle ? 'AFK' : 'Active'}</span></div><strong>${escapeHtml(player.deaths)} <small>deaths</small></strong></article>`;
    };
    const playerSection = (title, entries, empty) => `<section class="player-section"><div class="section-heading"><h3>${title}</h3><span class="panel-tag">${entries.length}</span></div>${entries.length ? `<div class="player-grid">${entries.map(playerCard).join('')}</div>` : `<p class="muted">${empty}</p>`}</section>`;
    const playerResults = byId('player-results');
    if (playerResults) playerResults.innerHTML = playerSection('Online now', onlinePlayers, 'No players are connected.') + playerSection('Offline', offlinePlayers, 'No offline player profiles yet.');
    if (byId('status-log-output')) byId('status-log-output').textContent = data.log?.length ? data.log.join('\n') : 'No log output yet.';
    const telemetryResponse = await fetch(apiUrl('api/telemetry/events?limit=50'), { cache: 'no-store' });
    const telemetry = telemetryResponse.ok ? await telemetryResponse.json() : { events: [] };
    const events = Array.isArray(telemetry.events) ? telemetry.events : [];
    setText('telemetry-event-meta', `${events.length} EVENTS`);
    const telemetryEvents = byId('telemetry-events');
    if (telemetryEvents) telemetryEvents.innerHTML = events.length
      ? events.slice().reverse().map((event) => `<div class="telemetry-event"><strong>${escapeHtml(event.event)}</strong><span>${escapeHtml(event.bridge_received_at || `tick ${event.tick ?? '—'}`)}</span><code>${escapeHtml(JSON.stringify(event))}</code></div>`).join('')
      : '<p class="muted">No structured telemetry events yet.</p>';
    setText('status-updated', `UPDATED ${new Date(data.generated_at * 1000).toLocaleTimeString()}`);
    byId('overview-stamp') && (byId('overview-stamp').textContent = `LIVE · ${new Date(data.generated_at * 1000).toLocaleTimeString()}`);
    byId('players-stamp') && (byId('players-stamp').textContent = `${players.length} PROFILES`);
  } catch (error) {
    console.error('Factorio Assistant status refresh failed', error);
    byId('status-factorio') && (byId('status-factorio').textContent = 'Unavailable');
    byId('status-updated') && (byId('status-updated').textContent = `CONNECTION UNAVAILABLE: ${error.message || 'request failed'}`);
  }
}
async function refreshWorld() {
  try {
    const response = await fetch(apiUrl('api/world'), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    const surfaces = Array.isArray(data.surfaces) ? data.surfaces : [];
    renderResourceMonitor(data);
    renderResourceOverview(data);
    renderLogisticsView(data);
    const players = Array.isArray(data.players) ? data.players : [];
    const available = Boolean(data.available);
    byId('world-tick').textContent = available ? Number(data.tick).toLocaleString() : 'Unavailable';
    const onlinePlayers = players.filter((player) => player.connected).length;
    const hasLiveMetrics = available && (players.length > 0 || data.game_time !== '' && data.game_time !== null && data.game_time !== undefined);
    if (hasLiveMetrics) lastWorldMetrics = { players: onlinePlayers, gameTime: data.game_time };
    setText('overview-online-players', lastWorldMetrics.players ?? '—');
    setText('overview-game-time', formatGameTime(lastWorldMetrics.gameTime));
    byId('overview-tick') && (byId('overview-tick').textContent = data.available ? Number(data.tick).toLocaleString() : '—');
    byId('world-state-title') && (byId('world-state-title').textContent = available ? 'Nauvis is running' : 'World unavailable');
    byId('world-state-detail') && (byId('world-state-detail').textContent = available ? `${surfaces.length} surfaces · ${players.length} players connected` : (data.error || 'The bridge is not reporting a live world.'));
    byId('world-speed').textContent = `Simulation speed ${available ? Number(data.speed).toFixed(2) : '—'}`;
    byId('world-daytime').textContent = available ? `${(Number(data.daytime) * 100).toFixed(1)}%` : '—';
    byId('world-game-time').textContent = `Game time ${available ? `${Number(data.game_time || 0).toLocaleString()} s · Day ${Number(data.game_day || 0).toLocaleString()}` : '—'}`;
    byId('world-evolution').textContent = available ? `${(Number(data.evolution) * 100).toFixed(1)}%` : '—';
    byId('world-evolution-progress').textContent = `Research progress ${available ? `${Number(data.research_progress || 0).toFixed(1)}%` : '—'}`;
    byId('world-surface-count').textContent = surfaces.length;
    byId('world-surface-list').textContent = surfaces.map((surface) => surface.name).join(' · ') || 'No surfaces reported';
    byId('overview-daytime') && (byId('overview-daytime').textContent = available ? `${(Number(data.daytime) * 100).toFixed(1)}%` : '—');
    byId('overview-evolution') && (byId('overview-evolution').textContent = available ? `${(Number(data.evolution) * 100).toFixed(1)}%` : '—');
    byId('overview-surfaces') && (byId('overview-surfaces').textContent = surfaces.length);
    byId('overview-world-name') && (byId('overview-world-name').textContent = available ? (surfaces[0]?.name || 'Active world') : 'World telemetry unavailable');
    byId('overview-world-detail') && (byId('overview-world-detail').textContent = available ? `Simulation speed ${Number(data.speed).toFixed(2)} · ${players.length} players connected` : (data.error || 'Waiting for the RCON bridge.'));
    byId('overview-surface-list') && (byId('overview-surface-list').textContent = surfaces.map((surface) => surface.name).join(' · ') || 'No surfaces reported');
    byId('world-player-count').textContent = players.length;
    byId('world-connected-tag') && (byId('world-connected-tag').textContent = `${players.length} ONLINE`);
    byId('world-players').innerHTML = players.length ? players.map((player) => `<div class="world-player"><b>${escapeHtml(player.name)}</b><span>${escapeHtml(player.surface)} · ${player.x}, ${player.y}</span></div>`).join('') : '<p class="muted">No players connected in-game.</p>';
    const researchQueue = Array.isArray(data.research_queue) ? data.research_queue : [];
    byId('world-research-level').textContent = `${Number(data.technologies_researched || 0)} / ${Number(data.technologies_total || 0)}`;
    byId('world-research').innerHTML = `<div class="storage-row"><span>Current research</span><b>${escapeHtml(data.research || 'None')}</b></div><div class="storage-row"><span>Progress</span><b>${Number(data.research_progress || 0).toFixed(1)}%</b></div><div class="storage-row"><span>Queue</span><b>${escapeHtml(researchQueue.join(' · ') || 'Empty')}</b></div>`;
    const surfaceRows = surfaces.map((surface) => `<div class="storage-row"><span>${escapeHtml(surface.name)}</span><b>${Number(surface.pollution || 0).toFixed(1)} pollution</b></div>`).join('');
    byId('world-factory-meta').textContent = `${Number(data.rockets_launched || 0)} rockets`;
    byId('world-factory').innerHTML = `<div class="storage-row"><span>Active entities</span><b>${Number(data.active_entity_count || 0).toLocaleString()}</b></div><div class="storage-row"><span>Rockets launched</span><b>${Number(data.rockets_launched || 0).toLocaleString()}</b></div>`;
    byId('world-mod-count').textContent = `${surfaces.length} surfaces`;
    byId('world-mods').innerHTML = surfaceRows || '<p class="muted">No surface telemetry reported.</p>';
  } catch (error) {
    byId('world-tick').textContent = 'Unavailable';
    byId('world-surface-list').textContent = error.message || 'World telemetry unavailable';
    setText('overview-online-players', lastWorldMetrics.players ?? '—');
    setText('overview-game-time', formatGameTime(lastWorldMetrics.gameTime));
  }
}
async function restoreSave(source) {
  if (!window.confirm(`Restore ${source} over the configured save?`)) return;
  const response = await fetch(apiUrl('api/saves/restore'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source }) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Restore failed.');
  await waitForRestore();
  await refreshWorld();
}
async function waitForRestore() {
  for (let attempt = 0; attempt < 45; attempt += 1) {
    await refreshStatus();
    const state = byId('save-restore-status')?.textContent || '';
    if (!['Stopping', 'Restoring', 'Starting'].some((phase) => state.includes(phase))) return;
    await new Promise((resolve) => window.setTimeout(resolve, 2000));
  }
}
async function deleteSave(name) {
  if (!window.confirm(`Delete ${name}?`)) return;
  const response = await fetch(apiUrl('api/saves/delete'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Delete failed.');
  await refreshStatus();
}
function renderSaveFiles(details) {
  const results = byId('save-file-results');
  const autosaves = byId('save-autosave-results');
  if (!results && !autosaves) return;
  if (!byId('save-file-filter')) {
    results.insertAdjacentHTML('beforebegin', '<div class="save-files-toolbar"><span id="save-filter-count" class="status-detail">Loading save files...</span><label class="save-filter-control"><span>Show</span><select id="save-file-filter"><option value="all">All saves and backups</option><option value="save">Saves only</option><option value="matching-backups">Configured save and matching backups</option></select></label></div>');
    byId('save-file-filter').addEventListener('change', (event) => { saveFileFilter = event.target.value; renderSaveFiles(details); });
  }
  const configured = details.configured || '';
  const files = Array.isArray(details.files) ? details.files : [];
  const autosaveFiles = files.filter((file) => file.autosave);
  const visibleFiles = files.filter((file) => !file.autosave && (saveFileFilter === 'all' || (saveFileFilter === 'save' ? !file.backup : file.backup || file.name === configured)));
  setText('save-filter-count', `${autosaveFiles.length} autosaves · ${visibleFiles.length} saves/backups`);
  if (autosaves) {
    autosaves.innerHTML = autosaveFiles.length ? autosaveFiles.map((file) => {
      const isConfigured = file.name === configured;
      const timestamp = Number(file.modified || 0) ? new Date(Number(file.modified) * 1000).toLocaleString() : 'Timestamp unavailable';
      return `<article class="save-file-card save-file-autosave ${isConfigured ? 'save-file-configured' : ''}"><div class="save-file-card-heading"><span class="save-file-icon">▣</span><span class="save-file-kind">AUTOSAVE</span></div><strong class="save-file-name">${escapeHtml(file.name)}</strong><div class="save-file-details"><span>${formatBytes(file.size)}</span><span>${escapeHtml(timestamp)}</span></div><div class="save-file-actions">${isConfigured ? '<span class="panel-tag">ACTIVE</span>' : `<button class="save-action-button restore-save" data-save-restore="${escapeHtml(file.name)}">Restore</button><button class="save-action-button save-delete-button" data-save-delete="${escapeHtml(file.name)}">Delete</button>`}</div></article>`;
    }).join('') : '<p class="muted">No internal autosaves found yet.</p>';
  }
  results.innerHTML = visibleFiles.length ? visibleFiles.map((file) => {
    const isConfigured = file.name === configured;
    const kind = isConfigured ? 'CONFIGURED' : file.backup ? 'BACKUP' : file.autosave ? 'AUTOSAVE' : 'SAVE';
    const actions = isConfigured ? '<span class="panel-tag">ACTIVE</span>' : `<button class="save-action-button restore-save" data-save-restore="${escapeHtml(file.name)}">Restore</button><button class="save-action-button save-delete-button" data-save-delete="${escapeHtml(file.name)}">Delete</button>`;
    const timestamp = Number(file.modified || 0) ? new Date(Number(file.modified) * 1000).toLocaleString() : 'Timestamp unavailable';
    return `<article class="save-file-card save-file-${kind.toLowerCase()}"><div class="save-file-card-heading"><span class="save-file-icon">▣</span><span class="save-file-kind">${kind}</span></div><strong class="save-file-name">${escapeHtml(file.name)}</strong><div class="save-file-details"><span>${formatBytes(file.size)}</span><span>${escapeHtml(timestamp)}</span></div><div class="save-file-actions">${actions}</div></article>`;
  }).join('') : `<p class="muted">No ${saveFileFilter === 'matching-backups' ? 'matching backup' : saveFileFilter === 'save' ? 'save' : 'save'} files found.</p>`;
  results.querySelectorAll('[data-save-restore]').forEach((button) => button.addEventListener('click', () => restoreSave(button.dataset.saveRestore).catch((error) => window.alert(error.message))));
  results.querySelectorAll('[data-save-delete]').forEach((button) => button.addEventListener('click', () => deleteSave(button.dataset.saveDelete).catch((error) => window.alert(error.message))));
  autosaves?.querySelectorAll('[data-save-restore]').forEach((button) => button.addEventListener('click', () => restoreSave(button.dataset.saveRestore).catch((error) => window.alert(error.message))));
  autosaves?.querySelectorAll('[data-save-delete]').forEach((button) => button.addEventListener('click', () => deleteSave(button.dataset.saveDelete).catch((error) => window.alert(error.message))));
}
function switchAppTab(tabName, refresh = true) {
  document.querySelectorAll('[data-app-tab]').forEach((tab) => tab.classList.toggle('active', tab.dataset.appTab === tabName));
  document.querySelectorAll('[data-app-view]').forEach((view) => view.classList.toggle('active', view.dataset.appView === tabName));
  if (!refresh) return;
  if (tabName === 'overview' || tabName === 'world' || tabName === 'system' || tabName === 'mods' || tabName === 'storage') refreshStatus();
  if (tabName === 'overview' || tabName === 'world' || tabName === 'resources') refreshWorld();
  if (tabName === 'logistics') refreshWorld();
  if (tabName === 'browse') { renderExploreTabs(); refreshExplore(); refreshCatalogMetadata(); }
  if (tabName === 'production' && byId('production-output') && !byId('production-output').querySelector('.production-summary')) byId('production-output').innerHTML = '<p class="muted">Run a plan to see the chain and machine breakdown.</p>';
}
document.querySelectorAll('[data-app-tab]').forEach((tab) => tab.addEventListener('click', () => switchAppTab(tab.dataset.appTab)));
document.querySelectorAll('[data-master-kind]').forEach((tab) => tab.addEventListener('click', () => selectMasterCatalogGroup(tab.dataset.masterKind)));
byId('explore-query')?.addEventListener('input', () => { exploreOffset = 0; refreshExplore(); });
byId('explore-previous')?.addEventListener('click', () => { exploreOffset = Math.max(0, exploreOffset - 48); refreshExplore(); });
byId('explore-next')?.addEventListener('click', () => { exploreOffset += 48; refreshExplore(); });
byId('production-run')?.addEventListener('click', () => runProductionPlan());
byId('status-refresh').addEventListener('click', refreshStatus);
byId('world-refresh').addEventListener('click', refreshWorld);
byId('resources-refresh')?.addEventListener('click', refreshWorld);
byId('storage-refresh')?.addEventListener('click', refreshStatus);
async function updateBackupSettings() {
  const enabled = byId('save-backups-enabled').checked;
  const mode = byId('save-backup-mode').value;
  const interval_hours = Number(byId('save-backup-interval').value);
  const daily_time = byId('save-backup-daily-time').value;
  const max_saves = Number(byId('save-backup-max-saves').value);
  const max_total_size_mb = Number(byId('save-backup-max-size').value);
  if (!Number.isInteger(interval_hours) || interval_hours < 1 || !Number.isInteger(max_saves) || max_saves < 1 || !Number.isInteger(max_total_size_mb) || max_total_size_mb < 0 || (mode === 'daily' && !daily_time)) {
    window.alert('Enter valid schedule and retention values.');
    return;
  }
  const response = await fetch(apiUrl('api/saves/backup-settings'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled, mode, interval_hours, daily_time, max_saves, max_total_size_mb }) });
  const data = await response.json();
  if (!response.ok) window.alert(data.error || 'Backup setting failed.');
  else await refreshStatus();
}
function updateBackupScheduleVisibility() {
  const daily = byId('save-backup-mode')?.value === 'daily';
  if (byId('save-backup-interval-label')) byId('save-backup-interval-label').hidden = daily;
  if (byId('save-backup-daily-label')) byId('save-backup-daily-label').hidden = !daily;
}
byId('save-backups-enabled')?.addEventListener('change', updateBackupSettings);
byId('save-backup-mode')?.addEventListener('change', () => { updateBackupScheduleVisibility(); updateBackupSettings(); });
byId('save-backup-interval')?.addEventListener('change', updateBackupSettings);
byId('save-backup-daily-time')?.addEventListener('change', updateBackupSettings);
byId('save-backup-max-saves')?.addEventListener('change', updateBackupSettings);
byId('save-backup-max-size')?.addEventListener('change', updateBackupSettings);
syncHomeAssistantTheme();
try {
  new MutationObserver(syncHomeAssistantTheme).observe(window.parent.document.documentElement, { attributes: true, attributeFilter: ['class', 'style'] });
} catch {
  // Direct access does not have a Home Assistant parent document.
}
setupDashboardShell();
refreshStatus();
refreshWorld();
refreshCatalogMetadata();
renderMasterCatalogGroups();
renderExploreTabs();
refreshExplore();
setInterval(refreshStatus, 10000);
setInterval(refreshWorld, 10000);
