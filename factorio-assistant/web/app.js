const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
const apiUrl = (path) => new URL(`./${path.replace(/^\//, '')}`, document.baseURI).toString();
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
let researchState = { available: false, researched: [], current: '', progress: 0, queue: [] };
let monitoredTechnologies = new Set(JSON.parse(localStorage.getItem('factorio-monitored-technologies') || '[]'));
function renderResearchSummary() {
  const currentEntry = technologyEntries.find((entry) => entry.name === researchState.current);
  const summary = byId('research-summary');
  if (!summary) return;
  summary.innerHTML = `<span><b>${researchState.available ? `${researchState.researched.length} researched` : 'Research unavailable'}</b></span><span>${currentEntry ? `Current: ${escapeHtml(currentEntry.localized_name || currentEntry.name)} · ${Number(researchState.progress || 0).toFixed(1)}%` : 'No active research'}</span><span>Queue: ${researchState.queue.length}</span><span>Monitoring: ${monitoredTechnologies.size}</span>`;
}
const catalogView = () => document.querySelector('.factoriopedia-view.active .pedia-panel-active[data-catalog-kind]');
const catalogElement = (name) => catalogView()?.querySelector(`[data-catalog-element="${name}"]`) || byId({ query: 'catalog-query', previous: 'catalog-previous', page: 'catalog-page', next: 'catalog-next', results: 'catalog-results', detail: 'catalog-detail' }[name]);
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
const formatDetailValue = (key, value) => key === 'effects' && Array.isArray(value) ? value.map(formatEffect).join('\n') : ['ingredients', 'products', 'results', 'fluid_box'].includes(key) ? formatLocalizedList(value) : ['localized_prerequisites', 'made_in', 'used_in', 'unlocked_recipes'].includes(key) ? formatLocalizedRefs(value) : formatValue(value);
const referenceKind = (value, fallback = '') => {
  if (fallback === 'made_in' || fallback === 'used_in' || fallback === 'unlocked_recipes') return 'recipe';
  if (fallback === 'prerequisites') return 'technology';
  if (typeof value === 'object' && value) return ({ item: 'item', fluid: 'fluid', recipe: 'recipe', technology: 'technology' }[value.type] || fallback);
  return fallback;
};
const referenceMarkup = (key, value, localizedValues = null) => {
  const values = Array.isArray(value) ? value : [value];
  return values.map((entry, index) => {
    const name = typeof entry === 'object' && entry ? entry.name : entry;
    const kind = referenceKind(entry, key);
    if (!name || !kind || !['item', 'fluid', 'recipe', 'technology'].includes(kind)) return escapeHtml(formatDetailValue(key, entry));
    const localizedLabel = Array.isArray(localizedValues) ? localizedValues[index] : null;
    const label = localizedLabel || (typeof entry === 'object' && entry ? (entry.localized_name || entry.name) : entry);
    const amount = typeof entry === 'object' && entry ? (entry.amount ?? entry.amount_min ?? '') : '';
    return `<button class="catalog-reference" data-ref-kind="${escapeHtml(kind)}" data-ref-name="${escapeHtml(name)}">${escapeHtml(label)}</button>${amount === '' ? '' : ` <span class="reference-amount">× ${escapeHtml(amount)}</span>`}`;
  }).join('<span class="reference-entry-break"></span>');
};
const isReferenceField = (key) => ['ingredients', 'products', 'results', 'prerequisites', 'localized_prerequisites', 'made_in', 'used_in', 'unlocked_recipes'].includes(key);
function bindReferenceLinks(root = document) {
  root.querySelectorAll('[data-ref-kind]').forEach((link) => link.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    openCatalogReference(link.dataset.refKind, link.dataset.refName);
  }));
}
async function openCatalogReference(kind, name) {
  try {
    const response = await fetch(apiUrl(`api/catalog?${new URLSearchParams({ query: name, kind, limit: '100' })}`), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Catalog entry unavailable.');
    const entry = data.results?.find((candidate) => candidate.name === name);
    if (!entry || entry.name !== name) throw new Error(`Catalog entry not found: ${name}`);
    switchAppTab('catalog', false);
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
    if (typeof value === 'string') return value.includes('/') && (value.endsWith('.png') || value.endsWith('.jpg') || value.endsWith('.webp')) ? value : '';
    if (Array.isArray(value)) return value.map(findPath).find(Boolean) || '';
    if (!value || typeof value !== 'object') return '';
    return findPath(value.icon) || findPath(value.filename) || findPath(value.icons) || findPath(value.layers) || '';
  };
  return findPath(entry.icon) || findPath(entry.icons) || '';
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
  detailTarget.innerHTML = `<div class="detail-hero">${iconMarkup(entry, 'detail-icon')}<div><p class="eyebrow">${escapeHtml(entry.kind)} · ${escapeHtml(entry.type)}</p><h4>${escapeHtml(entry.localized_name || entry.name)}</h4><span class="detail-id">ID: ${escapeHtml(entry.name)}</span>${monitorButton}</div></div>${headline ? `<div class="detail-stats">${headline}</div>` : ''}${detailFields.length ? `<details class="technical-details"><summary>Technical details</summary><div class="detail-fields">${detailFields.map(([key, value]) => `<div><b>${escapeHtml(key.replaceAll('_', ' '))}</b>${isReferenceField(key) ? `<p>${referenceMarkup(key, value)}</p>` : `<pre>${escapeHtml(formatDetailValue(key, value))}</pre>`}</div>`).join('')}</div></details>` : ''}`;
  bindReferenceLinks(detailTarget);
  detailTarget.querySelector('[data-monitor-name]')?.addEventListener('click', () => toggleMonitoredTechnology(entry.name));
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
const masterCatalogLabels = { item: 'Find an item', recipe: 'Make something', technology: 'Research', entity: 'Build & machines', all: 'Browse everything' };
function renderMasterCatalogGroups() {
  const groups = byId('catalog-master-groups');
  if (!groups) return;
  groups.innerHTML = Object.entries(masterCatalogLabels).map(([kind, label]) => `<button class="catalog-master-tab ${kind === masterCatalogKind ? 'active' : ''}" data-master-kind="${kind}">${label}</button>`).join('');
  groups.querySelectorAll('[data-master-kind]').forEach((tab) => tab.addEventListener('click', () => selectMasterCatalogGroup(tab.dataset.masterKind)));
}
function selectMasterCatalogGroup(kind) {
  masterCatalogKind = kind;
  exploreKind = kind;
  exploreOffset = 0;
  renderMasterCatalogGroups();
  renderExploreTabs();
  refreshExplore();
}
function renderExploreTabs() {
  const tabs = byId('explore-kind-tabs');
  if (!tabs) return;
  tabs.innerHTML = exploreKinds.map((kind) => `<button class="explore-kind-tab ${exploreKind === kind ? 'active' : ''}" data-explore-kind="${kind}">${escapeHtml(exploreLabel(kind))}</button>`).join('');
  tabs.querySelectorAll('[data-explore-kind]').forEach((tab) => tab.addEventListener('click', () => { exploreKind = tab.dataset.exploreKind; exploreOffset = 0; renderExploreTabs(); refreshExplore(); }));
}
async function refreshExplore() {
  const query = byId('explore-query')?.value.trim() || '';
  const params = new URLSearchParams({ query, kind: exploreKind, limit: '48', offset: String(exploreOffset) });
  try {
    const response = await fetch(apiUrl(`api/catalog?${params}`), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    exploreResults = data.results || [];
    byId('explore-meta').textContent = `${data.total} results · ${exploreLabel(exploreKind)} · Factorio ${data.factorio_version}`;
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
  if (entry.kind === 'recipe') practical += detailSection('Ingredients', detailLinks('ingredients', entry.ingredients)) + detailSection('Produces', detailLinks('results', entry.results || entry.products));
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
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    byId('server-name').textContent = data.factorio.name || 'Factory reference';
    byId('header-status')?.replaceChildren(document.createTextNode(data.factorio.running ? 'ONLINE' : 'OFFLINE'));
    byId('header-status-dot')?.classList.toggle('online', Boolean(data.factorio.running));
    byId('header-status-dot')?.classList.toggle('offline', !data.factorio.running);
    byId('overview-factorio-state') && (byId('overview-factorio-state').textContent = data.factorio.running ? 'Online' : 'Offline');
    byId('overview-players') && (byId('overview-players').textContent = data.players.filter((player) => player.connected).length);
    byId('overview-players-detail') && (byId('overview-players-detail').textContent = `${data.players.length} known profiles`);
    byId('overview-saves') && (byId('overview-saves').textContent = data.storage.save_count);
    byId('overview-save-detail') && (byId('overview-save-detail').textContent = `Configured: ${data.storage.save_details?.configured || '—'}`);
    byId('overview-mods') && (byId('overview-mods').textContent = data.storage.mod_count);
    byId('overview-mod-detail') && (byId('overview-mod-detail').textContent = `${data.storage.mod_count} archives in storage`);
    byId('status-factorio').textContent = data.factorio.running ? 'Online' : 'Offline';
    byId('status-factorio-detail').textContent = `v${data.factorio.version} · UDP ${data.factorio.game_port}`;
    byId('status-bridge').textContent = data.bridge.running ? 'Connected' : 'Stopped';
    byId('status-bridge-detail').textContent = data.bridge.rcon_password_present ? 'RCON credentials ready' : 'Waiting for RCON';
    byId('status-player-count').textContent = data.players.length;
    byId('status-save-count').textContent = data.storage.save_count;
    byId('status-save-detail').textContent = `${data.storage.mod_count} installed mods`;
    byId('status-save-file').textContent = `Configured save: ${data.storage.save_details?.configured || '—'}`;
    const externalHost = window.location.hostname || data.bridge.host || '—';
    byId('status-host').textContent = externalHost;
    byId('status-connection-detail').textContent = `Host ${externalHost} · Factorio UDP ${data.factorio.game_port} · RCON TCP ${data.factorio.rcon_port}`;
    byId('status-mod-detail').textContent = `${data.storage.mod_count} mods installed`;
    byId('server-factorio') && (byId('server-factorio').textContent = data.factorio.running ? 'Online' : 'Offline');
    byId('server-factorio-detail') && (byId('server-factorio-detail').textContent = `v${data.factorio.version} · UDP ${data.factorio.game_port}`);
    byId('server-factorio-dot')?.classList.toggle('online', Boolean(data.factorio.running));
    byId('server-factorio-dot')?.classList.toggle('offline', !data.factorio.running);
    byId('server-bridge') && (byId('server-bridge').textContent = data.bridge.running ? 'Connected' : 'Stopped');
    byId('server-bridge-detail') && (byId('server-bridge-detail').textContent = data.bridge.rcon_password_present ? 'RCON credentials ready' : 'Waiting for RCON');
    byId('server-bridge-dot')?.classList.toggle('online', Boolean(data.bridge.running));
    byId('server-bridge-dot')?.classList.toggle('offline', !data.bridge.running);
    byId('server-web') && (byId('server-web').textContent = data.processes?.web ? 'Running' : 'Stopped');
    byId('server-web-dot')?.classList.toggle('online', Boolean(data.processes?.web));
    byId('server-web-dot')?.classList.toggle('offline', !data.processes?.web);
    byId('server-connection') && (byId('server-connection').innerHTML = `<div class="storage-row"><span>Host</span><b>${escapeHtml(externalHost)}</b></div><div class="storage-row"><span>Factorio UDP</span><b>${data.factorio.game_port}</b></div><div class="storage-row"><span>RCON TCP</span><b>${data.factorio.rcon_port}</b></div>`);
    byId('server-storage') && (byId('server-storage').innerHTML = `<div class="storage-row"><span>Save directory</span><b>${escapeHtml(data.storage.save_details?.directory || '—')}</b></div><div class="storage-row"><span>Configured save</span><b>${escapeHtml(data.storage.save_details?.configured || '—')}</b></div><div class="storage-row"><span>Installed mods</span><b>${data.storage.mod_count}</b></div>`);
    byId('system-web-status').textContent = data.processes?.web ? 'Running' : 'Stopped';
    byId('system-factorio-status').textContent = data.processes?.factorio ? 'Running' : 'Stopped';
    byId('system-storage-meta').textContent = `${data.storage.save_count} saves · ${data.storage.mod_count} mods`;
    byId('system-storage').innerHTML = `<div class="storage-row"><span>Save directory</span><b>${escapeHtml(data.storage.save_details?.directory || '—')}</b></div><div class="storage-row"><span>Configured save</span><b>${escapeHtml(data.storage.save_details?.configured || '—')}</b></div><div class="storage-row"><span>Log lines shown</span><b>${data.log.length}</b></div>`;
    const onlinePlayers = data.players.filter((player) => player.connected);
    renderResearchSummary();
    if (technologyEntries.length) renderTechnologyTree();
    const offlinePlayers = data.players.filter((player) => !player.connected);
    const playerCard = (player) => {
      if (!player.connected) {
        return `<article class="player-card player-offline"><div class="player-avatar"><span class="player-avatar-fallback">${escapeHtml(player.name.slice(0, 1).toUpperCase())}</span></div><div class="player-main"><div class="player-heading"><h3>${escapeHtml(player.name)}</h3></div><span class="status-detail">Offline</span></div><strong>Offline</strong></article>`;
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
      const armorBadge = armor.icon_url
        ? `<img class="player-avatar-image" src="${escapeHtml(armor.icon_url)}" alt="${escapeHtml(armorName)}">`
        : `<span class="player-avatar-fallback">${escapeHtml(player.name.slice(0, 1).toUpperCase())}</span>`;
      const activityFlags = `${player.motion && player.connected ? '<span class="player-flag player-flag-motion" title="Moving" aria-label="Moving">↔</span>' : ''}${player.idle ? '<span class="player-flag player-flag-afk" title="Away from keyboard" aria-label="Away from keyboard">Z</span>' : ''}${player.injured ? '<span class="player-flag player-flag-injured" title="Injured" aria-label="Injured">!</span>' : ''}`;
      return `<article class="player-card player-online"><div class="player-avatar">${armorBadge}</div><div class="player-main"><div class="player-heading"><h3>${escapeHtml(player.name)}</h3><div class="player-flags">${activityFlags}</div></div><span class="status-detail">${escapeHtml(player.surface)} · ${escapeHtml(player.x)}, ${escapeHtml(player.y)}</span><div class="player-health"><div class="player-health-label"><span>${escapeHtml(health)} / ${escapeHtml(maxHealth)} HP</span><span>${escapeHtml(armorName)}</span></div><div class="player-healthbar" aria-label="Health ${Math.round(healthPercent)} percent"><span style="width:${healthPercent.toFixed(1)}%"></span></div></div><span class="player-stats">${escapeHtml(armorName)} · ${escapeHtml(armor.equipment_count || 0)} equipment · ${escapeHtml(inventoryLabel)} · ${player.idle ? 'AFK' : 'Active'}</span></div><strong>${escapeHtml(player.deaths)} <small>deaths</small></strong></article>`;
    };
    const playerSection = (title, entries, empty) => `<section class="player-section"><div class="section-heading"><h3>${title}</h3><span class="panel-tag">${entries.length}</span></div>${entries.length ? `<div class="player-grid">${entries.map(playerCard).join('')}</div>` : `<p class="muted">${empty}</p>`}</section>`;
    byId('player-results').innerHTML = playerSection('Online now', onlinePlayers, 'No players are connected.') + playerSection('Offline', offlinePlayers, 'No offline player profiles yet.');
    if (byId('status-log-output')) byId('status-log-output').textContent = data.log.length ? data.log.join('\n') : 'No log output yet.';
    const telemetryResponse = await fetch(apiUrl('api/telemetry/events?limit=50'), { cache: 'no-store' });
    const telemetry = telemetryResponse.ok ? await telemetryResponse.json() : { events: [] };
    const events = Array.isArray(telemetry.events) ? telemetry.events : [];
    byId('telemetry-event-meta').textContent = `${events.length} EVENTS`;
    byId('telemetry-events').innerHTML = events.length
      ? events.slice().reverse().map((event) => `<div class="telemetry-event"><strong>${escapeHtml(event.event)}</strong><span>${escapeHtml(event.bridge_received_at || `tick ${event.tick ?? '—'}`)}</span><code>${escapeHtml(JSON.stringify(event))}</code></div>`).join('')
      : '<p class="muted">No structured telemetry events yet.</p>';
    byId('status-updated').textContent = `UPDATED ${new Date(data.generated_at * 1000).toLocaleTimeString()}`;
    byId('overview-stamp') && (byId('overview-stamp').textContent = `LIVE · ${new Date(data.generated_at * 1000).toLocaleTimeString()}`);
    byId('players-stamp') && (byId('players-stamp').textContent = `${data.players.length} PROFILES`);
  } catch (error) {
    byId('status-factorio').textContent = 'Unavailable';
    byId('status-updated').textContent = 'CONNECTION UNAVAILABLE';
  }
}
async function refreshWorld() {
  try {
    const response = await fetch(apiUrl('api/world'), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    const surfaces = Array.isArray(data.surfaces) ? data.surfaces : [];
    const players = Array.isArray(data.players) ? data.players : [];
    const available = Boolean(data.available);
    byId('world-tick').textContent = available ? Number(data.tick).toLocaleString() : 'Unavailable';
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
  }
}
async function restoreSave(source) {
  if (!window.confirm(`Restore ${source} over the configured save?`)) return;
  const response = await fetch(apiUrl('api/saves/restore'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source }) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Restore failed.');
  await refreshWorld();
}
function switchAppTab(tabName, refresh = true) {
  document.querySelectorAll('[data-app-tab]').forEach((tab) => tab.classList.toggle('active', tab.dataset.appTab === tabName));
  document.querySelectorAll('[data-app-view]').forEach((view) => view.classList.toggle('active', view.dataset.appView === tabName));
  if (!refresh) return;
  if (tabName === 'server' || tabName === 'players' || tabName === 'system' || tabName === 'logs') refreshStatus();
  if (tabName === 'world') { refreshStatus(); refreshWorld(); }
  if (tabName === 'catalog') { renderExploreTabs(); refreshExplore(); refreshCatalogMetadata(); }
}
document.querySelectorAll('[data-app-tab]').forEach((tab) => tab.addEventListener('click', () => switchAppTab(tab.dataset.appTab)));
document.querySelectorAll('[data-master-kind]').forEach((tab) => tab.addEventListener('click', () => selectMasterCatalogGroup(tab.dataset.masterKind)));
byId('explore-query')?.addEventListener('input', () => { exploreOffset = 0; refreshExplore(); });
byId('explore-previous')?.addEventListener('click', () => { exploreOffset = Math.max(0, exploreOffset - 48); refreshExplore(); });
byId('explore-next')?.addEventListener('click', () => { exploreOffset += 48; refreshExplore(); });
byId('status-refresh').addEventListener('click', refreshStatus);
byId('world-refresh').addEventListener('click', refreshWorld);
byId('logs-refresh').addEventListener('click', refreshStatus);
syncHomeAssistantTheme();
try {
  new MutationObserver(syncHomeAssistantTheme).observe(window.parent.document.documentElement, { attributes: true, attributeFilter: ['class', 'style'] });
} catch {
  // Direct access does not have a Home Assistant parent document.
}
refreshStatus();
refreshWorld();
refreshCatalogMetadata();
renderMasterCatalogGroups();
renderExploreTabs();
refreshExplore();
setInterval(refreshStatus, 10000);
setInterval(refreshWorld, 10000);
