export type PageKey = 'overview' | 'world' | 'resources' | 'logistics' | 'browse' | 'production' | 'storage' | 'system';
export type PageType = 'dashboard' | 'world' | 'resources' | 'logistics' | 'browse' | 'production' | 'storage' | 'system';

export interface FactorioStatus {
  factorio?: Record<string, unknown>;
  bridge?: Record<string, unknown>;
  storage?: Record<string, unknown>;
  players?: Array<Record<string, unknown>>;
  log?: string[];
  processes?: Record<string, unknown>;
  watchdog?: Record<string, unknown>;
  diagnostics?: Record<string, unknown>;
  restore?: Record<string, unknown>;
  connection?: Record<string, unknown>;
  generated_at?: number;
}

export interface FactorioWorld {
  available?: boolean;
  tick?: number;
  speed?: number;
  players_online?: number;
  research?: string;
  research_localized_name?: string;
  research_progress?: number;
  research_queue?: string[] | Record<string, unknown>;
  technologies_researched?: number;
  technologies_total?: number;
  rockets_launched?: number;
  evolution_factor?: number;
  evolution_progress?: number;
  game_day?: number;
  game_time?: string | number;
  surface_count?: number;
  surface_names?: string;
  daytime?: number;
  day_night_cycle?: boolean;
  daylight?: boolean;
  vehicle_counts?: Record<string, unknown>;
  ltn?: Record<string, unknown>;
  surfaces?: Array<Record<string, unknown>>;
  resource_monitor?: Record<string, unknown>;
  players?: Record<string, Record<string, unknown>> | Array<Record<string, unknown>>;
  combinators?: Array<Record<string, unknown>>;
  current_research?: string;
  current_research_localized_name?: string;
  current_research_progress?: number;
  error?: string;
}

export interface TelemetryEvent {
  event: string;
  tick?: number;
  bridge_received_at?: string;
  player?: string;
  message?: string;
  surface?: string;
  technology?: string;
  entity?: string;
  [key: string]: unknown;
}

export interface CatalogRecord {
  name: string;
  kind?: string;
  type?: string;
  localized_name?: string;
  localized_description?: string;
  icon?: string;
  icons?: unknown;
  [key: string]: unknown;
}

export interface AppSnapshot {
  status: FactorioStatus | null;
  world: FactorioWorld | null;
  telemetry: TelemetryEvent[];
  catalogMeta: Record<string, unknown> | null;
  loading: boolean;
  error: string | null;
  refreshedAt: number | null;
}

export interface PageDefinition {
  key: PageKey;
  label: string;
  subtitle: string;
  group: string;
  type: PageType;
}
