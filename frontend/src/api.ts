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

export type CensusFileStatus = {
  key: string;
  label: string;
  why: string;
  url: string;
  present: boolean;
  local_last_modified: string | null;
  remote_last_modified: string | null;
  update_available: boolean;
  downloaded_at: string | null;
};

export const api = {
  health: () => get<{ status: string }>('/api/health'),
  censusFiles: () => get<CensusFileStatus[]>('/api/census-files'),
  downloadCensusFile: (key: string) =>
    post<{ downloaded: boolean }>(`/api/census-files/${key}/download`),
  listBatches: () => get<BatchListItem[]>('/api/batches'),
  batchStatus: (id: string) => get<BatchStatusResponse>(`/api/batches/${id}/status`),
  statesGeoJSON: () => get<GeoJSON.FeatureCollection>('/api/states.geojson'),
  stateDistricts: (batchId: string, usps: string) =>
    get<GeoJSON.FeatureCollection>(`/api/batches/${batchId}/states/${usps}/districts.geojson`),
  // ---- catalog ----
  catalogList: (usps: string) =>
    get<{
      usps: string;
      default_plan_uuid: string;
      entries: Array<{
        plan_uuid: string;
        usps: string;
        name: string;
        source: 'census' | 'nationwide' | 'single';
        batch_id: string | null;
        parameters: Record<string, unknown>;
        scorecard: Record<string, unknown>;
        created_at: string | null;
        is_default?: boolean;
      }>;
    }>(`/api/states/${usps}/catalog`),
  catalogSave: (usps: string, body: { name: string; plan_id: string }) =>
    post<{ plan_uuid: string }>(`/api/states/${usps}/catalog`, body),
  catalogDelete: (usps: string, planUuid: string) =>
    fetch(`/api/states/${usps}/catalog/${planUuid}`, { method: 'DELETE' }).then(
      (r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))),
    ),
  catalogSetDefault: (usps: string, plan_uuid: string) =>
    post<{ default_plan_uuid: string }>(`/api/states/${usps}/catalog/set-default`, {
      plan_uuid,
    }),
  catalogDistricts: (usps: string, planUuid: string) =>
    get<GeoJSON.FeatureCollection>(
      `/api/states/${usps}/catalog/${planUuid}/districts.geojson`,
    ),
  // ---- bundled nationwide views ----
  nationwideCensus: () =>
    get<GeoJSON.FeatureCollection>('/api/nationwide/census-districts.geojson'),
  nationwideDefaults: () =>
    get<GeoJSON.FeatureCollection>('/api/nationwide/default-districts.geojson'),
  nationwideDefaultsSummary: () =>
    get<{
      defaults: Record<string, string>;
      tuned_count: number;
      total_states: number;
    }>('/api/nationwide/defaults-summary'),

  allDistricts: (batchId: string) =>
    get<GeoJSON.FeatureCollection>(`/api/batches/${batchId}/all-districts.geojson`),
  districtCities: (batchId: string, usps: string, district: number) =>
    get<{
      usps: string;
      district: number;
      cities: Array<{
        name: string;
        kind: string;
        population: number;
        area_sqmi: number;
      }>;
    }>(`/api/batches/${batchId}/states/${usps}/districts/${district}/cities`),
  stateCD119DistrictCities: (usps: string, district: number) =>
    get<{
      usps: string;
      district: number;
      cities: Array<{ name: string; kind: string; population: number; area_sqmi: number }>;
    }>(`/api/states/${usps}/cd119/districts/${district}/cities`),
  stateCD119: (usps: string) =>
    get<GeoJSON.FeatureCollection>(`/api/states/${usps}/cd119.geojson`),
  stateCD119Scorecard: (usps: string) =>
    get<{
      available: boolean;
      n_districts?: number;
      total_population?: number;
      target_population?: number;
      max_abs_deviation_pct?: number;
      polsby_popper_mean?: number;
      polsby_popper_min?: number;
      county_splits?: number;
      per_district?: Array<{
        district: number;
        population: number;
        deviation_pct: number;
        area_sqmi: number;
        perimeter_mi: number;
        polsby_popper: number;
      }>;
    }>(`/api/states/${usps}/cd119/scorecard`),
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
  // ---- single-state plan ----
  createSinglePlan: (req: {
    usps: string;
    unit: string;
    epsilon: number;
    chain_length: number;
    seed_strategy?: string;
    weights?: Record<string, number>;
    random_seed?: number | null;
  }) => post<{ plan_id: string }>('/api/single-plan', req),
  singlePlanStatus: (id: string) =>
    get<{
      plan_id: string;
      phase: string;
      usps: string;
      n_districts: number;
      step: number;
      best_score: number | null;
      best_max_dev_pct: number | null;
      best_polsby_popper_mean: number | null;
      error?: string;
    }>(`/api/single-plan/${id}/status`),
  singlePlanResult: (id: string) =>
    get<{
      plan_id: string;
      usps: string;
      n_districts: number;
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
    }>(`/api/single-plan/${id}/result`),
  singlePlanPreview: (id: string) =>
    get<GeoJSON.FeatureCollection & { _step?: number }>(
      `/api/single-plan/${id}/preview-districts.geojson`
    ),
  singlePlanCities: (id: string, district: number) =>
    get<{
      plan_id: string;
      district: number;
      cities: Array<{
        name: string;
        kind: string;
        population: number;
        area_sqmi: number;
      }>;
    }>(`/api/single-plan/${id}/districts/${district}/cities`),
  singlePlanDistricts: (id: string) =>
    get<GeoJSON.FeatureCollection>(`/api/single-plan/${id}/districts.geojson`),
  singlePlanPDFUrl: (id: string) => `/api/single-plan/${id}/pdf`,

  retryFailed: (id: string, workers = 4) =>
    post<{ started: boolean; states?: string[] }>(`/api/batches/${id}/retry`, { workers }),
};
