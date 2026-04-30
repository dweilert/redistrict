/**
 * Modal that lists all states matching a "kind" (done / running / failed / skipped /
 * total) with their seat counts (= number of districts). Triggered by clicking the
 * counter tiles on the LiveBatchView.
 */
import type { StateStatus } from './api';

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

export type CounterKind = 'total' | 'done' | 'running' | 'failed' | 'skipped';

interface Props {
  kind: CounterKind;
  statuses: StateStatus[];
  onClose: () => void;
  onStateClick?: (usps: string) => void;
}

const KIND_TITLES: Record<CounterKind, string> = {
  total: 'All states',
  done: 'Completed states',
  running: 'In-progress states',
  failed: 'Failed states',
  skipped: 'Single-seat states (whole state = one district)',
};

function matches(kind: CounterKind, s: StateStatus): boolean {
  switch (kind) {
    case 'total':
      return true;
    case 'done':
      return s.phase === 'done';
    case 'running':
      return ['loading', 'graph', 'districting'].includes(s.phase);
    case 'failed':
      return s.phase === 'failed';
    case 'skipped':
      return ['skipped', 'queued_skip'].includes(s.phase);
  }
}

export function CounterModal({ kind, statuses, onClose, onStateClick }: Props) {
  const items = statuses
    .filter((s) => matches(kind, s))
    .sort((a, b) => a.usps.localeCompare(b.usps));

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{KIND_TITLES[kind]}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="modal-meta">
          {items.length} state{items.length === 1 ? '' : 's'} — total districts:{' '}
          <strong>{items.reduce((acc, s) => acc + (s.seats ?? 0), 0)}</strong>
        </div>
        <table className="modal-table">
          <thead>
            <tr>
              <th>State</th>
              <th>Districts</th>
              <th>Phase</th>
              <th>Max |dev| %</th>
              <th>PP</th>
              <th>Splits</th>
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.usps} className="row-clickable"
                  onClick={() => onStateClick?.(s.usps)}>
                <td>
                  <strong>{s.usps}</strong>{' '}
                  <span className="muted">{STATE_NAMES[s.usps] ?? ''}</span>
                </td>
                <td><strong>{s.seats ?? '—'}</strong></td>
                <td><span className={`phase phase-${s.phase}`}>{s.phase}</span></td>
                <td>{s.max_abs_deviation_pct?.toFixed(4) ?? '—'}</td>
                <td>{s.polsby_popper_mean?.toFixed(3) ?? '—'}</td>
                <td>{s.county_splits ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
