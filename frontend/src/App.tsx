import { useMemo, useState } from 'react';
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { api, type BatchListItem, type StateStatus } from './api';
import { USMap, PhaseLegend, PHASE_COLORS } from './USMap';
import { CounterModal } from './CounterModal';
import { HelpPanel } from './HelpPanel';
import { StateDetailModal } from './StateDetailModal';
import { UpdateBanner } from './UpdateBanner';
import { SinglePlanView } from './SinglePlanView';
import { ErrorBoundary } from './ErrorBoundary';
import type { NationwideSource } from './USMap';
import './App.css';

const qc = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false },
  },
});

/**
 * Imperatively show a 'Opening <state>…' overlay by appending a DOM element
 * directly to <body>. Bypasses React's reconciler so it paints on the next
 * animation frame (~16ms) instead of waiting on a heavy tree re-render.
 * Auto-removes after 800ms.
 */
function showOpeningOverlay(usps: string) {
  // Remove any prior overlay so successive clicks don't stack.
  document.querySelectorAll('.opening-overlay-imperative').forEach((el) =>
    el.remove(),
  );
  const overlay = document.createElement('div');
  overlay.className = 'opening-overlay opening-overlay-imperative';
  overlay.innerHTML = `
    <div class="opening-overlay-card">
      <div class="opening-overlay-spinner"></div>
      <div class="opening-overlay-text">Opening ${usps}…</div>
    </div>
  `;
  document.body.appendChild(overlay);
  window.setTimeout(() => overlay.remove(), 800);
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <NationwideBatch />
    </QueryClientProvider>
  );
}

function NationwideBatch() {
  const [mode, setMode] = useState<'nationwide' | 'single'>('nationwide');
  const [singleSeed, setSingleSeed] = useState<{
    usps?: string;
    unit?: string;
    epsilon?: number;
    chainLength?: number;
    seedStrategy?: string;
    weights?: Record<string, number>;
    randomSeed?: number | null;
  }>({});
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null);
  const [showDistricts, setShowDistricts] = useState(true);
  const [selectedUsps, setSelectedUsps] = useState<string | null>(null);
  function handleStateClick(usps: string) {
    showOpeningOverlay(usps);
    // Defer the modal mount one tick so the imperative overlay paints first.
    window.setTimeout(() => setSelectedUsps(usps), 0);
  }

  return (
    <div className="layout">
      <header>
        <div className="mode-tabs">
          <button
            className={mode === 'nationwide' ? 'active' : ''}
            onClick={() => setMode('nationwide')}
          >Nationwide batch</button>
          <button
            className={mode === 'single' ? 'active' : ''}
            onClick={() => setMode('single')}
          >Single state</button>
        </div>
        <h1>Redistrict</h1>
        <p className="sub">
          Population-only U.S. congressional redistricting · gerrychain ReCom MCMC
        </p>
        <UpdateBanner />
      </header>
      <main>
        <ErrorBoundary>
          {mode === 'single' ? (
            <SinglePlanView
              initialUsps={singleSeed.usps}
              initialUnit={singleSeed.unit}
              initialEpsilon={singleSeed.epsilon}
              initialChainLength={singleSeed.chainLength}
              initialSeedStrategy={singleSeed.seedStrategy}
              initialWeights={singleSeed.weights}
              initialRandomSeed={singleSeed.randomSeed}
              onBack={() => setMode('nationwide')}
            />
          ) : !activeBatchId ? (
            <BatchPicker onWatch={setActiveBatchId} />
          ) : (
            <LiveBatchView
              batchId={activeBatchId}
              showDistricts={showDistricts}
              onToggleDistricts={() => setShowDistricts((v) => !v)}
              onUnwatch={() => setActiveBatchId(null)}
              onStateClick={handleStateClick}
              selectedUsps={selectedUsps}
              onClosePanel={() => setSelectedUsps(null)}
              onTuneState={(seed) => {
                setSingleSeed(seed);
                setSelectedUsps(null);
                setMode('single');
              }}
            />
          )}
        </ErrorBoundary>
      </main>

      {/* Click-feedback overlay is injected directly into <body> by
          showOpeningOverlay() so it paints before React reconciles. */}
    </div>
  );
}

const WEIGHT_DESCRIPTIONS: Array<{ key: string; label: string; help: string }> = [
  {
    key: 'population_deviation',
    label: 'Population deviation',
    help: "Already capped by ε; this slider just decides how aggressively to push within the legal envelope.",
  },
  {
    key: 'polsby_popper',
    label: 'Polsby–Popper (compactness)',
    help: "Higher = rounder, tidier districts. Lower = computer doesn't care about shape.",
  },
  {
    key: 'county_splits',
    label: 'County splits',
    help: 'Higher = the engine works harder to keep counties whole instead of cutting through them.',
  },
  {
    key: 'cut_edges',
    label: 'Cut edges',
    help: 'Number of dual-graph edges crossing district boundaries. Lower = smoother borders.',
  },
  {
    key: 'total_area_sqmi',
    label: 'Total area (sq mi)',
    help: 'Niche — usually leave at 0.',
  },
  {
    key: 'perimeter_total',
    label: 'Perimeter total',
    help: 'Like cut_edges; pick one of these two, not both.',
  },
  {
    key: 'reock',
    label: 'Reock score',
    help: 'Reserved — not yet computed.',
  },
];


function BatchPicker({ onWatch }: { onWatch: (id: string) => void }) {
  const batches = useQuery({
    queryKey: ['batches'],
    queryFn: () => api.listBatches(),
    refetchInterval: 5000,
  });

  const [unit, setUnit] = useState('blockgroup');
  const [epsilonPct, setEpsilonPct] = useState(1.0);
  const [chainLength, setChainLength] = useState(500);
  const [workers, setWorkers] = useState(6);
  const [seedStrategy, setSeedStrategy] = useState<'tree' | 'centroid' | 'sweep-ew' | 'sweep-ns'>('tree');
  const [randomSeed, setRandomSeed] = useState<number | ''>('');
  const [weights, setWeights] = useState<Record<string, number>>({
    population_deviation: 10,
    polsby_popper: 1,
    county_splits: 1,
    cut_edges: 0,
    total_area_sqmi: 0,
    perimeter_total: 0,
    reock: 0,
  });

  function updateWeight(k: string, v: number) {
    setWeights((w) => ({ ...w, [k]: v }));
  }

  const launch = useMutation({
    mutationFn: async () => {
      const m = await api.createBatch({
        unit,
        epsilon: epsilonPct / 100,
        chain_length: chainLength,
        seed_strategy: seedStrategy,
        weights,
        random_seed: randomSeed === '' ? null : Number(randomSeed),
      });
      await api.startBatch(m.batch_id, workers);
      return m;
    },
    onSuccess: (m) => onWatch(m.batch_id),
  });

  return (
    <div className="picker-with-help">
      <HelpPanel />
      <div className="picker">
      <section className="card">
        <h2>Watch existing batch</h2>
        {!batches.data || batches.data.length === 0 ? (
          <p className="muted">No batches yet — launch one on the right.</p>
        ) : (
          <ul className="batch-list">
            {batches.data.map((b) => (
              <BatchRow key={b.batch_id} batch={b} onWatch={onWatch} />
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h2>Launch new batch</h2>
        <p className="muted small">
          Runs the engine on every state in parallel. Each state takes seconds at
          blockgroup resolution; the whole country finishes in a few minutes.
        </p>

        <details className="knobs-group" open>
          <summary><strong>Engine</strong></summary>
          <label title="block = ~175k nodes per state; blockgroup = ~3k. Blockgroup is the academic standard for ReCom MCMC.">
            Unit of analysis
            <select value={unit} onChange={(e) => setUnit(e.target.value)}>
              <option value="blockgroup">blockgroup (fast, default)</option>
              <option value="block">block (high fidelity, slower)</option>
            </select>
          </label>
          <label title="How the chain starts. 'tree' is recommended; matches the ReCom proposal so the chain mixes faster.">
            Initial partition (seed strategy)
            <select value={seedStrategy} onChange={(e) => setSeedStrategy(e.target.value as typeof seedStrategy)}>
              <option value="tree">tree (recommended)</option>
              <option value="centroid">centroid (k-means++ population-weighted)</option>
              <option value="sweep-ew">sweep-ew (longitude strips)</option>
              <option value="sweep-ns">sweep-ns (latitude strips)</option>
            </select>
          </label>
          <label title="Hard cap on |district pop − target| / target. Federal congressional standard is ≤1%.">
            Population tolerance ε: <strong>{epsilonPct.toFixed(1)}%</strong>
            <input type="range" min={0.1} max={5} step={0.1} value={epsilonPct}
                   onChange={(e) => setEpsilonPct(parseFloat(e.target.value))} />
          </label>
          <label title="Number of ReCom proposals. More = better optimization, longer wait. 200–500 plenty for small states; 1000+ for big ones.">
            Chain length: <strong>{chainLength}</strong>
            <input type="range" min={100} max={3000} step={50} value={chainLength}
                   onChange={(e) => setChainLength(parseInt(e.target.value))} />
          </label>
          <label title="Same seed + same settings → identical plans. Leave blank to use the clock.">
            Random seed (optional)
            <input type="number" value={randomSeed}
                   placeholder="leave blank for clock-based"
                   onChange={(e) => setRandomSeed(e.target.value === '' ? '' : parseInt(e.target.value))} />
          </label>
          <label title="One state per worker. With 10 CPUs, 6 leaves headroom for the system + UI.">
            Workers: <strong>{workers}</strong>
            <input type="range" min={1} max={12} step={1} value={workers}
                   onChange={(e) => setWorkers(parseInt(e.target.value))} />
          </label>
        </details>

        <details className="knobs-group">
          <summary>
            <strong>Variable weights</strong>{' '}
            <span className="muted small">— relative importance during chain selection (lower = better composite score)</span>
          </summary>
          {WEIGHT_DESCRIPTIONS.map(({ key, label, help }) => (
            <label key={key} title={help}>
              {label}: <strong>{weights[key].toFixed(1)}</strong>
              <input type="range" min={0} max={20} step={0.5} value={weights[key]}
                     onChange={(e) => updateWeight(key, parseFloat(e.target.value))} />
            </label>
          ))}
        </details>

        <button
          className="primary"
          disabled={launch.isPending}
          onClick={() => launch.mutate()}
        >
          {launch.isPending ? 'Launching…' : 'Launch all 50 states'}
        </button>
      </section>
      </div>
    </div>
  );
}

function BatchRow({ batch, onWatch }: { batch: BatchListItem; onWatch: (id: string) => void }) {
  const s = batch.summary;
  return (
    <li>
      <div className="batch-row-main">
        <code>{batch.batch_id}</code>
        <span className="muted small">
          ε {(batch.epsilon * 100).toFixed(2)}% · chain {batch.chain_length} ·{' '}
          {s.done}/{s.total} done · {s.failed} failed
        </span>
      </div>
      <button onClick={() => onWatch(batch.batch_id)}>▶ Watch</button>
    </li>
  );
}

interface TuneSeed {
  usps: string;
  unit: string;
  epsilon: number;
  chainLength: number;
  seedStrategy: string;
  weights: Record<string, number>;
  randomSeed: number | null;
}

interface LiveBatchViewProps {
  batchId: string;
  showDistricts: boolean;
  onToggleDistricts: () => void;
  onUnwatch: () => void;
  onStateClick: (usps: string) => void;
  selectedUsps: string | null;
  onClosePanel: () => void;
  onTuneState: (seed: TuneSeed) => void;
}

function LiveBatchView(props: LiveBatchViewProps) {
  const {
    batchId,
    showDistricts,
    onToggleDistricts,
    onUnwatch,
    onStateClick,
    selectedUsps,
    onClosePanel,
    onTuneState,
  } = props;
  const queryClient = useQueryClient();
  const [counterModal, setCounterModal] = useState<
    'total' | 'done' | 'running' | 'failed' | 'skipped' | null
  >(null);
  const [source, setSource] = useState<NationwideSource>('batch');
  const defaultsSummary = useQuery({
    queryKey: ['nationwide-defaults-summary'],
    queryFn: () => api.nationwideDefaultsSummary(),
    enabled: source === 'defaults',
    staleTime: 30_000,
  });

  const status = useQuery({
    queryKey: ['batch-status', batchId],
    queryFn: () => api.batchStatus(batchId),
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return 2000;
      return data.summary.running > 0 ? 2000 : 4000;
    },
  });

  const retry = useMutation({
    mutationFn: () => api.retryFailed(batchId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['batch-status', batchId] }),
  });

  const failed = useMemo(
    () => status.data?.statuses.filter((s) => s.phase === 'failed') ?? [],
    [status.data]
  );

  if (!status.data) {
    return <div className="card">Loading batch…</div>;
  }

  const s = status.data.summary;
  const m = status.data.manifest;
  const statuses = status.data.statuses;

  return (
    <div className="live-grid">
      <div className="live-summary">
        <div className="batch-line">
          <button className="link-btn" onClick={onUnwatch}>
            ← all batches
          </button>
          <code>{m.batch_id}</code>
          <span>
            ε {(m.epsilon * 100).toFixed(2)}% · chain {m.chain_length} · {m.unit}
          </span>
        </div>
        <div className="counters">
          <Counter label="Total" value={s.total} onClick={() => setCounterModal('total')} />
          <Counter label="Done" value={s.done} kind="ok"
                   onClick={() => setCounterModal('done')} />
          <Counter label="Running" value={s.running} kind="busy"
                   onClick={() => setCounterModal('running')} />
          <Counter label="Failed" value={s.failed} kind={s.failed ? 'err' : 'idle'}
                   onClick={() => setCounterModal('failed')} />
          <Counter
            label="Skipped"
            value={(s.skipped ?? 0) + (s.queued_skip ?? 0)}
            kind="idle"
            onClick={() => setCounterModal('skipped')}
          />
        </div>
        <div className="controls-row">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={showDistricts}
              onChange={onToggleDistricts}
            />
            Show actual districts on done states
          </label>
          {failed.length > 0 && (
            <button
              className="warn"
              disabled={retry.isPending}
              onClick={() => retry.mutate()}
            >
              {retry.isPending ? 'Retrying…' : `🔁 Retry ${failed.length} failed`}
            </button>
          )}
        </div>
      </div>

      <div className="map-card">
        <div className="nationwide-source-tabs">
          <button
            className={source === 'batch' ? 'active' : ''}
            onClick={() => setSource('batch')}
            title="Show the current batch's per-state plans."
          >
            📊 This batch
          </button>
          <button
            className={source === 'defaults' ? 'active' : ''}
            onClick={() => setSource('defaults')}
            title="Compose the map from each state's catalog default."
          >
            ⭐ Catalog defaults
            {defaultsSummary.data && (
              <span className="badge">
                {defaultsSummary.data.tuned_count} of{' '}
                {defaultsSummary.data.total_states} tuned
              </span>
            )}
          </button>
          <button
            className={source === 'census' ? 'active' : ''}
            onClick={() => setSource('census')}
            title="Show every state's official 119th-Congress districts."
          >
            🇺🇸 Census current
          </button>
        </div>
        <USMap
          batchId={batchId}
          statuses={statuses}
          showDistricts={showDistricts}
          source={source}
          onStateClick={onStateClick}
          highlightUsps={selectedUsps}
        />
        <PhaseLegend />
      </div>
      {counterModal && (
        <CounterModal
          kind={counterModal}
          statuses={statuses}
          onClose={() => setCounterModal(null)}
          onStateClick={(usps) => {
            setCounterModal(null);
            onStateClick(usps);
          }}
        />
      )}

      {selectedUsps && (
        <StateDetailModal
          batchId={batchId}
          usps={selectedUsps}
          status={statuses.find((x) => x.usps === selectedUsps)}
          manifest={status.data?.manifest}
          onTune={(u) => {
            const m = status.data!.manifest as unknown as {
              unit: string;
              epsilon: number;
              chain_length: number;
              seed_strategy: string;
              weights?: Record<string, number>;
              random_seed_base?: number | null;
            };
            onTuneState({
              usps: u,
              unit: m.unit,
              epsilon: m.epsilon,
              chainLength: m.chain_length,
              seedStrategy: m.seed_strategy ?? 'tree',
              weights: m.weights ?? {},
              randomSeed: m.random_seed_base ?? null,
            });
          }}
          onClose={onClosePanel}
        />
      )}

      <details className="status-table">
        <summary>Per-state status table ({statuses.length} entries)</summary>
        <StatusTable statuses={statuses} onStateClick={onStateClick} />
      </details>

      {failed.length > 0 && (
        <details className="failure-block" open>
          <summary>⚠ Failures ({failed.length})</summary>
          <ul>
            {failed.map((f) => (
              <li key={f.usps}>
                <strong>{f.usps}</strong>: <code>{f.error ?? 'unknown error'}</code>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Counter({
  label,
  value,
  kind = 'idle',
  onClick,
}: {
  label: string;
  value: number;
  kind?: string;
  onClick?: () => void;
}) {
  return (
    <button
      className={`counter counter-${kind}`}
      onClick={onClick}
      title={onClick ? `Click to see ${label.toLowerCase()} states` : undefined}
    >
      <div className="counter-value">{value}</div>
      <div className="counter-label">{label}</div>
    </button>
  );
}

function StatusTable({
  statuses,
  onStateClick,
}: {
  statuses: StateStatus[];
  onStateClick?: (u: string) => void;
}) {
  return (
    <table>
      <thead>
        <tr>
          <th>USPS</th>
          <th>Phase</th>
          <th>Seats</th>
          <th>Max |dev| %</th>
          <th>PP mean</th>
          <th>Splits</th>
          <th>Elapsed s</th>
        </tr>
      </thead>
      <tbody>
        {statuses.map((s) => (
          <tr
            key={s.usps}
            className="row-clickable"
            onClick={() => onStateClick?.(s.usps)}
          >
            <td>
              <strong>{s.usps}</strong>
            </td>
            <td>
              <span className={`phase phase-${s.phase}`}>{s.phase}</span>
            </td>
            <td>{s.seats ?? '—'}</td>
            <td>{s.max_abs_deviation_pct?.toFixed(4) ?? '—'}</td>
            <td>{s.polsby_popper_mean?.toFixed(3) ?? '—'}</td>
            <td>{s.county_splits ?? '—'}</td>
            <td>{s.elapsed_sec?.toFixed(1) ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StateDetailPanel({
  usps,
  status,
  onClose,
}: {
  usps: string;
  status?: StateStatus;
  onClose: () => void;
}) {
  return (
    <aside className="state-panel">
      <button className="link-btn close" onClick={onClose}>
        ×
      </button>
      <h3>{usps}</h3>
      {!status ? (
        <p className="muted">No status yet.</p>
      ) : (
        <>
          <p>
            Phase: <span className={`phase phase-${status.phase}`}>{status.phase}</span>
          </p>
          {status.seats !== undefined && <p>Seats: {status.seats}</p>}
          {status.max_abs_deviation_pct !== undefined && (
            <p>Max |dev|: {status.max_abs_deviation_pct.toFixed(4)}%</p>
          )}
          {status.polsby_popper_mean !== undefined && (
            <p>Polsby–Popper (mean): {status.polsby_popper_mean.toFixed(3)}</p>
          )}
          {status.county_splits !== undefined && (
            <p>County splits: {status.county_splits}</p>
          )}
          {status.elapsed_sec !== undefined && (
            <p>Elapsed: {status.elapsed_sec.toFixed(1)} s</p>
          )}
          {status.error && (
            <p className="err">
              Error: <code>{status.error}</code>
            </p>
          )}
        </>
      )}
    </aside>
  );
}
