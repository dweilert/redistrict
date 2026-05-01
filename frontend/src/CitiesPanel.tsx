/**
 * Cities-in-district panel. Generic over which fetcher to use so the same UI
 * works for nationwide-batch results (per-batch GPKG) and single-plan results
 * (in-memory assignment).
 */
import { useQuery } from '@tanstack/react-query';
import { DISTRICT_PALETTE } from './DistrictMap';

interface City {
  name: string;
  kind: string;
  population: number;
  area_sqmi: number;
}

interface Props {
  district: number;
  queryKey: ReadonlyArray<string | number>;
  fetcher: () => Promise<{ cities: City[] }>;
  onClose: () => void;
}

export function CitiesPanel({ district, queryKey, fetcher, onClose }: Props) {
  const cities = useQuery({
    queryKey: [...queryKey],
    queryFn: fetcher,
    retry: false,
  });
  const color = DISTRICT_PALETTE[district % DISTRICT_PALETTE.length];

  return (
    <div className="cities-panel">
      <div className="cities-header">
        <span className="district-swatch"
              style={{ background: color, width: 18, height: 18 }} />
        <strong>District {district + 1}</strong>
        <span className="muted">— cities & places</span>
        <button className="link-btn" onClick={onClose}
                style={{ marginLeft: 'auto' }}>✕ close</button>
      </div>
      {cities.isLoading && <p className="muted small">Loading places…</p>}
      {cities.error && <p className="err small">Could not load places.</p>}
      {cities.data && cities.data.cities.length === 0 && (
        <p className="muted small">No incorporated places found in this district.</p>
      )}
      {cities.data && cities.data.cities.length > 0 && (
        <ul className="cities-list">
          {cities.data.cities.map((c, i) => (
            <li key={i} title={`${c.area_sqmi.toFixed(1)} sq mi`}>
              <span className="city-name">{c.name}</span>
              {c.kind && <span className="muted small">({c.kind})</span>}
              <span style={{ marginLeft: 'auto', fontVariantNumeric: 'tabular-nums' }}>
                {c.population > 0
                  ? c.population.toLocaleString()
                  : <span className="muted small">—</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
