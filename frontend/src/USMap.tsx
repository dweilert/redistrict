/**
 * Live US choropleth.
 *
 * - Renders all 50 states as SVG paths via d3-geo (Albers USA projection).
 * - Color = phase from per-state status. "done" states optionally show their actual
 *   district choropleth (fetched lazily and cached).
 * - Pure React + d3-geo. No flicker, no full-page reruns. State updates only repaint
 *   the affected paths.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { geoAlbersUsa, geoPath } from 'd3-geo';
import { useQueries, useQuery } from '@tanstack/react-query';
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

interface Props {
  batchId: string;
  statuses: StateStatus[];
  showDistricts: boolean;
  onStateClick?: (usps: string) => void;
}

export function USMap({ batchId, statuses, showDistricts, onStateClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [{ width, height }, setSize] = useState({ width: 1100, height: 660 });
  // Zoom + pan state (transform on an inner <g>).
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [drag, setDrag] = useState<{ x: number; y: number; px: number; py: number; moved: boolean } | null>(null);
  // "Hold ⌘/Ctrl to zoom" hint, auto-clears after a couple seconds.
  const [zoomHint, setZoomHint] = useState(false);

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

  // Districts per "done" state — fetched in parallel, cached, only when showDistricts.
  const doneStates = useMemo(
    () => statuses.filter((s) => s.phase === 'done').map((s) => s.usps),
    [statuses]
  );

  const districtQueries = useQueries({
    queries: doneStates.map((usps) => ({
      queryKey: ['districts', batchId, usps],
      queryFn: () => api.stateDistricts(batchId, usps),
      enabled: showDistricts,
      staleTime: 60 * 60 * 1000,
      retry: false,
    })),
  });

  const districtsByUsps = useMemo(() => {
    const m: Record<string, GeoJSON.FeatureCollection> = {};
    doneStates.forEach((usps, i) => {
      const q = districtQueries[i];
      if (q?.data) m[usps] = q.data;
    });
    return m;
  }, [doneStates, districtQueries]);

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
          e.preventDefault();
          if (e.deltaY < 0) zoomIn();
          else zoomOut();
        }}
      >
        <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>
        {statesQuery.data.features.map((feature) => {
          const usps = (feature.properties as { usps?: string } | null)?.usps;
          if (!usps) return null;
          const phase = phaseByUsps[usps] ?? 'queued';
          const districtFC = districtsByUsps[usps];

          const stateOutlinePath = pathGen(feature) ?? '';
          // Center for label
          const centroid = pathGen.centroid(feature);

          const showRealDistricts = showDistricts && phase === 'done' && districtFC;

          return (
            <g
              key={usps}
              onClick={() => {
                // Suppress click if user just dragged.
                if (drag?.moved) return;
                onStateClick?.(usps);
              }}
              style={{ cursor: 'pointer' }}
            >
              {showRealDistricts ? (
                <>
                  {districtFC.features.map((df, i) => (
                    <path
                      key={i}
                      d={pathGen(df) ?? ''}
                      fill={DISTRICT_PALETTE[
                        ((df.properties as { district?: number } | null)?.district ?? i) %
                          DISTRICT_PALETTE.length
                      ]}
                      stroke="#fff"
                      strokeWidth={0.6}
                    />
                  ))}
                  {/* Outline state border on top so neighbors are clearly delimited. */}
                  <path
                    d={stateOutlinePath}
                    fill="none"
                    stroke="#1e293b"
                    strokeWidth={0.7}
                  />
                </>
              ) : (
                <path
                  d={stateOutlinePath}
                  fill={PHASE_COLORS[phase] ?? '#fff'}
                  stroke="#1e293b"
                  strokeWidth={0.6}
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
