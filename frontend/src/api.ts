// Tiny API client. The Vite dev server proxies /api/* to FastAPI on :8000.

export type StateStatus = {
  usps: string;
  phase: string;
  seats?: number;
  max_abs_deviation_pct?: number;
  polsby_popper_mean?: number;
  county_splits?: number;
  elapsed_sec?: number;
  error?: string;
  traceback?: string;
  plan_id?: string;
  updated_at?: string;
};

export type Summary = {
  total: number;
  done: number;
  failed: number;
  skipped: number;
  queued?: number;
  queued_skip?: number;
  loading?: number;
  graph?: number;
  districting?: number;
  running: number;
};

export type BatchManifest = {
  batch_id: string;
  created_at: string;
  states: string[];
  unit: string;
  seed_strategy: string;
  epsilon: number;
  chain_length: number;
};

export type BatchListItem = BatchManifest & {
  summary: Summary;
};

export type BatchStatusResponse = {
  manifest: BatchManifest;
  summary: Summary;
  statuses: StateStatus[];
};

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

async function post<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

export const api = {
  health: () => get<{ status: string }>('/api/health'),
  listBatches: () => get<BatchListItem[]>('/api/batches'),
  batchStatus: (id: string) => get<BatchStatusResponse>(`/api/batches/${id}/status`),
  statesGeoJSON: () => get<GeoJSON.FeatureCollection>('/api/states.geojson'),
  stateDistricts: (batchId: string, usps: string) =>
    get<GeoJSON.FeatureCollection>(`/api/batches/${batchId}/states/${usps}/districts.geojson`),
  statePlan: (batchId: string, usps: string) =>
    get<{
      plan_id: string;
      usps: string;
      n_districts: number;
      seed_strategy: string;
      epsilon: number;
      chain_length: number;
      random_seed: number;
      elapsed_sec: number;
      scorecard: {
        target_population: number;
        total_population: number;
        max_abs_deviation_pct: number;
        polsby_popper_mean: number;
        polsby_popper_min: number;
        county_splits: number;
        cut_edges: number;
        per_district: Array<{
          district: number;
          population: number;
          deviation_pct: number;
          area_sqmi: number;
          perimeter_mi: number;
          polsby_popper: number;
          block_count: number;
        }>;
      };
    }>(`/api/batches/${batchId}/states/${usps}/plan`),
  createBatch: (req: {
    unit: string;
    epsilon: number;
    chain_length: number;
    seed_strategy?: string;
    weights?: Record<string, number>;
    random_seed?: number | null;
  }) => post<BatchManifest>('/api/batches', req),
  startBatch: (id: string, workers: number) =>
    post<{ started: boolean }>(`/api/batches/${id}/start`, { workers }),
  retryFailed: (id: string, workers = 4) =>
    post<{ started: boolean; states?: string[] }>(`/api/batches/${id}/retry`, { workers }),
};
