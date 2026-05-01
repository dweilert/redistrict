/**
 * Live US choropleth.
 *
 * - Renders all 50 states as SVG paths via d3-geo (Albers USA projection).
 * - Color = phase from per-state status. "done" states optionally show their actual
 *   district choropleth (fetched lazily and cached).
 * - Pure React + d3-geo. No flicker, no full-page reruns. State updates only repaint
 *   the affected paths.
 */
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { geoAlbersUsa, geoPath } from 'd3-geo';
import { useQuery } from '@tanstack/react-query';
import { api, type StateStatus } from './api';

export const PHASE_COLORS: Record<string, string> = {
  queued: '#cbd5e1',
  // Single-seat states are "complete" by definition (the whole state is the one
  // district) — show as a light green to look done.
  queued_skip: '#86efac',
  skipped: '#86efac',
  loading: '#f59e0b',
  graph: '#f59e0b',
  districting: '#f59e0b',
  done: '#10b981',
  failed: '#ef4444',
};

const DISTRICT_PALETTE = [
  '#4E79A7', '#F28E2B', '#E15759', '#76B7B2', '#59A14F',
  '#EDC948', '#B07AA1', '#FF9DA7', '#9C755F', '#BAB0AC',
  '#1F77B4', '#D62728', '#2CA02C', '#9467BD', '#8C564B',
  '#E377C2', '#17BECF', '#BCBD22', '#7F7F7F', '#AEC7E8',
];

/** Where the per-state district choropleths come from:
 *   'batch'    — currently active batch's per-state plans
 *   'defaults' — composed from each state's catalog default
 *   'census'   — official 119th-Congress districts for every state
 */
export type NationwideSource = 'batch' | 'defaults' | 'census';

interface Props {
  batchId: string;
  statuses: StateStatus[];
  showDistricts: boolean;
  source?: NationwideSource;
  onStateClick?: (usps: string) => void;
  highlightUsps?: string | null;
}

// Memoized below so a parent state change (e.g. opening overlay) doesn't trigger
// a full re-render of all 50 states' SVG paths.
function USMapImpl({
  batchId,
  statuses,
  showDistricts,
  source = 'batch',
  onStateClick,
  highlightUsps,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [{ width, height }, setSize] = useState({ width: 1100, height: 660 });
  // Zoom + pan state (transform on an inner <g>).
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [drag, setDrag] = useState<{ x: number; y: number; px: number; py: number; moved: boolean } | null>(null);
  // "Hold ⌘/Ctrl to zoom" hint, auto-clears after a couple seconds.
  const [zoomHint, setZoomHint] = useState(false);
  // Timestamp of the last wheel event — used to suppress click-state
  // selection when the user is wheel-zooming (so a stray click during the
  // scroll gesture doesn't open a state's modal).
  const lastWheelAt = useRef(0);

  function zoomIn() {
    setZoom((z) => Math.min(8, z * 1.4));
  }
  function zoomOut() {
    setZoom((z) => {
      const next = Math.max(1, z / 1.4);
      if (next === 1) setPan({ x: 0, y: 0 });
      return next;
    });
  }
  function resetView() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }
  /** Zoom about a point so the location under (anchorX, anchorY) stays put. */
  function zoomAt(anchorX: number, anchorY: number, factor: number) {
    setZoom((z) => {
      const next = Math.max(1, Math.min(8, z * factor));
      // Solve for new pan that keeps (ax, ay) fixed under the SVG transform.
      // The transform is: x' = pan.x + scale * x_world. We want the world
      // point at (ax, ay) before to map to (ax, ay) after. With p_old, z_old:
      //   ax = pan.x_old + z_old * x_w → x_w = (ax - pan.x_old) / z_old
      //   ax = pan.x_new + z_new * x_w → pan.x_new = ax - z_new * x_w
      setPan((p) => {
        if (next === 1) return { x: 0, y: 0 };
        const xw = (anchorX - p.x) / z;
        const yw = (anchorY - p.y) / z;
        return { x: anchorX - next * xw, y: anchorY - next * yw };
      });
      return next;
    });
  }

  // Track container size so the map fills the panel.
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(() => {
      const el = containerRef.current;
      if (!el) return;
      setSize({
        width: el.clientWidth,
        height: Math.max(420, el.clientWidth * 0.6),
      });
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // Static state outlines.
  const statesQuery = useQuery({
    queryKey: ['states-geojson'],
    queryFn: () => api.statesGeoJSON(),
    staleTime: 60 * 60 * 1000,
  });

  // SINGLE bundled fetch of every state's districts. Endpoint depends on
  // which 'source' the user picked at the top of the nationwide view:
  //   'batch'    — districts from the currently active batch
  //   'defaults' — each state's catalog default (mostly Census, plus tunes)
  //   'census'   — every state's official 119th-Congress districts
  const allDistricts = useQuery({
    queryKey: ['all-districts', source, batchId],
    queryFn: () => {
      if (source === 'census') return api.nationwideCensus();
      if (source === 'defaults') return api.nationwideDefaults();
      return api.allDistricts(batchId);
    },
    enabled: showDistricts,
    staleTime: 60 * 60 * 1000,
    retry: false,
  });

  // Group features by usps once — memoized so we don't repeat on every render.
  const districtsByUsps = useMemo(() => {
    const m: Record<string, GeoJSON.FeatureCollection> = {};
    if (!allDistricts.data) return m;
    for (const f of allDistricts.data.features) {
      const usps = (f.properties as { usps?: string } | null)?.usps;
      if (!usps) continue;
      if (!m[usps]) m[usps] = { type: 'FeatureCollection', features: [] };
      m[usps].features.push(f);
    }
    return m;
  }, [allDistricts.data]);

  const phaseByUsps = useMemo(() => {
    const m: Record<string, string> = {};
    statuses.forEach((s) => {
      m[s.usps] = s.phase;
    });
    return m;
  }, [statuses]);

  const projection = useMemo(
    () => geoAlbersUsa().fitSize([width, height], statesQuery.data ?? { type: 'Sphere' }),
    [width, height, statesQuery.data]
  );
  const pathGen = useMemo(() => geoPath(projection), [projection]);

  // ---- Heavy path strings memoized ONCE per (projection × geojson) ----
  // d3-geo's path generator is called once per feature here; we keep the
  // resulting SVG `d` strings in a Map so the render loop is just a string
  // lookup. Without this, every re-render (TanStack poll, modal open, etc.)
  // rebuilt 400+ path strings on the main thread, causing 1.2s long tasks.
  const stateOutlinePaths = useMemo(() => {
    const m = new Map<string, string>();
    for (const f of statesQuery.data?.features ?? []) {
      const usps = (f.properties as { usps?: string } | null)?.usps;
      if (usps) m.set(usps, pathGen(f) ?? '');
    }
    return m;
  }, [statesQuery.data, pathGen]);

  const stateCentroids = useMemo(() => {
    const m = new Map<string, [number, number]>();
    for (const f of statesQuery.data?.features ?? []) {
      const usps = (f.properties as { usps?: string } | null)?.usps;
      if (usps) m.set(usps, pathGen.centroid(f) as [number, number]);
    }
    return m;
  }, [statesQuery.data, pathGen]);

  // For each done state, pre-render its district path strings.
  const districtPathsByUsps = useMemo(() => {
    const out = new Map<string, Array<{ d: string; districtId: number }>>();
    for (const [usps, fc] of Object.entries(districtsByUsps)) {
      out.set(
        usps,
        fc.features.map((df, i) => ({
          d: pathGen(df) ?? '',
          districtId:
            (df.properties as { district?: number } | null)?.district ?? i,
        })),
      );
    }
    return out;
  }, [districtsByUsps, pathGen]);

  if (!statesQuery.data) {
    return (
      <div ref={containerRef} className="us-map-loading">
        Loading state outlines…
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ width: '100%', position: 'relative' }}>
      <div className="map-zoom-controls">
        <button onClick={zoomIn} title="Zoom in">＋</button>
        <button onClick={zoomOut} title="Zoom out">−</button>
        <button onClick={resetView} title="Reset view">⟳</button>
        <span className="muted small">{(zoom * 100).toFixed(0)}%</span>
      </div>
      {zoomHint && (
        <div className="zoom-hint">
          Hold <span className="kbd">Cmd</span> (Mac) or <span className="kbd">Ctrl</span> (Win/Linux) and scroll to zoom
        </div>
      )}
      <svg
        width={width}
        height={height}
        style={{
          background: '#f8fafc',
          cursor: drag ? 'grabbing' : (zoom > 1 ? 'grab' : 'pointer'),
        }}
        onMouseDown={(e) => {
          // Track for click-vs-drag detection; allow drag only when zoomed.
          setDrag({ x: e.clientX, y: e.clientY, px: pan.x, py: pan.y, moved: false });
        }}
        onMouseMove={(e) => {
          if (!drag) return;
          const dx = e.clientX - drag.x;
          const dy = e.clientY - drag.y;
          // Only count as drag if movement exceeds threshold.
          if (!drag.moved && Math.hypot(dx, dy) < 5) return;
          if (zoom <= 1) {
            // Mark moved so the upcoming mouseup won't trigger click, but don't pan.
            setDrag({ ...drag, moved: true });
            return;
          }
          setDrag({ ...drag, moved: true });
          setPan({ x: drag.px + dx, y: drag.py + dy });
        }}
        onMouseUp={() => setDrag(null)}
        onMouseLeave={() => setDrag(null)}
        onWheel={(e) => {
          // Require modifier so plain wheel scrolls the page like normal.
          if (!(e.ctrlKey || e.metaKey)) {
            setZoomHint(true);
            window.setTimeout(() => setZoomHint(false), 2000);
            return;
          }
          // Prevent the browser's page zoom + the click-on-state that would
          // otherwise fire when the wheel lands. stopPropagation isn't enough
          // — we mark drag.moved so the upcoming click doesn't open a state.
          e.preventDefault();
          // Mark wheel time so any click that fires within the next 200ms
          // (e.g. a stray click during the zoom gesture) is ignored.
          lastWheelAt.current = performance.now();
          if (drag) setDrag({ ...drag, moved: true });
          // Anchor the zoom on the cursor position so users zoom into where
          // they're hovering, not the map's center.
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const ax = e.clientX - rect.left;
          const ay = e.clientY - rect.top;
          zoomAt(ax, ay, e.deltaY < 0 ? 1.15 : 1 / 1.15);
        }}
      >
        <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>
        {statesQuery.data.features.map((feature) => {
          const usps = (feature.properties as { usps?: string } | null)?.usps;
          if (!usps) return null;
          const phase = phaseByUsps[usps] ?? 'queued';
          const districtPaths = districtPathsByUsps.get(usps);

          const stateOutlinePath = stateOutlinePaths.get(usps) ?? '';
          const centroid = stateCentroids.get(usps) ?? [0, 0];

          const showRealDistricts =
            showDistricts && phase === 'done' && districtPaths && districtPaths.length > 0;

          return (
            <g
              key={usps}
              onClick={() => {
                // Suppress click if user just dragged OR was wheel-zooming
                // within the last 200ms (so the modifier+wheel gesture
                // doesn't accidentally pop a state modal).
                if (drag?.moved) return;
                if (performance.now() - lastWheelAt.current < 200) return;
                onStateClick?.(usps);
              }}
              style={{ cursor: 'pointer' }}
            >
              {showRealDistricts ? (
                <>
                  {districtPaths!.map((dp, i) => (
                    <path
                      key={i}
                      d={dp.d}
                      fill={DISTRICT_PALETTE[dp.districtId % DISTRICT_PALETTE.length]}
                      stroke="#fff"
                      strokeWidth={0.6}
                      pointerEvents="none"
                    />
                  ))}
                  {/* Outline state border on top so neighbors are clearly delimited.
                      THIS path catches the click; others have pointer-events: none. */}
                  <path
                    d={stateOutlinePath}
                    fill="rgba(0,0,0,0.001)" /* invisible but hit-testable */
                    stroke={highlightUsps === usps ? '#2563eb' : '#1e293b'}
                    strokeWidth={highlightUsps === usps ? 3 : 0.7}
                  />
                </>
              ) : (
                <path
                  d={stateOutlinePath}
                  fill={PHASE_COLORS[phase] ?? '#fff'}
                  stroke={highlightUsps === usps ? '#2563eb' : '#1e293b'}
                  strokeWidth={highlightUsps === usps ? 3 : 0.6}
                />
              )}

              {!isNaN(centroid[0]) && !isNaN(centroid[1]) && (
                <text
                  x={centroid[0]}
                  y={centroid[1]}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={11}
                  fontWeight={500}
                  fill="#0f172a"
                  pointerEvents="none"
                >
                  {usps}
                </text>
              )}
            </g>
          );
        })}
        </g>
      </svg>
    </div>
  );
}

export const USMap = memo(USMapImpl);

export function PhaseLegend() {
  const phases: Array<[string, string]> = [
    ['queued', 'Waiting'],
    ['districting', 'Processing'],
    ['done', 'Done'],
    ['failed', 'Failed'],
    ['skipped', '1-seat (skipped)'],
  ];
  return (
    <div className="legend">
      {phases.map(([k, label]) => (
        <span key={k} className="legend-item">
          <span className="legend-swatch" style={{ background: PHASE_COLORS[k] }} />
          {label}
        </span>
      ))}
    </div>
  );
}
