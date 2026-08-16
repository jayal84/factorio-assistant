import type { CatalogRecord, FactorioStatus, FactorioWorld, TelemetryEvent } from './types';

const apiUrl = (path: string) => new URL(`./${path.replace(/^\//, '')}`, document.baseURI).toString();

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    cache: 'no-store',
    ...init,
    headers: {
      ...(init?.headers || {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const message = payload && typeof payload === 'object' && 'error' in payload ? String((payload as { error?: unknown }).error || 'Request failed.') : 'Request failed.';
    throw new Error(message);
  }
  return payload as T;
}

export async function getStatus(): Promise<FactorioStatus> {
  return requestJson<FactorioStatus>('/api/status');
}

export async function getWorld(): Promise<FactorioWorld> {
  return requestJson<FactorioWorld>('/api/world');
}

export async function getTelemetry(limit = 50): Promise<{ events: TelemetryEvent[] }> {
  return requestJson<{ events: TelemetryEvent[] }>(`/api/telemetry/events?limit=${encodeURIComponent(String(limit))}`);
}

export async function getCatalog(params: URLSearchParams): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(`/api/catalog?${params.toString()}`);
}

export async function getCatalogEntry(name: string, kind = ''): Promise<Record<string, unknown>> {
  const params = new URLSearchParams({ name, kind, detail: 'full' });
  return requestJson<Record<string, unknown>>(`/api/catalog/entry?${params.toString()}`);
}

export async function getProductionPlan(items: Array<{ name: string; rate: number }>, knownRecipes: string[] = []): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/api/catalog/production', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items, known_recipes: knownRecipes }),
  });
}

export async function callModRemote(method: string, payload: Record<string, unknown>): Promise<unknown> {
  const command = `/silent-command local ok,result=pcall(remote.call,${JSON.stringify('factorio_assistant')},${JSON.stringify(method)},${JSON.stringify(JSON.stringify(payload))});rcon.print(helpers.table_to_json({ok=ok,result=result}))`;
  const response = await requestJson<{ response?: string; error?: string }>('/api/rcon', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command }),
  });
  if (typeof response.response !== 'string' || !response.response) {
    throw new Error(response.error || 'RCON response missing.');
  }
  const envelope = JSON.parse(response.response) as { ok?: boolean; result?: unknown; error?: string };
  if (!envelope || envelope.ok !== true) {
    throw new Error(envelope?.error || 'Remote command failed.');
  }
  return envelope.result;
}

export async function dispatchAaiVehicle(payload: Record<string, unknown>): Promise<unknown> {
  return callModRemote('aai_dispatch', payload);
}

export async function dispatchLtnCommand(payload: Record<string, unknown>): Promise<unknown> {
  return callModRemote('ltn_command', payload);
}

export function catalogRecordLabel(entry: CatalogRecord | null | undefined): string {
  if (!entry) return 'Unknown';
  return entry.localized_name || entry.name || 'Unknown';
}
