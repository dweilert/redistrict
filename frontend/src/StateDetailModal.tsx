/**
 * Modal dialog showing one state's details: phase, totals, and the per-district
 * scorecard (population, deviation %, area, compactness).
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { geoMercator, geoPath } from 'd3-geo';
import { api, type StateStatus } from './api';

const STATE_NAMES: Record<string, string> = {
  AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California',
  CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware', DC: 'District of Columbia',
  FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois',
  IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana',
  ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota',
  MS: 'Mississippi', MO: 'Missouri', MT: 'Montana', NE: 'Nebraska', NV: 'Nevada',
  NH: 'New Hampshire', NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York',
  NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio', OK: 'Oklahoma', OR: 'Oregon',
  PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota',
  TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont', VA: 'Virginia',
  WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming',
};

const DISTRICT_PALETTE = [
  '#4E79A7', '#F28E2B', '#E15759', '#76B7B2', '#59A14F',
  '#EDC948', '#B07AA1', '#FF9DA7', '#9C755F', '#BAB0AC',
  '#1F77B4', '#D62728', '#2CA02C', '#9467BD', '#8C564B',
  '#E377C2', '#17BECF', '#BCBD22', '#7F7F7F', '#AEC7E8',
];

interface Props {
  batchId: string;
  usps: string;
  status?: StateStatus;
  onClose: () => void;
}

export function StateDetailModal({ batchId, usps, status, onClose }: Props) {
  const planQuery = useQuery({
    queryKey: ['state-plan', batchId, usps],
    queryFn: () => api.statePlan(batchId, usps),
    enabled: status?.phase === 'done',
    retry: false,
  });
  const districtsQuery = useQuery({
    queryKey: ['districts', batchId, usps],
    queryFn: () => api.stateDistricts(batchId, usps),
    enabled: status?.phase === 'done',
    retry: false,
  });

  const fullName = STATE_NAMES[usps] ?? usps;
  const plan = planQuery.data;
  const sc = plan?.scorecard;
  const districtsFC = districtsQuery.data;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal modal-state-fullscreen"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-state-header">
          <h2>
            {fullName} <span className="muted">({usps})</span>
            {status?.seats !== undefined && (
              <span className="muted small" style={{ marginLeft: 12 }}>
                {status.seats} U.S. House seats
              </span>
            )}
          </h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal-state-body">
          {/* LEFT: big district map */}
          <div className="modal-state-map">
            {districtsFC ? (
              <StateDistrictMap fc={districtsFC} />
            ) : status?.phase === 'done' ? (
              <div className="muted center-pad">Loading districts…</div>
            ) : (
              <div className="muted center-pad">No districts to draw.</div>
            )}
          </div>

          {/* RIGHT: data panels */}
          <div className="modal-state-info">
            {status && (
              <div className="state-meta">
                <span>
                  Phase: <span className={`phase phase-${status.phase}`}>{status.phase}</span>
                </span>
                {status.elapsed_sec !== undefined && (
                  <span>Elapsed: {status.elapsed_sec.toFixed(1)} s</span>
                )}
              </div>
            )}

            {status?.phase === 'failed' && status.error && (
              <div className="failure-block">
                <strong>Failure:</strong> <code>{status.error}</code>
              </div>
            )}

            {(status?.phase === 'queued_skip' || status?.phase === 'skipped') && (
              <div className="info-block">
                <strong>Single-seat state.</strong> The whole state is one district —
                nothing for the engine to compute.
              </div>
            )}

            {planQuery.isLoading && <p className="muted">Loading plan…</p>}

            {sc && plan && (
              <>
                <h3>Plan summary</h3>
                <div className="kv-grid">
                  <KV k="Total population" v={sc.total_population.toLocaleString()} />
                  <KV k="Target / district" v={sc.target_population.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
                  <KV k="Max |deviation|" v={`${sc.max_abs_deviation_pct.toFixed(4)}%`} />
                  <KV k="Polsby–Popper mean" v={sc.polsby_popper_mean.toFixed(3)} />
                  <KV k="County splits" v={sc.county_splits} />
                  <KV k="Districts drawn" v={plan.n_districts} />
                </div>

                <h3>Per-district detail</h3>
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
                    {sc.per_district.map((d) => {
                      const id = Number(d.district);
                      const color = DISTRICT_PALETTE[id % DISTRICT_PALETTE.length];
                      return (
                        <tr key={id}>
                          <td>
                            <span
                              className="district-swatch"
                              style={{ background: color }}
                            />
                            <strong>{id + 1}</strong>
                          </td>
                          <td>{d.population.toLocaleString()}</td>
                          <td>{d.deviation_pct >= 0 ? '+' : ''}{d.deviation_pct.toFixed(3)}</td>
                          <td>{d.area_sqmi.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                          <td>{d.polsby_popper.toFixed(2)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>

                <details className="modal-run-params">
                  <summary>Run parameters</summary>
                  <div className="kv-grid">
                    <KV k="Seed strategy" v={plan.seed_strategy} />
                    <KV k="ε (tolerance)" v={`${(plan.epsilon * 100).toFixed(2)}%`} />
                    <KV k="Chain length" v={plan.chain_length} />
                    <KV k="Random seed" v={plan.random_seed} />
                    <KV k="Plan ID" v={<code>{plan.plan_id.slice(0, 8)}…</code>} />
                  </div>
                </details>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="kv">
      <span className="kv-key">{k}</span>
      <span className="kv-val">{v}</span>
    </div>
  );
}

/** Inline SVG choropleth of one state's districts, with numeric labels matching
 *  the per-district table below.
 *
 *  Label-anti-collision: districts whose centroids are closer than the label radius
 *  get pushed apart by force-directed relaxation; leader lines connect each
 *  displaced label back to its district centroid. Avoids overlap in busy states
 *  like Texas, Massachusetts, New Jersey. */
function StateDistrictMap({ fc }: { fc: GeoJSON.FeatureCollection }) {
  const W = 800;
  const H = 540;
  const projection = useMemo(() => geoMercator().fitSize([W, H], fc), [fc]);
  const pathGen = useMemo(() => geoPath(projection), [projection]);

  // Compute label positions with anti-collision.
  const labels = useMemo(() => {
    const initial = fc.features.map((f, i) => {
      const did = (f.properties as { district?: number } | null)?.district ?? i;
      const c = pathGen.centroid(f);
      const valid = !isNaN(c[0]) && !isNaN(c[1]);
      return {
        id: did,
        idx: i,
        pin: valid ? [c[0], c[1]] : [W / 2, H / 2],
        pos: valid ? [c[0], c[1]] : [W / 2, H / 2],
      };
    });
    const MIN_DIST = 30; // label radius pad in px
    for (let iter = 0; iter < 80; iter++) {
      let moved = false;
      for (let i = 0; i < initial.length; i++) {
        for (let j = i + 1; j < initial.length; j++) {
          const dx = initial[j].pos[0] - initial[i].pos[0];
          const dy = initial[j].pos[1] - initial[i].pos[1];
          const d = Math.hypot(dx, dy);
          if (d < MIN_DIST && d > 0.01) {
            const push = (MIN_DIST - d) / 2;
            const nx = dx / d;
            const ny = dy / d;
            initial[i].pos[0] -= nx * push;
            initial[i].pos[1] -= ny * push;
            initial[j].pos[0] += nx * push;
            initial[j].pos[1] += ny * push;
            moved = true;
          }
        }
      }
      // Pull labels back toward their pin (so they don't drift far).
      for (const l of initial) {
        const dx = l.pin[0] - l.pos[0];
        const dy = l.pin[1] - l.pos[1];
        l.pos[0] += dx * 0.05;
        l.pos[1] += dy * 0.05;
      }
      // Clamp to canvas bounds.
      for (const l of initial) {
        l.pos[0] = Math.max(16, Math.min(W - 16, l.pos[0]));
        l.pos[1] = Math.max(16, Math.min(H - 16, l.pos[1]));
      }
      if (!moved) break;
    }
    return initial;
  }, [fc, pathGen]);

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="state-district-svg">
      {/* District polygons */}
      {fc.features.map((f, i) => {
        const did = (f.properties as { district?: number } | null)?.district ?? i;
        const color = DISTRICT_PALETTE[did % DISTRICT_PALETTE.length];
        const d = pathGen(f) ?? '';
        return <path key={i} d={d} fill={color} stroke="#fff" strokeWidth={1} />;
      })}
      {/* Leader lines (only drawn when label was displaced) */}
      {labels.map((l) => {
        const dx = l.pos[0] - l.pin[0];
        const dy = l.pos[1] - l.pin[1];
        if (Math.hypot(dx, dy) < 4) return null;
        return (
          <line
            key={`line-${l.idx}`}
            x1={l.pin[0]}
            y1={l.pin[1]}
            x2={l.pos[0]}
            y2={l.pos[1]}
            stroke="#0f172a"
            strokeWidth={1}
            opacity={0.55}
          />
        );
      })}
      {/* Pin dots */}
      {labels.map((l) => (
        <circle
          key={`pin-${l.idx}`}
          cx={l.pin[0]}
          cy={l.pin[1]}
          r={2}
          fill="#0f172a"
        />
      ))}
      {/* Numbered chips */}
      {labels.map((l) => (
        <g
          key={`chip-${l.idx}`}
          transform={`translate(${l.pos[0]},${l.pos[1]})`}
          pointerEvents="none"
        >
          <circle r={13} fill="#0f172a" stroke="#fff" strokeWidth={2} opacity={0.92} />
          <text
            textAnchor="middle"
            dominantBaseline="central"
            fontSize={12}
            fontWeight={700}
            fill="#fff"
          >
            {l.id + 1}
          </text>
        </g>
      ))}
    </svg>
  );
}
