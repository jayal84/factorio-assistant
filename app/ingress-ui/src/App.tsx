import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  callModRemote,
  catalogRecordLabel,
  dispatchAaiVehicle,
  dispatchLtnCommand,
  getCatalog,
  getCatalogEntry,
  getProductionPlan,
  getStatus,
  getTelemetry,
  getWorld,
} from './api';
import type { AppSnapshot, CatalogRecord, FactorioStatus, FactorioWorld, PageDefinition, PageKey, PageType, TelemetryEvent } from './types';

type WorldPlayer = Record<string, unknown> & { name?: string; connected?: boolean; surface?: string; deaths?: number };
type WorldSurface = Record<string, unknown> & { name?: string; pollution?: number; pinned_resources?: Array<Record<string, unknown>>; tracked_resources?: Array<Record<string, unknown>> };

type PageProps = {
  snapshot: AppSnapshot;
  activePage: PageDefinition;
  refreshAll: () => Promise<void>;
};

type PageRenderer = React.FC<PageProps>;

type PageGroup = { label: string; items: PageDefinition[] };

const PAGE_REGISTRY: Record<PageKey, PageDefinition> = {
  overview: { key: 'overview', label: 'Overview', subtitle: 'Live status, health, and the most important alerts.', group: 'Operations', type: 'dashboard' },
  world: { key: 'world', label: 'World', subtitle: 'Tick, research, players, surfaces, and active telemetry.', group: 'Operations', type: 'world' },
  resources: { key: 'resources', label: 'Resources', subtitle: 'Pinned resource sites and extraction telemetry.', group: 'Operations', type: 'resources' },
  logistics: { key: 'logistics', label: 'Logistics', subtitle: 'AAI vehicle dispatch and limited LTN helpers.', group: 'Operations', type: 'logistics' },
  browse: { key: 'browse', label: 'Browse', subtitle: 'Factorio catalog search with grouped filters and details.', group: 'Planning', type: 'browse' },
  production: { key: 'production', label: 'Production', subtitle: 'Build and inspect recipe plans from live catalog data.', group: 'Planning', type: 'production' },
  storage: { key: 'storage', label: 'Storage', subtitle: 'Saves, backups, restores, and recent telemetry.', group: 'Administration', type: 'storage' },
  system: { key: 'system', label: 'System', subtitle: 'Bridge, Factorio, and ingress service diagnostics.', group: 'Administration', type: 'system' },
};

const PAGE_GROUPS: PageGroup[] = [
  { label: 'Operations', items: [PAGE_REGISTRY.overview, PAGE_REGISTRY.world, PAGE_REGISTRY.resources, PAGE_REGISTRY.logistics] },
  { label: 'Planning', items: [PAGE_REGISTRY.browse, PAGE_REGISTRY.production] },
  { label: 'Administration', items: [PAGE_REGISTRY.storage, PAGE_REGISTRY.system] },
];

const PAGE_RENDERERS: Record<PageType, PageRenderer> = {
  dashboard: DashboardPage,
  world: WorldPage,
  resources: ResourcesPage,
  logistics: LogisticsPage,
  browse: BrowsePage,
  production: ProductionPage,
  storage: StoragePage,
  system: SystemPage,
};

const DEFAULT_PAGE: PageKey = 'overview';

function hashToPage(): PageKey {
  const value = window.location.hash.replace(/^#/, '') as PageKey;
  return value in PAGE_REGISTRY ? value : DEFAULT_PAGE;
}

function PageShell({ title, subtitle, actions, children }: { title: string; subtitle: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">FACTORIO ASSISTANT</p>
          <h1>{title}</h1>
          <p className="lede">{subtitle}</p>
        </div>
        <div className="page-actions">{actions}</div>
      </header>
      <div className="page-content">{children}</div>
    </section>
  );
}

function SectionCard({ title, tag, children, description }: { title: string; tag?: string; description?: string; children: React.ReactNode }) {
  return (
    <article className="card section-card">
      <div className="section-head">
        <div>
          <h2>{title}</h2>
          {description ? <p className="section-description">{description}</p> : null}
        </div>
        {tag ? <span className="tag">{tag}</span> : null}
      </div>
      {children}
    </article>
  );
}

function MetricCard({ label, value, detail }: { label: string; value: React.ReactNode; detail?: React.ReactNode }) {
  return (
    <article className="card metric-card">
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
      {detail ? <span className="metric-detail">{detail}</span> : null}
    </article>
  );
}

function DefinitionList({ items }: { items: Array<[string, React.ReactNode]> }) {
  return (
    <dl className="definition-list">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function CompactList({ items, empty }: { items: React.ReactNode[]; empty: string }) {
  if (!items.length) {
    return <p className="empty-state">{empty}</p>;
  }
  return <div className="compact-list">{items}</div>;
}

function formatNumber(value: unknown, digits = 0): string {
  const parsed = Number(value ?? 0);
  if (!Number.isFinite(parsed)) return '—';
  return parsed.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function formatPercent(value: unknown, digits = 1): string {
  const parsed = Number(value ?? 0);
  if (!Number.isFinite(parsed)) return '—';
  return `${(parsed * 100).toFixed(digits)}%`;
}

function formatTime(value: unknown): string {
  const seconds = Number(value ?? 0);
  if (!Number.isFinite(seconds) || seconds <= 0) return '—';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

function formatGameTime(value: unknown): string {
  const raw = Number(value ?? 0);
  return Number.isFinite(raw) ? raw.toLocaleString() : String(value ?? '—');
}

const PLANNER_DRAFT_KEY = 'factorio-planner-draft';

type PlannerDraft = {
  goal: string;
  items: Array<{ name: string; rate: number }>;
  knownRecipes: string[];
};

function normalizeRelationEntries(value: unknown): CatalogRecord[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => {
      if (!entry || typeof entry === 'string') return { name: String(entry ?? '') } as CatalogRecord;
      if (typeof entry === 'object') return entry as CatalogRecord;
      return null;
    })
    .filter((entry): entry is CatalogRecord => Boolean(entry?.name));
}

function relationKind(entry: CatalogRecord, fallback = ''): string {
  const explicit = String(entry.kind || entry.type || '').trim();
  if (explicit) return explicit;
  if (fallback === 'made_in' || fallback === 'used_in' || fallback === 'crafted_in' || fallback === 'unlocked_by') return 'recipe';
  if (fallback === 'prerequisites') return 'technology';
  return fallback;
}

function relationLabel(entry: CatalogRecord): string {
  return String(entry.localized_name || entry.name || entry.type || 'Unknown');
}

function relationAmount(entry: CatalogRecord): string {
  const amount = entry.amount ?? entry.amount_min ?? entry.amount_max;
  if (amount === null || amount === undefined || amount === '') return '';
  const parsed = Number(amount);
  return Number.isFinite(parsed) ? formatNumber(parsed, 2) : String(amount);
}

function readPlannerDraft(): PlannerDraft | null {
  try {
    const raw = window.localStorage.getItem(PLANNER_DRAFT_KEY);
    if (!raw) return null;
    window.localStorage.removeItem(PLANNER_DRAFT_KEY);
    const draft = JSON.parse(raw) as Partial<PlannerDraft>;
    if (!Array.isArray(draft.items) || !draft.items.length) return null;
    return {
      goal: String(draft.goal || ''),
      items: draft.items
        .map((item) => ({ name: String(item?.name || '').trim(), rate: Number(item?.rate || 0) }))
        .filter((item) => item.name),
      knownRecipes: Array.isArray(draft.knownRecipes) ? draft.knownRecipes.map((recipe) => String(recipe || '').trim()).filter(Boolean) : [],
    };
  } catch {
    return null;
  }
}

function writePlannerDraft(draft: PlannerDraft) {
  window.localStorage.setItem(PLANNER_DRAFT_KEY, JSON.stringify(draft));
}

function plannerTargetName(entry: CatalogRecord): string {
  if (entry.kind === 'recipe') {
    const firstResult = Array.isArray(entry.results) ? entry.results[0] as Record<string, unknown> | undefined : undefined;
    const recipeTarget = firstResult && typeof firstResult === 'object' ? String(firstResult.name || '') : '';
    if (recipeTarget) return recipeTarget;
  }
  return entry.name;
}

function plannerDraftForEntry(entry: CatalogRecord): PlannerDraft {
  const targetName = plannerTargetName(entry);
  return {
    goal: `Plan ${relationLabel(entry)}`,
    items: [{ name: targetName, rate: 60 }],
    knownRecipes: entry.kind === 'recipe' ? [entry.name] : [],
  };
}

function RelationList({ title, value, fallbackKind, empty, onOpen }: { title: string; value: unknown; fallbackKind: string; empty: string; onOpen: (entry: CatalogRecord) => void }) {
  const entries = normalizeRelationEntries(value);
  if (!entries.length) {
    return (
      <section className="detail-section">
        <h3>{title}</h3>
        <p className="empty-state">{empty}</p>
      </section>
    );
  }
  return (
    <section className="detail-section">
      <h3>{title}</h3>
      <div className="compact-list">
        {entries.map((entry) => {
          const kind = relationKind(entry, fallbackKind);
          const amount = relationAmount(entry);
          return (
            <div key={`${kind}-${entry.name}`} className="compact-row">
              <button className="inline-button" onClick={() => onOpen({ ...entry, kind })}>
                {relationLabel(entry)}
              </button>
              <span>{kind}{amount ? ` · ×${amount}` : ''}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function useFactorioSnapshot() {
  const [snapshot, setSnapshot] = useState<AppSnapshot>({ status: null, world: null, telemetry: [], catalogMeta: null, loading: true, error: null, refreshedAt: null });

  const refreshAll = useCallback(async () => {
    try {
      const [status, world, telemetry, catalogMeta] = await Promise.all([
        getStatus(),
        getWorld(),
        getTelemetry(50),
        getCatalog(new URLSearchParams({ limit: '1', offset: '0' })),
      ]);
      setSnapshot({
        status,
        world,
        telemetry: Array.isArray(telemetry.events) ? telemetry.events : [],
        catalogMeta,
        loading: false,
        error: null,
        refreshedAt: Date.now(),
      });
    } catch (error) {
      setSnapshot((current) => ({ ...current, loading: false, error: error instanceof Error ? error.message : 'Refresh failed.' }));
    }
  }, []);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      if (!active) return;
      await refreshAll();
    };
    void refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refreshAll]);

  return { snapshot, refreshAll };
}

function App() {
  const { snapshot, refreshAll } = useFactorioSnapshot();
  const [activePage, setActivePage] = useState<PageKey>(hashToPage());

  useEffect(() => {
    const onHashChange = () => setActivePage(hashToPage());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const page = PAGE_REGISTRY[activePage] || PAGE_REGISTRY.overview;
  const CurrentPage = PAGE_RENDERERS[page.type];
  const status = snapshot.status;
  const world = snapshot.world;
  const title = status?.factorio && typeof status.factorio === 'object' && 'name' in status.factorio ? String((status.factorio as Record<string, unknown>).name || 'Factorio Assistant') : 'Factorio Assistant';
  const bridgeOnline = Boolean(status?.bridge && typeof status.bridge === 'object' && (status.bridge as Record<string, unknown>).running);
  const factorioOnline = Boolean(status?.factorio && typeof status.factorio === 'object' && (status.factorio as Record<string, unknown>).running);
  const refreshedAt = snapshot.refreshedAt ? new Date(snapshot.refreshedAt).toLocaleTimeString() : 'Waiting';

  return (
    <div className="app-shell app-shell-compact">
      <main className="workspace">
        <header className="topbar">
          <div className="brand compact-brand">
            <div className="brand-mark">⚙</div>
            <div>
              <p className="eyebrow">FACTORIO OPERATIONS CONSOLE</p>
              <h2>{title}</h2>
              <p className="sidebar-subtitle">{bridgeOnline ? 'Bridge online' : 'Bridge unavailable'} · {factorioOnline ? 'Factorio online' : 'Factorio offline'}</p>
            </div>
          </div>
          <div className="topbar-statuses">
            <StatusChip label="Factorio" value={factorioOnline ? 'Online' : 'Offline'} tone={factorioOnline ? 'good' : 'bad'} />
            <StatusChip label="Bridge" value={bridgeOnline ? 'Connected' : 'Stopped'} tone={bridgeOnline ? 'good' : 'bad'} />
            <StatusChip label="Updated" value={refreshedAt} tone="neutral" />
          </div>
          <nav className="topbar-nav" aria-label="Console pages">
            {PAGE_GROUPS.map((group) => (
              <div key={group.label} className="topbar-nav-group">
                <span className="nav-group-label">{group.label}</span>
                <div className="topbar-nav-items">
                  {group.items.map((item) => (
                    <button
                      key={item.key}
                      className={`nav-item ${item.key === activePage ? 'active' : ''}`}
                      onClick={() => {
                        window.location.hash = item.key;
                        setActivePage(item.key);
                      }}
                    >
                      <span>
                        <strong>{item.label}</strong>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </nav>
          <button className="refresh-button" onClick={() => void refreshAll()}>
            Refresh all data
          </button>
        </header>
        <PageShell title={page.label} subtitle={page.subtitle} actions={<button className="ghost-button" onClick={() => void refreshAll()}>Refresh page data</button>}>
          {snapshot.error ? <div className="alert error">{snapshot.error}</div> : null}
          <CurrentPage snapshot={snapshot} activePage={page} refreshAll={refreshAll} />
        </PageShell>
      </main>
    </div>
  );
}

function StatusChip({ label, value, tone }: { label: string; value: string; tone: 'good' | 'bad' | 'neutral' }) {
  return (
    <div className={`status-chip ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DashboardPage({ snapshot, refreshAll }: PageProps) {
  const status = snapshot.status || {};
  const world = snapshot.world || {};
  const players = normalizePlayers(world.players || status.players || []);
  const connectedPlayers = players.filter((player) => player.connected);
  const visibleTelemetry = snapshot.telemetry.filter((event) => event.event !== 'state_snapshot');
  const recentEvents = visibleTelemetry.slice(-1).reverse();
  const storage = status.storage && typeof status.storage === 'object' ? status.storage : {};
  const diagnostics = status.diagnostics && typeof status.diagnostics === 'object' ? status.diagnostics : {};

  return (
    <div className="page-stack">
      <div className="metric-grid">
        <MetricCard label="Active players" value={formatNumber(world.players_online ?? connectedPlayers.length)} detail={`${players.length} known profiles`} />
        <MetricCard label="Game time" value={formatGameTime(world.game_time)} detail={`Day ${formatNumber(world.game_day)}`} />
        <MetricCard label="Research" value={String(world.research_localized_name || world.research || 'None')} detail={`${formatPercent(world.research_progress ?? 0)} complete`} />
        <MetricCard label="Events" value={formatNumber(snapshot.telemetry.length)} detail={`${recentEvents.length} shown`} />
      </div>

      <div className="two-column-grid">
        <SectionCard title="Server" tag={factorioTag(status)} description="Game process, bridge, and connection summary.">
          <DefinitionList
            items={[
              ['Factorio', factorioStatusLabel(status)],
              ['Bridge', bridgeStatusLabel(status)],
              ['Save file', String(storage.save_details && typeof storage.save_details === 'object' ? (storage.save_details as Record<string, unknown>).configured || '—' : '—')],
              ['RCON', String(status.connection && typeof status.connection === 'object' ? (status.connection as Record<string, unknown>).rcon_port || '—' : '—')],
            ]}
          />
        </SectionCard>
        <SectionCard title="Diagnostics" tag="Health" description="Current bridge and system health.">
          <DefinitionList
            items={[
              ['CPU', `${formatNumber(diagnostics.cpu_usage, 1)}%`],
              ['Memory', `${formatNumber(diagnostics.mem_usage, 1)}%`],
              ['Uptime', `${formatTime(diagnostics.uptime)}`],
              ['Watchdog', String(status.watchdog && typeof status.watchdog === 'object' ? (status.watchdog as Record<string, unknown>).healthy ? 'Healthy' : 'Problem' : '—')],
            ]}
          />
        </SectionCard>
      </div>

      <div className="two-column-grid">
        <SectionCard title="World snapshot" tag="Live" description="World totals and the latest state snapshot.">
          <DefinitionList
            items={[
              ['Tick', formatNumber(world.tick)],
              ['Speed', formatNumber(world.speed, 2)],
              ['Surface count', formatNumber(world.surface_count)],
              ['Rockets launched', formatNumber(world.rockets_launched)],
            ]}
          />
          <CompactList
            empty="No surface telemetry reported yet."
            items={normalizeSurfaces(world.surfaces).slice(0, 3).map((surface) => (
              <div key={String(surface.name || Math.random())} className="compact-row">
                <span>{String(surface.name || 'Unknown surface')}</span>
                <strong>{formatNumber(surface.pollution, 1)} pollution</strong>
              </div>
            ))}
          />
        </SectionCard>
        <SectionCard title="Recent events" tag={`${recentEvents.length} shown`} description="The latest structured telemetry from the mod.">
          <CompactList
            empty="No telemetry events yet."
            items={recentEvents.map((event) => (
              <div key={`${String(event.event)}-${String(event.tick || event.bridge_received_at || '')}`} className="event-row">
                <strong>{String(event.event)}</strong>
                <span>{String(event.bridge_received_at || `tick ${event.tick ?? '—'}`)}</span>
                <pre>{JSON.stringify(event, null, 2)}</pre>
              </div>
            ))}
          />
        </SectionCard>
      </div>

      <div className="two-column-grid">
        <SectionCard title="Players" tag={`${players.length} known`} description="Merged into the world view so player state stays with live telemetry.">
          <div className="player-grid">
            {players
              .slice()
              .sort((left, right) => Number(Boolean(right.connected)) - Number(Boolean(left.connected)) || String(left.name || '').localeCompare(String(right.name || '')))
              .map((player) => (
                <div key={String(player.name || Math.random())} className={`player-card ${player.connected ? 'online' : 'offline'}`}>
                  <strong>{String(player.name || 'Unknown')}</strong>
                  <span>{player.connected ? 'Connected' : 'Offline'}</span>
                  <small>{String(player.surface || 'Unknown surface')}</small>
                  <small>{formatNumber(player.deaths)} deaths</small>
                </div>
              ))}
          </div>
        </SectionCard>
        <SectionCard title="Storage summary" tag="Quick view" description="The detailed backup tools live in the Storage page.">
          <DefinitionList
            items={[
              ['Saves', formatNumber(storage.save_count)],
              ['Mods', formatNumber(storage.mod_count)],
              ['Configured save', String(storage.save_details && typeof storage.save_details === 'object' ? (storage.save_details as Record<string, unknown>).configured || '—' : '—')],
              ['Directory', String(storage.save_details && typeof storage.save_details === 'object' ? (storage.save_details as Record<string, unknown>).directory || '—' : '—')],
            ]}
          />
          <button className="inline-button" onClick={() => void refreshAll()}>Update overview</button>
        </SectionCard>
      </div>
    </div>
  );
}

function WorldPage({ snapshot }: PageProps) {
  const world = snapshot.world || {};
  const players = normalizePlayers(world.players || snapshot.status?.players || []);
  const connectedPlayers = players.filter((player) => player.connected).sort((left, right) => String(left.name || '').localeCompare(String(right.name || '')));
  const offlinePlayers = players.filter((player) => !player.connected).sort((left, right) => String(left.name || '').localeCompare(String(right.name || '')));
  const surfaces = normalizeSurfaces(world.surfaces);

  return (
    <div className="page-stack">
      <div className="metric-grid">
        <MetricCard label="Tick" value={formatNumber(world.tick)} detail={`Speed ${formatNumber(world.speed, 2)}`} />
        <MetricCard label="Game day" value={formatNumber(world.game_day)} detail={formatGameTime(world.game_time)} />
        <MetricCard label="Research" value={String(world.research_localized_name || world.research || 'None')} detail={`${formatPercent(world.research_progress ?? 0)} complete`} />
        <MetricCard label="Surfaces" value={formatNumber(world.surface_count ?? surfaces.length)} detail={String(world.surface_names || 'No surface list')} />
      </div>

      <div className="two-column-grid">
        <SectionCard title="Players online" tag={formatNumber(connectedPlayers.length)} description="Connected players stay grouped above offline profiles.">
          <div className="player-grid">
            {connectedPlayers.map((player) => (
              <div key={String(player.name || Math.random())} className="player-card online">
                <strong>{String(player.name || 'Unknown')}</strong>
                <span>{String(player.surface || 'Unknown surface')}</span>
                <small>{formatNumber(player.deaths)} deaths</small>
                <small>{String(player.idle ? 'Idle' : 'Active')}</small>
              </div>
            ))}
          </div>
          <h3 className="subheading">Offline profiles</h3>
          <div className="player-grid">
            {offlinePlayers.map((player) => (
              <div key={String(player.name || Math.random())} className="player-card offline">
                <strong>{String(player.name || 'Unknown')}</strong>
                <span>{String(player.surface || 'Unknown surface')}</span>
                <small>{formatNumber(player.deaths)} deaths</small>
              </div>
            ))}
          </div>
        </SectionCard>
        <SectionCard title="Surface summary" tag={`${surfaces.length} surfaces`} description="Pollution and surface-level resource totals.">
          <CompactList
            empty="No surface telemetry reported yet."
            items={surfaces
              .slice()
              .sort((left, right) => String(left.name || '').localeCompare(String(right.name || '')))
              .map((surface) => (
                <div key={String(surface.name || Math.random())} className="compact-row">
                  <span>{String(surface.name || 'Unknown surface')}</span>
                  <strong>{formatNumber(surface.pollution, 1)} pollution</strong>
                </div>
              ))}
          />
        </SectionCard>
      </div>

    </div>
  );
}

function ResourcesPage({ snapshot }: PageProps) {
  const world = snapshot.world || {};
  const resourceMonitor = normalizeRecord(world.resource_monitor);
  const hasResourceMonitor = Array.isArray(resourceMonitor.surfaces) || Object.keys(resourceMonitor).length > 0;
  const monitoredSurfaces = normalizeSurfaces(resourceMonitor.surfaces);
  const surfaces = hasResourceMonitor ? monitoredSurfaces : normalizeSurfaces(world.surfaces);
  const resources = surfaces.flatMap((surface) => normalizePinnedResources(surface.tracked_resources || surface.pinned_resources).map((resource) => ({ ...resource, surface: String(surface.name || 'Unknown') })));
  const sortedResources = resources.slice().sort((left, right) => Number(right.amount || 0) - Number(left.amount || 0));

  return (
    <div className="page-stack">
      <div className="metric-grid metric-grid-fluid">
        <MetricCard label="Sites" value={formatNumber(resources.length)} detail={`${surfaces.length} surfaces`} />
        <MetricCard label="Largest site" value={String(sortedResources[0]?.name || '—')} detail={resources.length ? `${formatNumber(sortedResources[0]?.amount)} remaining` : 'No pinned resources'} />
        <MetricCard label="Surfaces" value={formatNumber(surfaces.length)} detail="Tracked across the map" />
        <MetricCard label="Telemetry" value={String(world.tick ? `Tick ${formatNumber(world.tick)}` : 'Waiting')} detail={String(world.game_time || '—')} />
      </div>

      <SectionCard title="Pinned resources" tag={`${resources.length} sites`} description="Grouped across all surfaces with the most important numbers first.">
        <div className="resource-grid resource-grid-dense">
          {sortedResources.map((resource) => (
            <article key={`${String(resource.surface)}-${String(resource.id || resource.name)}`} className="resource-card resource-card-dense">
              <div className="section-head tight">
                <div>
                  <p className="eyebrow">{String(resource.surface)}</p>
                  <h3>{String(resource.name || resource.type_name || resource.type || 'Resource')}</h3>
                </div>
                <span className="tag">{String(resource.type_name || resource.type || 'Resource')}</span>
              </div>
              <DefinitionList
                items={[
                  ['Remaining', formatNumber(resource.amount)],
                  ['Rate', `${formatNumber(resource.rate, 2)}/s`],
                  ['Remaining %', `${formatPercent(resource.percent ?? 0)}`],
                  ['Until depleted', resource.estimated_depletion == null ? 'No estimate' : formatTime(Number(resource.estimated_depletion || 0) / 60)],
                ]}
              />
            </article>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}

function LogisticsPage({ snapshot, refreshAll }: PageProps) {
  const world = snapshot.world || {};
  const vehicleCounts = normalizeRecord(world.vehicle_counts);
  const vehicleKinds = normalizeRecord(vehicleCounts.kinds);
  const vehicleSurfaces = normalizeRecord(vehicleCounts.surfaces);
  const ltn = normalizeRecord(world.ltn);
  const ltnTrains = Array.isArray(ltn.trains) ? ltn.trains : [];

  const [aaiAction, setAaiAction] = useState('follow_player');
  const [aaiUnitKind, setAaiUnitKind] = useState('any');
  const [aaiPlayer, setAaiPlayer] = useState('');
  const [aaiSurface, setAaiSurface] = useState('');
  const [aaiCenterX, setAaiCenterX] = useState('0');
  const [aaiCenterY, setAaiCenterY] = useState('0');
  const [aaiAreaSize, setAaiAreaSize] = useState('32');
  const [aaiStatus, setAaiStatus] = useState('Ready');
  const [ltnAction, setLtnAction] = useState('clear_all_surface_connections');
  const [ltnName, setLtnName] = useState('');
  const [ltnTrainId, setLtnTrainId] = useState('0');
  const [ltnOldTrainId, setLtnOldTrainId] = useState('0');
  const [ltnNewTrainId, setLtnNewTrainId] = useState('0');
  const [ltnScheduleIndex, setLtnScheduleIndex] = useState('0');
  const [ltnStatus, setLtnStatus] = useState('Ready');

  const runAai = async () => {
    setAaiStatus('Sending...');
    try {
      const result = await dispatchAaiVehicle({
        action: aaiAction,
        unit_kind: aaiUnitKind,
        player: aaiPlayer,
        surface: aaiSurface,
        center_x: Number(aaiCenterX || 0),
        center_y: Number(aaiCenterY || 0),
        area_size: Number(aaiAreaSize || 32),
      });
      setAaiStatus(`OK · ${String(normalizeRecord(result).action || 'dispatched')}`);
      await refreshAll();
    } catch (error) {
      setAaiStatus(error instanceof Error ? error.message : 'Dispatch failed');
    }
  };

  const runLtn = async () => {
    setLtnStatus('Sending...');
    try {
      const result = await dispatchLtnCommand({
        action: ltnAction,
        name: ltnName,
        train_id: Number(ltnTrainId || 0),
        old_train_id: Number(ltnOldTrainId || 0),
        new_train_id: Number(ltnNewTrainId || 0),
        schedule_index: Number(ltnScheduleIndex || 0),
      });
      setLtnStatus(`OK · ${String(normalizeRecord(result).action || 'completed')}`);
      await refreshAll();
    } catch (error) {
      setLtnStatus(error instanceof Error ? error.message : 'Command failed');
    }
  };

  return (
    <div className="page-stack">
      <div className="metric-grid">
        <MetricCard label="AAI vehicles" value={formatNumber(vehicleCounts.matched)} detail={`${formatNumber(vehicleCounts.total)} total`} />
        <MetricCard label="LTN trains" value={formatNumber(ltn.train_count)} detail={`${formatNumber(ltn.scheduled_train_count)} scheduled`} />
        <MetricCard label="Manual trains" value={formatNumber(ltn.manual_train_count)} detail={String(ltn.installed ? 'LTN installed' : 'LTN absent')} />
        <MetricCard label="AAI kinds" value={formatNumber(Object.keys(vehicleKinds).length)} detail={`${formatNumber(Object.keys(vehicleSurfaces).length)} surfaces`} />
      </div>

      <div className="two-column-grid">
        <SectionCard title="AAI fleet telemetry" tag="Live counts" description="Fleet counts are sorted by vehicle family and surface.">
          <DefinitionList
            items={[
              ['All vehicles', formatNumber(vehicleCounts.total)],
              ['AAI vehicles', formatNumber(vehicleCounts.matched)],
              ['Miners', formatNumber(vehicleKinds.miner)],
              ['Haulers', formatNumber(vehicleKinds.hauler)],
              ['Wardens', formatNumber(vehicleKinds.warden)],
              ['Chaingunners', formatNumber(vehicleKinds.chaingunner)],
              ['Flame tanks', formatNumber(vehicleKinds.flame_tank)],
              ['Ironclads', formatNumber(vehicleKinds.ironclad)],
              ['Laser tanks', formatNumber(vehicleKinds.laser_tank)],
            ]}
          />
          <CompactList
            empty="No surface telemetry reported yet."
            items={Object.entries(vehicleSurfaces)
              .sort(([left], [right]) => left.localeCompare(right))
              .map(([surface, summary]) => (
                <div key={surface} className="compact-row">
                  <span>{surface}</span>
                  <strong>{formatNumber(normalizeRecord(summary).matched)}</strong>
                </div>
              ))}
          />
        </SectionCard>
        <SectionCard title="Dispatch AAI vehicle" tag={aaiStatus} description="Use the current bridge command surface without the old shell layout.">
          <FormGrid>
            <SelectField label="Action" value={aaiAction} onChange={setAaiAction} options={['follow_player', 'go_to_position', 'mine_area']} />
            <SelectField label="Vehicle kind" value={aaiUnitKind} onChange={setAaiUnitKind} options={['any', 'miner', 'hauler', 'warden', 'chaingunner', 'flame_tank', 'flame_tumbler', 'ironclad', 'laser_tank']} />
            <TextField label="Player" value={aaiPlayer} onChange={setAaiPlayer} placeholder="Player name to follow" />
            <TextField label="Surface" value={aaiSurface} onChange={setAaiSurface} placeholder="nauvis" />
            <TextField label="X" value={aaiCenterX} onChange={setAaiCenterX} type="number" />
            <TextField label="Y" value={aaiCenterY} onChange={setAaiCenterY} type="number" />
            <TextField label="Area size" value={aaiAreaSize} onChange={setAaiAreaSize} type="number" />
          </FormGrid>
          <button className="primary-button" onClick={() => void runAai()}>Send vehicle</button>
        </SectionCard>
      </div>

      <div className="two-column-grid">
        <SectionCard title="LTN control" tag={ltnStatus} description="Limited helpers are exposed from the bridge and grouped here with the train snapshot.">
          <FormGrid>
            <SelectField label="Action" value={ltnAction} onChange={setLtnAction} options={['clear_all_surface_connections', 'exclude_from_fuel_schedule', 'get_or_create_next_temp_stop', 'get_next_logistic_stop', 'reassign_delivery']} />
            <TextField label="Locomotive or prototype name" value={ltnName} onChange={setLtnName} placeholder="optional name for fuel exclusion" />
            <TextField label="Train id" value={ltnTrainId} onChange={setLtnTrainId} type="number" />
            <TextField label="Old train id" value={ltnOldTrainId} onChange={setLtnOldTrainId} type="number" />
            <TextField label="New train id" value={ltnNewTrainId} onChange={setLtnNewTrainId} type="number" />
            <TextField label="Schedule index" value={ltnScheduleIndex} onChange={setLtnScheduleIndex} type="number" />
          </FormGrid>
          <button className="primary-button" onClick={() => void runLtn()}>Run LTN action</button>
        </SectionCard>
        <SectionCard title="Train snapshot" tag={`${formatNumber(ltnTrains.length)} trains`} description="Direct read-only discovery so the UI can stay honest about what LTN reports.">
          <div className="train-list">
            {ltnTrains.map((train: Record<string, unknown>) => (
              <article key={String(train.id || Math.random())} className="train-card">
                <strong>Train {formatNumber(train.id)}</strong>
                <span>{String(train.surface || 'Unknown surface')}</span>
                <small>{String(train.state || 'unknown')}</small>
                <small>{String(train.manual_mode ? 'Manual' : 'Automatic')}</small>
              </article>
            ))}
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

function BrowsePage({ snapshot }: PageProps) {
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('item');
  const [results, setResults] = useState<CatalogRecord[]>([]);
  const [selected, setSelected] = useState<CatalogRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [meta, setMeta] = useState('Ready');

  const search = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ query, kind, limit: '32', offset: '0' });
      const response = await getCatalog(params);
      const nextResults = Array.isArray(response.results) ? (response.results as CatalogRecord[]) : [];
      setResults(nextResults);
      setSelected(nextResults[0] || null);
      setMeta(`${formatNumber(response.total)} results · ${String(response.factorio_version || 'unknown')}`);
    } catch (error) {
      setMeta(error instanceof Error ? error.message : 'Catalog unavailable');
    } finally {
      setLoading(false);
    }
  };

  const openEntry = async (entry: CatalogRecord) => {
    try {
      const response = await getCatalogEntry(entry.name, entry.kind || '');
      const result = normalizeRecord(response.result);
      setSelected(result as CatalogRecord);
    } catch (error) {
      setMeta(error instanceof Error ? error.message : 'Catalog entry unavailable');
    }
  };

  const addSelectedToPlanner = () => {
    if (!selected) return;
    writePlannerDraft(plannerDraftForEntry(selected));
    window.location.hash = 'production';
  };

  const detailBody = selected ? (
    <div className="detail-panel">
      <div className="detail-hero">
        <div>
          <h3>{catalogRecordLabel(selected)}</h3>
          <p className="helper-text">{String(selected.localized_description || 'No description available.')}</p>
        </div>
      </div>
      <DefinitionList
        items={[
          ['Name', selected.name],
          ['Kind', String(selected.kind || selected.type || 'unknown')],
          ['Category', String(selected.category || '—')],
          ['Energy', String(selected.energy_required || '—')],
        ]}
      />
      {(selected.kind === 'item' || selected.kind === 'fluid') ? (
        <>
          <RelationList title="How to make it" value={selected.made_in} fallbackKind="made_in" empty="No recipe data linked yet." onOpen={(entry) => void openEntry(entry)} />
          <RelationList title="What uses it" value={selected.used_in} fallbackKind="used_in" empty="No indexed recipes use this yet." onOpen={(entry) => void openEntry(entry)} />
        </>
      ) : null}
      {selected.kind === 'recipe' ? (
        <>
          <RelationList title="Ingredients" value={selected.ingredients} fallbackKind="ingredient" empty="No ingredient data available." onOpen={(entry) => void openEntry(entry)} />
          <RelationList title="Produces" value={selected.results || selected.products} fallbackKind="result" empty="No result data available." onOpen={(entry) => void openEntry(entry)} />
          <RelationList title="Crafted in" value={selected.crafted_in} fallbackKind="crafted_in" empty="No machine data available." onOpen={(entry) => void openEntry(entry)} />
          <RelationList title="Unlocked by" value={selected.unlocked_by} fallbackKind="unlocked_by" empty="No technology unlocks linked." onOpen={(entry) => void openEntry(entry)} />
        </>
      ) : null}
      <details className="json-block" open>
        <summary>Technical data</summary>
        <pre>{JSON.stringify(selected, null, 2)}</pre>
      </details>
      {(selected.kind === 'item' || selected.kind === 'fluid' || selected.kind === 'recipe') ? (
        <button className="primary-button" onClick={addSelectedToPlanner}>✓ Add to production planner</button>
      ) : null}
    </div>
  ) : null;

  useEffect(() => {
    void search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="page-stack">
      <div className="two-column-grid browse-layout">
        <SectionCard title="Catalog search" tag={meta} description="Query names, descriptions, and internal IDs without reusing the old layout.">
          <div className="search-row">
            <TextField label="Search" value={query} onChange={setQuery} placeholder="iron-plate, assembling-machine-2, or any data" />
            <SelectField label="Kind" value={kind} onChange={setKind} options={['item', 'fluid', 'recipe', 'technology', 'entity', 'module', 'equipment', 'resource', 'signal', 'tile', 'setting']} />
          </div>
          <button className="primary-button" onClick={() => void search()}>{loading ? 'Searching...' : 'Search catalog'}</button>
          <div className="result-list">
            {results.map((entry) => (
              <button key={`${entry.kind || 'entry'}-${entry.name}`} className={`result-row ${selected?.name === entry.name ? 'active' : ''}`} onClick={() => void openEntry(entry)}>
                <strong>{catalogRecordLabel(entry)}</strong>
                <span>{String(entry.kind || entry.type || 'unknown')}</span>
              </button>
            ))}
          </div>
        </SectionCard>
        <SectionCard title="Catalog detail" tag={selected ? selected.kind || 'entry' : '—'} description="The right side is dedicated to details so the browser feels like a workspace, not a stacked list.">
          {detailBody || <p className="empty-state">Select an entry to inspect its data.</p>}
        </SectionCard>
      </div>
      <div className="card">
        <p className="helper-text">Open a result, then use the detail pane to inspect the raw export if you need to wire production or planning controls around it.</p>
      </div>
    </div>
  );
}

function ProductionPage({ snapshot }: PageProps) {
  const [goal, setGoal] = useState('Make 60 iron plates per minute');
  const [itemsText, setItemsText] = useState('[{"name":"iron-plate","rate":60}]');
  const [knownRecipesText, setKnownRecipesText] = useState('[]');
  const [output, setOutput] = useState<Record<string, unknown> | null>(null);
  const [status, setStatus] = useState('Ready');

  useEffect(() => {
    const draft = readPlannerDraft();
    if (!draft) return;
    setGoal(draft.goal || '');
    setItemsText(JSON.stringify(draft.items, null, 2));
    setKnownRecipesText(JSON.stringify(draft.knownRecipes, null, 2));
    setStatus('Draft loaded');
  }, []);

  const plan = async () => {
    setStatus('Planning...');
    try {
      const items = JSON.parse(itemsText) as Array<{ name: string; rate: number }>;
      const knownRecipes = JSON.parse(knownRecipesText) as string[];
      const response = await getProductionPlan(items, knownRecipes);
      setOutput(response);
      setStatus(String(response.status || 'Ready'));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Planning failed');
    }
  };

  return (
    <div className="page-stack">
      <div className="two-column-grid">
        <SectionCard title="Plan input" tag={status} description="Simple form inputs with JSON payloads when needed.">
          <FormGrid>
            <TextField label="Goal" value={goal} onChange={setGoal} placeholder="What should the factory produce?" />
            <TextAreaField label="Items" value={itemsText} onChange={setItemsText} />
            <TextAreaField label="Known recipes" value={knownRecipesText} onChange={setKnownRecipesText} />
          </FormGrid>
          <button className="primary-button" onClick={() => void plan()}>Plan production</button>
        </SectionCard>
        <SectionCard title="Plan output" tag={output ? String(output.detail || 'Live') : 'Idle'} description="The result is shown as grouped output rather than a wall of text.">
          {output ? <pre className="json-output">{JSON.stringify(output, null, 2)}</pre> : <p className="empty-state">Run a plan to see the chain and machine breakdown.</p>}
          <p className="helper-text">Goal: {goal}</p>
        </SectionCard>
      </div>
      <SectionCard title="Current telemetry" tag="Context" description="Production planning can inspect the current world snapshot while you work.">
        <DefinitionList
          items={[
            ['Research', String(snapshot.world?.research || 'None')],
            ['Technologies', `${formatNumber(snapshot.world?.technologies_researched)} / ${formatNumber(snapshot.world?.technologies_total)}`],
            ['Players online', formatNumber(snapshot.world?.players_online)],
            ['Surfaces', formatNumber(snapshot.world?.surface_count)],
          ]}
        />
      </SectionCard>
    </div>
  );
}

function StoragePage({ snapshot, refreshAll }: PageProps) {
  const status = snapshot.status || {};
  const storage = status.storage && typeof status.storage === 'object' ? status.storage as Record<string, unknown> : {};
  const saveDetails = storage.save_details && typeof storage.save_details === 'object' ? storage.save_details as Record<string, unknown> : {};
  const files = Array.isArray(saveDetails.files) ? saveDetails.files as Array<Record<string, unknown>> : [];
  const autosaves = files.filter((file) => Boolean(file.autosave));
  const backups = files.filter((file) => Boolean(file.backup));
  const saves = files.filter((file) => !file.autosave && !file.backup);
  const visibleTelemetry = snapshot.telemetry.filter((event) => event.event !== 'state_snapshot');

  return (
    <div className="page-stack">
      <div className="metric-grid">
        <MetricCard label="Files" value={formatNumber(files.length)} detail={`${formatNumber(autosaves.length)} autosaves`} />
        <MetricCard label="Backups" value={formatNumber(backups.length)} detail={`${formatNumber(saves.length)} saves`} />
        <MetricCard label="Configured save" value={String(saveDetails.configured || '—')} detail={String(saveDetails.directory || '—')} />
        <MetricCard label="Retention" value={String(status.restore && typeof status.restore === 'object' ? (status.restore as Record<string, unknown>).state || 'ready' : 'ready')} detail={String(saveDetails.backup_max_saves || 14)} />
      </div>

      <div className="three-column-grid">
        <SectionCard title="Save summary" tag={`${formatNumber(files.length)} files`} description="Backup controls stay grouped here instead of in the main shell.">
          <DefinitionList
            items={[
              ['Directory', String(saveDetails.directory || '—')],
              ['Backup mode', String(saveDetails.backup_mode || 'interval')],
              ['Interval', `${formatNumber(saveDetails.backup_interval_hours || 12)} hours`],
              ['Max saves', formatNumber(saveDetails.backup_max_saves || 14)],
            ]}
          />
          <button className="inline-button" onClick={() => void refreshAll()}>Refresh save data</button>
        </SectionCard>
        <SectionCard title="Autosaves" tag={formatNumber(autosaves.length)} description="Internal autosaves are shown separately so they are easy to scan.">
          <CompactList
            empty="No autosaves found."
            items={autosaves.map((file) => (
              <div key={String(file.name || Math.random())} className="file-row">
                <span>{String(file.name || 'Autosave')}</span>
                <strong>{formatFileSize(file.size)}</strong>
              </div>
            ))}
          />
        </SectionCard>
        <SectionCard title="Recent telemetry" tag={`${formatNumber(visibleTelemetry.length)} events`} description="The storage view still shows recent events, but the top-level layout is now cleaner.">
          <CompactList
            empty="No telemetry events yet."
            items={visibleTelemetry.slice(-8).reverse().map((event) => (
              <div key={`${String(event.event)}-${String(event.tick || '')}`} className="event-row short">
                <strong>{String(event.event)}</strong>
                <span>{String(event.bridge_received_at || `tick ${event.tick ?? '—'}`)}</span>
              </div>
            ))}
          />
        </SectionCard>
      </div>
      <SectionCard title="World files" tag="Group by type" description="Configured save, backups, and autosaves are grouped into the categories that make the most sense.">
        <div className="file-group-grid">
          <FileGroup title="Configured save" items={saves.filter((file) => String(file.name || '') === String(saveDetails.configured || ''))} />
          <FileGroup title="Backups" items={backups} />
          <FileGroup title="Autosaves" items={autosaves} />
        </div>
      </SectionCard>
    </div>
  );
}

function SystemPage({ snapshot }: PageProps) {
  const status = snapshot.status || {};
  const factorio = status.factorio && typeof status.factorio === 'object' ? status.factorio as Record<string, unknown> : {};
  const bridge = status.bridge && typeof status.bridge === 'object' ? status.bridge as Record<string, unknown> : {};
  const processes = status.processes && typeof status.processes === 'object' ? status.processes as Record<string, unknown> : {};
  const diagnostics = status.diagnostics && typeof status.diagnostics === 'object' ? status.diagnostics as Record<string, unknown> : {};
  const restore = status.restore && typeof status.restore === 'object' ? status.restore as Record<string, unknown> : {};
  const connection = status.connection && typeof status.connection === 'object' ? status.connection as Record<string, unknown> : {};

  return (
    <div className="page-stack">
      <div className="metric-grid">
        <MetricCard label="Factorio" value={String(factorio.running ? 'Online' : 'Offline')} detail={`v${String(factorio.version || '—')}`} />
        <MetricCard label="Bridge" value={String(bridge.running ? 'Connected' : 'Stopped')} detail={String(bridge.rcon_password_present ? 'RCON ready' : 'Waiting for credentials')} />
        <MetricCard label="Web" value={String(processes.web ? 'Running' : 'Stopped')} detail={String(processes.factorio ? 'Factorio online' : 'Factorio offline')} />
        <MetricCard label="Restore" value={String(restore.state || 'ready')} detail={String(restore.message || 'No active restore')} />
      </div>

      <div className="two-column-grid">
        <SectionCard title="Connection" tag={String(connection.ip || '—')} description="Ingress host, ports, and runtime connection details.">
          <DefinitionList
            items={[
              ['Hostname', String(connection.hostname || '—')],
              ['IP address', String(connection.ip || '—')],
              ['Game port', String(connection.game_port || '—')],
              ['RCON port', String(connection.rcon_port || '—')],
            ]}
          />
        </SectionCard>
        <SectionCard title="Diagnostics" tag="Runtime" description="Process and bridge health in one grouped view.">
          <DefinitionList
            items={[
              ['CPU usage', `${formatNumber(diagnostics.cpu_usage, 1)}%`],
              ['Memory usage', `${formatNumber(diagnostics.mem_usage, 1)}%`],
              ['Uptime', `${formatTime(diagnostics.uptime)}`],
              ['Watchdog checked', String(status.watchdog && typeof status.watchdog === 'object' ? (status.watchdog as Record<string, unknown>).checked_at || '—' : '—')],
            ]}
          />
        </SectionCard>
      </div>

      <SectionCard title="Persistent data" tag="Grouped" description="Storage and logs stay visible here as supporting information, not as the whole interface.">
        <div className="file-group-grid">
          <FileGroup title="Factorio files" items={Array.isArray(status.storage && typeof status.storage === 'object' ? (status.storage as Record<string, unknown>).saves : []) ? (status.storage as Record<string, unknown>).saves as Array<Record<string, unknown>> : []} />
          <FileGroup title="Installed mods" items={Array.isArray(status.storage && typeof status.storage === 'object' ? (status.storage as Record<string, unknown>).mods : []) ? (status.storage as Record<string, unknown>).mods as Array<Record<string, unknown>> : []} />
        </div>
      </SectionCard>
    </div>
  );
}

function FileGroup({ title, items }: { title: string; items: Array<Record<string, unknown>> }) {
  const sorted = items.slice().sort((left, right) => String(left.name || left.title || '').localeCompare(String(right.name || right.title || '')));
  return (
    <article className="sub-card">
      <div className="section-head tight">
        <h3>{title}</h3>
        <span className="tag">{formatNumber(sorted.length)}</span>
      </div>
      <CompactList
        empty={`No ${title.toLowerCase()} found.`}
        items={sorted.map((item) => (
          <div key={String(item.name || item.title || Math.random())} className="file-row">
            <span>{String(item.name || item.title || 'Unknown')}</span>
            <strong>{formatFileSize(item.size)}</strong>
          </div>
        ))}
      />
    </article>
  );
}

function FormGrid({ children }: { children: React.ReactNode }) {
  return <div className="form-grid">{children}</div>;
}

function TextField({ label, value, onChange, placeholder = '', type = 'text' }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type={type} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function TextAreaField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="field field-wide">
      <span>{label}</span>
      <textarea value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function SelectField({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: string[] }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    </label>
  );
}

function factorioTag(status: FactorioStatus | null): string {
  if (!status) return 'Loading';
  return String(status.factorio && typeof status.factorio === 'object' ? (status.factorio as Record<string, unknown>).running ? 'Online' : 'Offline' : 'Unknown');
}

function factorioStatusLabel(status: FactorioStatus | null): string {
  if (!status?.factorio || typeof status.factorio !== 'object') return 'Unknown';
  return String((status.factorio as Record<string, unknown>).running ? 'Online' : 'Offline');
}

function bridgeStatusLabel(status: FactorioStatus | null): string {
  if (!status?.bridge || typeof status.bridge !== 'object') return 'Unknown';
  return String((status.bridge as Record<string, unknown>).running ? 'Connected' : 'Stopped');
}

function formatFileSize(value: unknown): string {
  const bytes = Number(value ?? 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function normalizeRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function normalizePlayers(value: unknown): WorldPlayer[] {
  if (Array.isArray(value)) {
    return value.filter((entry): entry is WorldPlayer => Boolean(entry && typeof entry === 'object'));
  }
  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).map(([name, details]) => ({ name, ...(details as Record<string, unknown>) }));
  }
  return [];
}

function normalizeSurfaces(value: unknown): WorldSurface[] {
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is WorldSurface => Boolean(entry && typeof entry === 'object'));
}

function normalizePinnedResources(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is Record<string, unknown> => Boolean(entry && typeof entry === 'object'));
}

export default App;
