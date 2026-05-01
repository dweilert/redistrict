/**
 * Live state preview shown while the chain runs.
 *
 *  - Until the first ReCom proposal lands a "best plan", we paint the state
 *    outline with an animated sweep gradient so the user sees the actual shape
 *    of the state, not a generic blue box.
 *  - Once the backend has a best assignment, the dissolved districts geojson
 *    replaces the outline, with a quick crossfade. Each subsequent preview
 *    poll updates the colors in place — districts visibly evolve as the chain
 *    finds better cuts.
 *  - Big state name + step counter overlaid as floating chips.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { geoMercator, geoPath } from 'd3-geo';
import { api } from './api';
import { DISTRICT_PALETTE } from './DistrictMap';

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

interface Props {
  planId: string;
  usps: string;
  step: number;
  chainLength: number;
  bestMaxDev: number | null;
  bestPP: number | null;
  hasFirstBest: boolean;
  isRunning: boolean;
}

export function LiveStatePreview({
  planId, usps, step, chainLength, bestMaxDev, bestPP, hasFirstBest, isRunning,
}: Props) {
  // Fetch state outlines once — used as the placeholder shape until districts arrive.
  const states = useQuery({
    queryKey: ['states-geojson'],
    queryFn: () => api.statesGeoJSON(),
    staleTime: 60 * 60 * 1000,
  });

  // Live evolving district preview (only fetched once we have a first best).
  const preview = useQuery({
    queryKey: ['single-preview', planId],
    queryFn: () => api.singlePlanPreview(planId),
    enabled: isRunning && hasFirstBest,
    refetchInterval: isRunning ? 4000 : false,
    retry: false,
  });

  // Single-state subset of the national outlines.
  const stateFC = useMemo(() => {
    if (!states.data) return null;
    const f = states.data.features.find(
      (x) => (x.properties as { usps?: string } | null)?.usps === usps
    );
    return f
      ? ({ type: 'FeatureCollection', features: [f] } as GeoJSON.FeatureCollection)
      : null;
  }, [states.data, usps]);

  const W = 800;
  const H = 480;

  // Project either the preview districts (if available) or the state outline.
  const fcForProjection = preview.data ?? stateFC;
  const projection = useMemo(
    () =>
      fcForProjection ? geoMercator().fitSize([W, H], fcForProjection) : null,
    [fcForProjection]
  );
  const pathGen = useMemo(
    () => (projection ? geoPath(projection) : null),
    [projection]
  );

  const fullName = STATE_NAMES[usps] ?? usps;
  const pct = Math.min(100, (step / chainLength) * 100);

  return (
    <div className="live-preview-card">
      {/* Floating header chips */}
      <div className="live-chips">
        <span className="chip chip-state">{fullName}</span>
        <span className="chip chip-step">
          step <strong>{step}</strong> / {chainLength}
        </span>
        {bestMaxDev !== null && (
          <span className="chip chip-metric">
            best |dev| <strong>{bestMaxDev.toFixed(3)}%</strong>
          </span>
        )}
        {bestPP !== null && (
          <span className="chip chip-metric">
            best PP <strong>{bestPP.toFixed(3)}</strong>
          </span>
        )}
      </div>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="live-svg">
        <defs>
          <linearGradient id="sweep" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#dbeafe">
              <animate
                attributeName="stop-color"
                values="#dbeafe; #93c5fd; #dbeafe"
                dur="2.4s"
                repeatCount="indefinite"
              />
            </stop>
            <stop offset="50%" stopColor="#60a5fa">
              <animate
                attributeName="stop-color"
                values="#60a5fa; #3b82f6; #60a5fa"
                dur="2.4s"
                repeatCount="indefinite"
              />
            </stop>
            <stop offset="100%" stopColor="#dbeafe">
              <animate
                attributeName="stop-color"
                values="#dbeafe; #93c5fd; #dbeafe"
                dur="2.4s"
                repeatCount="indefinite"
              />
            </stop>
          </linearGradient>
        </defs>

        {/* Render evolving districts if we have them */}
        {preview.data && pathGen && preview.data.features.map((f, i) => {
          const did =
            (f.properties as { district?: number } | null)?.district ?? i;
          return (
            <path
              key={`d-${i}-${preview.data?._step}`}
              d={pathGen(f) ?? ''}
              fill={DISTRICT_PALETTE[did % DISTRICT_PALETTE.length]}
              stroke="#fff"
              strokeWidth={1}
              className="evolving-district"
            />
          );
        })}

        {/* Otherwise render the state outline with an animated gradient */}
        {!preview.data && stateFC && pathGen && stateFC.features.map((f, i) => (
          <path
            key={`outline-${i}`}
            d={pathGen(f) ?? ''}
            fill="url(#sweep)"
            stroke="#1d4ed8"
            strokeWidth={1.5}
            className="outline-pulse"
          />
        ))}

        {/* Always overlay the state border on top so the silhouette reads. */}
        {stateFC && pathGen && stateFC.features.map((f, i) => (
          <path
            key={`border-${i}`}
            d={pathGen(f) ?? ''}
            fill="none"
            stroke="#1e293b"
            strokeWidth={1.5}
            opacity={0.35}
          />
        ))}
      </svg>

      {/* Bottom progress bar */}
      <div className="live-progressbar">
        <div className="live-progressbar-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="live-status-line">
        {!hasFirstBest ? (
          <>
            <span className="spinner" />
            Searching for first valid plan…
          </>
        ) : preview.isFetching ? (
          <>
            <span className="spinner" />
            Updating preview…
          </>
        ) : (
          <>Best plan after step {step} — districts evolve as the chain finds better cuts.</>
        )}
      </div>
    </div>
  );
}
