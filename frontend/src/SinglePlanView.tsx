/**
 * Single-state Generate Plan view.
 *
 * Lets the user pick a state, dial in all the engine knobs (unit, seed strategy,
 * ε, chain length, random seed, weight sliders), kick off a single-state ReCom
 * run, and watch live as the chain progresses. When done, the resulting plan
 * renders as a colored district choropleth with the same modal-style scorecard
 * as the nationwide view, plus a one-click PDF export.
 */
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { geoMercator, geoPath } from 'd3-geo';
import { api } from './api';
import { DistrictMap, DISTRICT_PALETTE } from './DistrictMap';
import { CitiesPanel } from './CitiesPanel';
import { SinglePlanHelp } from './SinglePlanHelp';
import { LiveStatePreview } from './LiveStatePreview';

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

const WEIGHT_KEYS: Array<{ key: string; label: string; help: string }> = [
  { key: 'population_deviation', label: 'population_deviation',
    help: "Already capped by ε; this just decides whether to push for as-close-as-possible or settle for 'good enough within the legal envelope'." },
  { key: 'polsby_popper', label: 'polsby_popper (compactness)',
    help: 'Higher = rounder, tidier districts. 1.0 = perfect circle; 0.2–0.3 typical real district.' },
  { key: 'county_splits', label: 'county_splits',
    help: 'Higher = engine works harder to keep counties whole.' },
  { key: 'cut_edges', label: 'cut_edges',
    help: 'Smoother borders. Pick this OR polsby_popper, not both — they reward similar things.' },
  { key: 'total_area_sqmi', label: 'total_area_sqmi',
    help: 'Niche. Usually leave at 0.' },
  { key: 'perimeter_total', label: 'perimeter_total',
    help: 'Like cut_edges; pick one of the two.' },
  { key: 'reock', label: 'reock',
    help: 'Reserved — not yet computed.' },
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
    <div className="single-plan-wrapper">
      <header style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>Generate single-state plan</h2>
        {props.onBack && (
          <button className="link-btn" onClick={props.onBack}>
            ← back
          </button>
        )}
      </header>
      <SinglePlanHelp />
      <div className="single-plan-grid">

      {/* LEFT: controls */}
      <section className="card">
        <h3>State</h3>
        <label title="Only states with two or more U.S. House seats are listed; one-seat states have nothing to district.">
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
        <label title="blockgroup ≈ thousands of nodes, fast, academic-standard for ReCom. block ≈ hundreds of thousands; minutes per chain.">
          Unit
          <select value={unit} onChange={(e) => setUnit(e.target.value)}>
            <option value="blockgroup">blockgroup (fast)</option>
            <option value="block">block (slow, high fidelity)</option>
          </select>
        </label>
        <label title="How the engine starts. 'tree' is recommended — matches the ReCom proposal, mixes faster.">
          Initial partition
          <select value={seedStrategy} onChange={(e) => setSeedStrategy(e.target.value)}>
            <option value="tree">tree (recommended)</option>
            <option value="centroid">centroid</option>
            <option value="sweep-ew">sweep-ew</option>
            <option value="sweep-ns">sweep-ns</option>
          </select>
        </label>
        <label title="Hard cap on |district pop − target| / target. Federal congressional standard is ≤1%. Higher = exploratory only.">
          ε (%): <strong>{epsilonPct.toFixed(1)}</strong>
          <input type="range" min={0.1} max={5} step={0.1} value={epsilonPct}
                 onChange={(e) => setEpsilonPct(parseFloat(e.target.value))} />
        </label>
        <label title="Number of ReCom moves to attempt. More = better optimization, longer wait. 200–500 plenty for small states; 1000–3000 for big ones.">
          Chain length: <strong>{chainLength}</strong>
          <input type="range" min={100} max={3000} step={50} value={chainLength}
                 onChange={(e) => setChainLength(parseInt(e.target.value))} />
        </label>
        <label title="Same seed + same settings = identical map every time. Leave blank to randomize.">
          Random seed (blank = clock)
          <input type="number" value={randomSeed}
                 onChange={(e) => setRandomSeed(
                   e.target.value === '' ? '' : parseInt(e.target.value)
                 )} />
        </label>

        <details className="knobs-group" open>
          <summary><strong>Variable weights</strong></summary>
          {WEIGHT_KEYS.map(({ key, label, help }) => (
            <label key={key} title={help}>
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

      {/* RIGHT: state preview / live progress / result */}
      <section className="card single-plan-result">
        {!planId ? (
          <StateSelectionPreview usps={usps} />
        ) : (
          <SinglePlanRunner planId={planId} usps={usps} chainLength={chainLength} />
        )}
      </section>
      </div>
    </div>
  );
}

/** Static preview of the picked state, shown before any plan is generated. */
function StateSelectionPreview({ usps }: { usps: string }) {
  const states = useQuery({
    queryKey: ['states-geojson'],
    queryFn: () => api.statesGeoJSON(),
    staleTime: 60 * 60 * 1000,
  });
  const fullName = STATE_NAMES[usps] ?? usps;
  const seats = STATE_SEATS[usps] ?? 0;

  // Project just this state.
  const W = 700;
  const H = 420;
  const fc = states.data && {
    type: 'FeatureCollection',
    features: states.data.features.filter(
      (f) => (f.properties as { usps?: string } | null)?.usps === usps
    ),
  } as GeoJSON.FeatureCollection | undefined;
  const projection = fc ? geoMercator().fitSize([W, H], fc) : null;
  const pathGen = projection ? geoPath(projection) : null;

  return (
    <div className="state-preview">
      <div className="state-preview-header">
        <h3 style={{ margin: 0 }}>{fullName}</h3>
        <span className="muted">({usps})</span>
        <span className="state-seats-pill">{seats} U.S. House seats</span>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="state-preview-svg">
        {fc && pathGen && fc.features.map((f, i) => (
          <path
            key={i}
            d={pathGen(f) ?? ''}
            fill="#cbd5e1"
            stroke="#1e293b"
            strokeWidth={1.5}
          />
        ))}
      </svg>
      <p className="muted small" style={{ marginTop: 8 }}>
        Set ε / chain length / weights on the left, then click{' '}
        <strong>Generate plan</strong> to start the engine.
      </p>
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
    retry: false,
  });

  // If the server lost the plan (e.g. backend restart), tell the user.
  if (status.error && /Unknown plan|404/.test(String(status.error))) {
    return (
      <div className="failure-block">
        <strong>Plan lost.</strong> The backend restarted and the in-progress
        chain was discarded. Click <strong>Generate plan</strong> again to start over.
      </div>
    );
  }

  const isDone = status.data?.phase === 'done';
  const isRunning = status.data?.phase === 'districting' || status.data?.phase === 'loading' || status.data?.phase === 'graph';

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
        <LiveStatePreview
          planId={planId}
          usps={usps}
          step={status.data.step}
          chainLength={chainLength}
          bestMaxDev={status.data.best_max_dev_pct}
          bestPP={status.data.best_polsby_popper_mean}
          hasFirstBest={status.data.best_score !== null && status.data.best_score !== undefined}
          isRunning={isRunning}
        />
      )}

      {phase === 'failed' && (
        <div className="failure-block">
          Failed: <code>{status.data?.error}</code>
        </div>
      )}

      {isDone && districts.data && result.data && (
        <SinglePlanResultView
          planId={planId}
          usps={usps}
          districts={districts.data}
          scorecard={result.data.scorecard}
          nDistricts={result.data.n_districts}
        />
      )}
    </>
  );
}

interface ResultProps {
  planId: string;
  usps: string;
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
}

type ViewMode = 'generated' | 'overlay' | 'current';

function SinglePlanResultView({ planId, usps, districts, scorecard, nDistricts }: ResultProps) {
  const [showLabels, setShowLabels] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>('generated');
  const [overlayOpacity, setOverlayOpacity] = useState(50);
  const [selectedDistrict, setSelectedDistrict] = useState<number | null>(null);

  // Current districts always loaded eagerly so the toggle is instant.
  const officialQuery = useQuery({
    queryKey: ['cd119', usps],
    queryFn: () => api.stateCD119(usps),
    staleTime: 24 * 60 * 60 * 1000,
    retry: false,
  });
  const officialScorecardQuery = useQuery({
    queryKey: ['cd119-scorecard', usps],
    queryFn: () => api.stateCD119Scorecard(usps),
    staleTime: 24 * 60 * 60 * 1000,
    retry: false,
  });

  // Reset selection when view mode changes — district numbering comes from a
  // different source.
  function changeView(m: ViewMode) {
    setViewMode(m);
    setSelectedDistrict(null);
  }

  // Determine what the primary (interactive) FC is and what the overlay is.
  const primaryFC = viewMode === 'current' ? officialQuery.data : districts;
  const overlayFC =
    viewMode === 'overlay'
      ? officialQuery.data
      : undefined;
  const effectiveOverlayOpacity = viewMode === 'overlay' ? overlayOpacity / 100 : 0;

  return (
    <>
      <div className="single-stats">
        <span>Total pop: <strong>{scorecard.total_population.toLocaleString()}</strong></span>
        <span>Max |dev|: <strong>{scorecard.max_abs_deviation_pct.toFixed(4)}%</strong></span>
        <span>PP mean: <strong>{scorecard.polsby_popper_mean.toFixed(3)}</strong></span>
        <span>County splits: <strong>{scorecard.county_splits}</strong></span>
        <span>Districts: <strong>{nDistricts}</strong></span>
      </div>

      <div className="view-mode-tabs" role="tablist">
        <button
          className={viewMode === 'generated' ? 'active' : ''}
          onClick={() => changeView('generated')}
          title="The plan you just generated."
        >
          Generated
        </button>
        <button
          className={viewMode === 'overlay' ? 'active' : ''}
          onClick={() => changeView('overlay')}
          title="Generated plan with the official current districts overlaid (drag the slider to fade)."
          disabled={!officialQuery.data}
        >
          Both (overlay)
        </button>
        <button
          className={viewMode === 'current' ? 'active' : ''}
          onClick={() => changeView('current')}
          title="The state's officially-adopted current 119th-Congress districts."
          disabled={!officialQuery.data}
        >
          Current 119th
        </button>
      </div>

      <div className="single-plan-mapwrap">
        <div className="state-map-toolbar">
          <label className="checkbox">
            <input type="checkbox" checked={showLabels}
                   onChange={(e) => setShowLabels(e.target.checked)} />
            Show district numbers
          </label>
        </div>
        {viewMode === 'overlay' && (
          <div className="overlay-toggle">
            <span title="Opacity of the official-current overlay. 0% = generated only; 100% = current districts on top.">
              Current overlay
            </span>
            <input type="range" min={0} max={100} step={5} value={overlayOpacity}
                   onChange={(e) => setOverlayOpacity(parseInt(e.target.value))} />
            <span className="muted small" style={{ minWidth: 36 }}>{overlayOpacity}%</span>
          </div>
        )}
        {primaryFC ? (
          <DistrictMap
            fc={primaryFC}
            overlayFC={overlayFC}
            overlayOpacity={effectiveOverlayOpacity}
            showLabels={showLabels}
            selectedDistrict={selectedDistrict}
            onDistrictClick={setSelectedDistrict}
            className="single-plan-svg"
          />
        ) : (
          <div className="muted center-pad">Loading…</div>
        )}
      </div>

      {selectedDistrict !== null && viewMode !== 'current' && (
        <CitiesPanel
          district={selectedDistrict}
          queryKey={['single-plan-cities', planId, String(selectedDistrict)]}
          fetcher={() => api.singlePlanCities(planId, selectedDistrict)}
          onClose={() => setSelectedDistrict(null)}
        />
      )}
      {selectedDistrict !== null && viewMode === 'current' && (
        <CitiesPanel
          district={selectedDistrict}
          queryKey={['cd119-cities', usps, String(selectedDistrict)]}
          fetcher={() => api.stateCD119DistrictCities(usps, selectedDistrict)}
          onClose={() => setSelectedDistrict(null)}
        />
      )}

      {officialScorecardQuery.data?.available && (
        <>
          <h4>Generated vs. current (119th Congress)</h4>
          <table className="modal-table compare-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Generated</th>
                <th>Current (119th)</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Max |deviation|</td>
                <td>{scorecard.max_abs_deviation_pct.toFixed(4)}%</td>
                <td>{officialScorecardQuery.data.max_abs_deviation_pct?.toFixed(4)}%</td>
              </tr>
              <tr>
                <td>Polsby–Popper mean</td>
                <td>{scorecard.polsby_popper_mean.toFixed(3)}</td>
                <td>{officialScorecardQuery.data.polsby_popper_mean?.toFixed(3)}</td>
              </tr>
              <tr>
                <td>County splits</td>
                <td>{scorecard.county_splits}</td>
                <td>{officialScorecardQuery.data.county_splits}</td>
              </tr>
            </tbody>
          </table>
        </>
      )}

      <h4>Per-district detail <span className="muted small">(click a row to see its cities)</span></h4>
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
            <tr key={d.district} className="row-clickable"
                onClick={() => setSelectedDistrict(d.district)}>
              <td>
                <span className="district-swatch"
                      style={{ background: DISTRICT_PALETTE[d.district % DISTRICT_PALETTE.length] }} />
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
