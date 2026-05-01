/**
 * Modal dialog showing one state's details: phase, totals, and the per-district
 * scorecard (population, deviation %, area, compactness).
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, type StateStatus } from './api';
import { DistrictMap, DISTRICT_PALETTE } from './DistrictMap';
import { CitiesPanel } from './CitiesPanel';

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

interface Props {
  batchId: string;
  usps: string;
  status?: StateStatus;
  manifest?: { unit: string; epsilon: number; chain_length: number };
  onTune?: (usps: string) => void;
  onClose: () => void;
}

export function StateDetailModal({ batchId, usps, status, manifest, onTune, onClose }: Props) {
  const [showLabels, setShowLabels] = useState(true);
  const [selectedDistrict, setSelectedDistrict] = useState<number | null>(null);
  const [overlayOpacity, setOverlayOpacity] = useState(0); // 0–100, 0 = no overlay
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
  // Official current (119th Congress) districts — only fetched once we
  // start showing the overlay (>0 opacity).
  const officialQuery = useQuery({
    queryKey: ['cd119', usps],
    queryFn: () => api.stateCD119(usps),
    enabled: overlayOpacity > 0,
    staleTime: 24 * 60 * 60 * 1000,
    retry: false,
  });
  const officialScorecardQuery = useQuery({
    queryKey: ['cd119-scorecard', usps],
    queryFn: () => api.stateCD119Scorecard(usps),
    enabled: overlayOpacity > 0,
    staleTime: 24 * 60 * 60 * 1000,
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
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {onTune && (
              <button
                onClick={() => onTune(usps)}
                title="Open the single-state generator pre-filled with this state's settings"
              >
                ⚙ Tune this state
              </button>
            )}
            <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
          </div>
        </div>

        <div className="modal-state-body">
          {/* LEFT: big district map */}
          <div className="modal-state-map">
            <div className="state-map-toolbar">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={showLabels}
                  onChange={(e) => setShowLabels(e.target.checked)}
                />
                Show district numbers
              </label>
            </div>
            <div className="overlay-toggle">
              <span title="Overlays the state's officially-adopted current U.S. House districts (119th Congress) on top of the generated plan. Drag the slider to fade between the two.">
                Current US House districts
              </span>
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={overlayOpacity}
                onChange={(e) => setOverlayOpacity(parseInt(e.target.value))}
              />
              <span className="muted small" style={{ minWidth: 36 }}>
                {overlayOpacity}%
              </span>
            </div>
            {districtsFC ? (
              <DistrictMap
                fc={districtsFC}
                overlayFC={officialQuery.data}
                overlayOpacity={overlayOpacity / 100}
                showLabels={showLabels}
                selectedDistrict={selectedDistrict}
                onDistrictClick={setSelectedDistrict}
              />
            ) : status?.phase === 'done' ? (
              <div className="muted center-pad">Loading districts…</div>
            ) : (
              <div className="muted center-pad">No districts to draw.</div>
            )}
          </div>

          {/* RIGHT: data panels */}
          <div className="modal-state-info">
            {selectedDistrict !== null && (
              <CitiesPanel
                district={selectedDistrict}
                queryKey={['cities', batchId, usps, String(selectedDistrict)]}
                fetcher={() => api.districtCities(batchId, usps, selectedDistrict)}
                onClose={() => setSelectedDistrict(null)}
              />
            )}
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

                {officialScorecardQuery.data?.available && (
                  <>
                    <h3>Generated vs. current (119th Congress)</h3>
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
                          <td>{sc.max_abs_deviation_pct.toFixed(4)}%</td>
                          <td>{officialScorecardQuery.data.max_abs_deviation_pct?.toFixed(4)}%</td>
                        </tr>
                        <tr>
                          <td>Polsby–Popper mean</td>
                          <td>{sc.polsby_popper_mean.toFixed(3)}</td>
                          <td>{officialScorecardQuery.data.polsby_popper_mean?.toFixed(3)}</td>
                        </tr>
                        <tr>
                          <td>County splits</td>
                          <td>{sc.county_splits}</td>
                          <td>{officialScorecardQuery.data.county_splits}</td>
                        </tr>
                      </tbody>
                    </table>
                  </>
                )}

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
