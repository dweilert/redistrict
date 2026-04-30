/**
 * Single-state Generate Plan view.
 *
 * Lets the user pick a state, dial in all the engine knobs (unit, seed strategy,
 * ε, chain length, random seed, weight sliders), kick off a single-state ReCom
 * run, and watch live as the chain progresses. When done, the resulting plan
 * renders as a colored district choropleth with the same modal-style scorecard
 * as the nationwide view, plus a one-click PDF export.
 */
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { geoMercator, geoPath } from 'd3-geo';
import { api } from './api';

const STATE_NAMES: Record<string, string> = {
  AL: 'Alabama', AZ: 'Arizona', AR: 'Arkansas', CA: 'California', CO: 'Colorado',
  CT: 'Connecticut', FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho',
  IL: 'Illinois', IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky',
  LA: 'Louisiana', ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts',
  MI: 'Michigan', MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri',
  MT: 'Montana', NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire',
  NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York', NC: 'North Carolina',
  OH: 'Ohio', OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania',
  RI: 'Rhode Island', SC: 'South Carolina', TN: 'Tennessee', TX: 'Texas',
  UT: 'Utah', VA: 'Virginia', WA: 'Washington', WV: 'West Virginia',
  WI: 'Wisconsin',
};

const STATE_SEATS: Record<string, number> = {
  AL: 7, AZ: 9, AR: 4, CA: 52, CO: 8, CT: 5, FL: 28, GA: 14, HI: 2, ID: 2,
  IL: 17, IN: 9, IA: 4, KS: 4, KY: 6, LA: 6, ME: 2, MD: 8, MA: 9, MI: 13,
  MN: 8, MS: 4, MO: 8, MT: 2, NE: 3, NV: 4, NH: 2, NJ: 12, NM: 3, NY: 26,
  NC: 14, OH: 15, OK: 5, OR: 6, PA: 17, RI: 2, SC: 7, TN: 9, TX: 38, UT: 4,
  VA: 11, WA: 10, WV: 2, WI: 8,
};

const DISTRICT_PALETTE = [
  '#4E79A7', '#F28E2B', '#E15759', '#76B7B2', '#59A14F',
  '#EDC948', '#B07AA1', '#FF9DA7', '#9C755F', '#BAB0AC',
  '#1F77B4', '#D62728', '#2CA02C', '#9467BD', '#8C564B',
  '#E377C2', '#17BECF', '#BCBD22', '#7F7F7F', '#AEC7E8',
];

const WEIGHT_KEYS: Array<{ key: string; label: string }> = [
  { key: 'population_deviation', label: 'population_deviation' },
  { key: 'polsby_popper', label: 'polsby_popper (compactness)' },
  { key: 'county_splits', label: 'county_splits' },
  { key: 'cut_edges', label: 'cut_edges' },
  { key: 'total_area_sqmi', label: 'total_area_sqmi' },
  { key: 'perimeter_total', label: 'perimeter_total' },
  { key: 'reock', label: 'reock' },
];

interface Props {
  initialUsps?: string;
  initialUnit?: string;
  initialEpsilon?: number;
  initialChainLength?: number;
  onBack?: () => void;
}

export function SinglePlanView(props: Props) {
  const [usps, setUsps] = useState(props.initialUsps ?? 'IA');
  const [unit, setUnit] = useState(props.initialUnit ?? 'blockgroup');
  const [epsilonPct, setEpsilonPct] = useState((props.initialEpsilon ?? 0.01) * 100);
  const [chainLength, setChainLength] = useState(props.initialChainLength ?? 500);
  const [seedStrategy, setSeedStrategy] = useState('tree');
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

  const [planId, setPlanId] = useState<string | null>(null);

  const launch = useMutation({
    mutationFn: () =>
      api.createSinglePlan({
        usps,
        unit,
        epsilon: epsilonPct / 100,
        chain_length: chainLength,
        seed_strategy: seedStrategy,
        weights,
        random_seed: randomSeed === '' ? null : Number(randomSeed),
      }),
    onSuccess: (r) => setPlanId(r.plan_id),
  });

  return (
    <div className="single-plan-grid">
      <header style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: 12 }}>
        <h2 style={{ margin: 0 }}>Generate single-state plan</h2>
        {props.onBack && (
          <button className="link-btn" onClick={props.onBack}>
            ← back
          </button>
        )}
      </header>

      {/* LEFT: controls */}
      <section className="card">
        <h3>State</h3>
        <label>
          State
          <select value={usps} onChange={(e) => setUsps(e.target.value)}>
            {Object.entries(STATE_NAMES)
              .sort((a, b) => a[1].localeCompare(b[1]))
              .filter(([k]) => (STATE_SEATS[k] ?? 0) >= 2)
              .map(([k, name]) => (
                <option key={k} value={k}>
                  {name} ({k}) — {STATE_SEATS[k]} seats
                </option>
              ))}
          </select>
        </label>

        <h3>Engine</h3>
        <label>
          Unit
          <select value={unit} onChange={(e) => setUnit(e.target.value)}>
            <option value="blockgroup">blockgroup (fast)</option>
            <option value="block">block (slow, high fidelity)</option>
          </select>
        </label>
        <label>
          Initial partition
          <select value={seedStrategy} onChange={(e) => setSeedStrategy(e.target.value)}>
            <option value="tree">tree (recommended)</option>
            <option value="centroid">centroid</option>
            <option value="sweep-ew">sweep-ew</option>
            <option value="sweep-ns">sweep-ns</option>
          </select>
        </label>
        <label>
          ε (%): <strong>{epsilonPct.toFixed(1)}</strong>
          <input type="range" min={0.1} max={5} step={0.1} value={epsilonPct}
                 onChange={(e) => setEpsilonPct(parseFloat(e.target.value))} />
        </label>
        <label>
          Chain length: <strong>{chainLength}</strong>
          <input type="range" min={100} max={3000} step={50} value={chainLength}
                 onChange={(e) => setChainLength(parseInt(e.target.value))} />
        </label>
        <label>
          Random seed (blank = clock)
          <input type="number" value={randomSeed}
                 onChange={(e) => setRandomSeed(
                   e.target.value === '' ? '' : parseInt(e.target.value)
                 )} />
        </label>

        <details className="knobs-group" open>
          <summary><strong>Variable weights</strong></summary>
          {WEIGHT_KEYS.map(({ key, label }) => (
            <label key={key}>
              {label}: <strong>{weights[key].toFixed(1)}</strong>
              <input type="range" min={0} max={20} step={0.5} value={weights[key]}
                     onChange={(e) =>
                       setWeights((w) => ({ ...w, [key]: parseFloat(e.target.value) }))
                     } />
            </label>
          ))}
        </details>

        <button
          className="primary"
          onClick={() => launch.mutate()}
          disabled={launch.isPending || !usps}
        >
          {launch.isPending ? 'Starting…' : 'Generate plan'}
        </button>
        {launch.error && (
          <p className="err small">{(launch.error as Error).message}</p>
        )}
      </section>

      {/* RIGHT: live progress + result */}
      <section className="card single-plan-result">
        {!planId ? (
          <div className="muted center-pad">
            <p>Pick a state, set weights, and click <strong>Generate plan</strong>.</p>
            <p className="small">
              The chain runs server-side; this panel shows live progress and the
              final district map when it finishes.
            </p>
          </div>
        ) : (
          <SinglePlanRunner planId={planId} usps={usps} chainLength={chainLength} />
        )}
      </section>
    </div>
  );
}

function SinglePlanRunner({ planId, usps, chainLength }: { planId: string; usps: string; chainLength: number }) {
  const status = useQuery({
    queryKey: ['single-status', planId],
    queryFn: () => api.singlePlanStatus(planId),
    refetchInterval: (q) => {
      const d = q.state.data;
      if (!d) return 800;
      return d.phase === 'done' || d.phase === 'failed' ? false : 800;
    },
  });

  const isDone = status.data?.phase === 'done';

  const result = useQuery({
    queryKey: ['single-result', planId],
    queryFn: () => api.singlePlanResult(planId),
    enabled: isDone,
    retry: false,
  });
  const districts = useQuery({
    queryKey: ['single-districts', planId],
    queryFn: () => api.singlePlanDistricts(planId),
    enabled: isDone,
    retry: false,
  });

  const phase = status.data?.phase ?? 'queued';

  return (
    <>
      <div className="batch-line" style={{ marginBottom: 8 }}>
        <strong>{STATE_NAMES[usps] ?? usps}</strong>{' '}
        <span className={`phase phase-${phase}`}>{phase}</span>
        <span className="muted small">plan {planId}</span>
      </div>

      {phase !== 'done' && phase !== 'failed' && status.data && (
        <div className="single-progress">
          <div className="progress-bar">
            <div
              className="progress-bar-fill"
              style={{
                width: `${Math.min(100, (status.data.step / chainLength) * 100)}%`,
              }}
            />
          </div>
          <div className="single-progress-stats">
            <span>
              Step <strong>{status.data.step}</strong> / {chainLength}
            </span>
            {status.data.best_max_dev_pct !== null && (
              <span>
                best max |dev|:{' '}
                <strong>{status.data.best_max_dev_pct?.toFixed(4)}%</strong>
              </span>
            )}
            {status.data.best_polsby_popper_mean !== null && (
              <span>
                best PP mean:{' '}
                <strong>{status.data.best_polsby_popper_mean?.toFixed(3)}</strong>
              </span>
            )}
          </div>
        </div>
      )}

      {phase === 'failed' && (
        <div className="failure-block">
          Failed: <code>{status.data?.error}</code>
        </div>
      )}

      {isDone && districts.data && result.data && (
        <SinglePlanResultView
          planId={planId}
          districts={districts.data}
          scorecard={result.data.scorecard}
          nDistricts={result.data.n_districts}
        />
      )}
    </>
  );
}

function SinglePlanResultView({
  planId, districts, scorecard, nDistricts,
}: {
  planId: string;
  districts: GeoJSON.FeatureCollection;
  scorecard: {
    target_population: number;
    total_population: number;
    max_abs_deviation_pct: number;
    polsby_popper_mean: number;
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
  nDistricts: number;
}) {
  const W = 600;
  const H = 420;
  const projection = useMemo(() => geoMercator().fitSize([W, H], districts), [districts]);
  const pathGen = useMemo(() => geoPath(projection), [projection]);

  return (
    <>
      <div className="single-stats">
        <span>Total pop: <strong>{scorecard.total_population.toLocaleString()}</strong></span>
        <span>Max |dev|: <strong>{scorecard.max_abs_deviation_pct.toFixed(4)}%</strong></span>
        <span>PP mean: <strong>{scorecard.polsby_popper_mean.toFixed(3)}</strong></span>
        <span>County splits: <strong>{scorecard.county_splits}</strong></span>
        <span>Districts: <strong>{nDistricts}</strong></span>
      </div>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="single-plan-svg">
        {districts.features.map((f, i) => {
          const did =
            (f.properties as { district?: number } | null)?.district ?? i;
          return (
            <path
              key={i}
              d={pathGen(f) ?? ''}
              fill={DISTRICT_PALETTE[did % DISTRICT_PALETTE.length]}
              stroke="#fff"
              strokeWidth={1}
            />
          );
        })}
      </svg>

      <h4>Per-district detail</h4>
      <table className="modal-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Population</th>
            <th>Dev %</th>
            <th>Area mi²</th>
            <th>PP</th>
          </tr>
        </thead>
        <tbody>
          {scorecard.per_district.map((d) => (
            <tr key={d.district}>
              <td>
                <span
                  className="district-swatch"
                  style={{ background: DISTRICT_PALETTE[d.district % DISTRICT_PALETTE.length] }}
                />
                <strong>{d.district + 1}</strong>
              </td>
              <td>{d.population.toLocaleString()}</td>
              <td>{d.deviation_pct >= 0 ? '+' : ''}{d.deviation_pct.toFixed(4)}</td>
              <td>{d.area_sqmi.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
              <td>{d.polsby_popper.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <a
        className="primary"
        style={{ display: 'inline-block', marginTop: 12, textDecoration: 'none' }}
        href={api.singlePlanPDFUrl(planId)}
        target="_blank"
        rel="noopener noreferrer"
      >
        📄 Download PDF (with embedded plan data)
      </a>
    </>
  );
}
