/**
 * Shared interactive district map.
 *
 * Used both in StateDetailModal (nationwide-batch state click) and SinglePlanView
 * (single-state generator result). Features:
 *
 *   - Numbered district chips with force-directed anti-collision so labels in
 *     dense states (TX, MA, NJ) don't overlap. Connected back to the district
 *     centroid by a leader line when the chip has been displaced.
 *   - "Show district numbers" toggle.
 *   - Click any district → highlight it + emit selectedDistrict.
 *   - Optional overlay layer (e.g. official 119th-Congress districts) drawn on
 *     top with a controllable opacity (filled pale color + dashed outline so
 *     boundaries are easy to compare).
 */
import { useMemo } from 'react';
import { geoMercator, geoPath } from 'd3-geo';

export const DISTRICT_PALETTE = [
  '#4E79A7', '#F28E2B', '#E15759', '#76B7B2', '#59A14F',
  '#EDC948', '#B07AA1', '#FF9DA7', '#9C755F', '#BAB0AC',
  '#1F77B4', '#D62728', '#2CA02C', '#9467BD', '#8C564B',
  '#E377C2', '#17BECF', '#BCBD22', '#7F7F7F', '#AEC7E8',
];

interface Props {
  fc: GeoJSON.FeatureCollection;
  /** Optional secondary feature collection drawn on top with controlled opacity. */
  overlayFC?: GeoJSON.FeatureCollection;
  overlayOpacity?: number;
  showLabels?: boolean;
  selectedDistrict?: number | null;
  onDistrictClick?: (district: number) => void;
  /** SVG viewbox dimensions; default 800×540 fits well in modal width. */
  width?: number;
  height?: number;
  className?: string;
}

export function DistrictMap({
  fc,
  overlayFC,
  overlayOpacity = 0,
  showLabels = true,
  selectedDistrict = null,
  onDistrictClick,
  width = 800,
  height = 540,
  className = 'state-district-svg',
}: Props) {
  const projection = useMemo(() => geoMercator().fitSize([width, height], fc),
                             [fc, width, height]);
  const pathGen = useMemo(() => geoPath(projection), [projection]);

  // Force-directed label placement.
  const labels = useMemo(() => {
    const initial = fc.features.map((f, i) => {
      const did = (f.properties as { district?: number } | null)?.district ?? i;
      const c = pathGen.centroid(f);
      const valid = !isNaN(c[0]) && !isNaN(c[1]);
      return {
        id: did,
        idx: i,
        pin: valid ? [c[0], c[1]] : [width / 2, height / 2],
        pos: valid ? [c[0], c[1]] : [width / 2, height / 2],
      };
    });
    const MIN_DIST = 22;
    for (let iter = 0; iter < 80; iter++) {
      let moved = false;
      for (let i = 0; i < initial.length; i++) {
        for (let j = i + 1; j < initial.length; j++) {
          const dx = initial[j].pos[0] - initial[i].pos[0];
          const dy = initial[j].pos[1] - initial[i].pos[1];
          const d = Math.hypot(dx, dy);
          if (d < MIN_DIST && d > 0.01) {
            const push = (MIN_DIST - d) / 2;
            const nx = dx / d, ny = dy / d;
            initial[i].pos[0] -= nx * push;
            initial[i].pos[1] -= ny * push;
            initial[j].pos[0] += nx * push;
            initial[j].pos[1] += ny * push;
            moved = true;
          }
        }
      }
      for (const l of initial) {
        l.pos[0] += (l.pin[0] - l.pos[0]) * 0.05;
        l.pos[1] += (l.pin[1] - l.pos[1]) * 0.05;
        l.pos[0] = Math.max(16, Math.min(width - 16, l.pos[0]));
        l.pos[1] = Math.max(16, Math.min(height - 16, l.pos[1]));
      }
      if (!moved) break;
    }
    return initial;
  }, [fc, pathGen, width, height]);

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} className={className}>
      {/* Generated district polygons */}
      {fc.features.map((f, i) => {
        const did = (f.properties as { district?: number } | null)?.district ?? i;
        const color = DISTRICT_PALETTE[did % DISTRICT_PALETTE.length];
        const d = pathGen(f) ?? '';
        const isSelected = selectedDistrict === did;
        return (
          <path
            key={i}
            d={d}
            fill={color}
            stroke={isSelected ? '#0f172a' : '#fff'}
            strokeWidth={isSelected ? 3 : 1}
            opacity={selectedDistrict !== null && !isSelected ? 0.55 : 1}
            style={{ cursor: 'pointer' }}
            onClick={() => onDistrictClick?.(did)}
          />
        );
      })}

      {/* Overlay layer (e.g. official current districts).
          White fill at the chosen opacity so the underlying generated colors
          fade evenly behind it; dashed black outlines on top mark the
          boundaries clearly. */}
      {overlayOpacity > 0 && overlayFC && overlayFC.features.map((f, i) => {
        const d = pathGen(f) ?? '';
        return (
          <g key={`overlay-${i}`} pointerEvents="none">
            <path d={d} fill="#ffffff" fillOpacity={0.85 * overlayOpacity}
                  stroke="none" />
            <path d={d} fill="none" stroke="#0f172a" strokeWidth={2}
                  strokeDasharray="6 4" opacity={overlayOpacity} />
          </g>
        );
      })}

      {/* Leader lines */}
      {showLabels && labels.map((l) => {
        const dx = l.pos[0] - l.pin[0];
        const dy = l.pos[1] - l.pin[1];
        if (Math.hypot(dx, dy) < 4) return null;
        return (
          <line key={`line-${l.idx}`}
                x1={l.pin[0]} y1={l.pin[1]}
                x2={l.pos[0]} y2={l.pos[1]}
                stroke="#0f172a" strokeWidth={1} opacity={0.55} />
        );
      })}
      {/* Pin dots */}
      {showLabels && labels.map((l) => (
        <circle key={`pin-${l.idx}`} cx={l.pin[0]} cy={l.pin[1]}
                r={2} fill="#0f172a" />
      ))}
      {/* Numbered chips */}
      {showLabels && labels.map((l) => (
        <g key={`chip-${l.idx}`}
           transform={`translate(${l.pos[0]},${l.pos[1]})`}
           pointerEvents="none">
          <circle r={10} fill="#0f172a" stroke="#fff" strokeWidth={1.5}
                  opacity={0.92} />
          <text textAnchor="middle" dominantBaseline="central"
                fontSize={10} fontWeight={700} fill="#fff">
            {l.id + 1}
          </text>
        </g>
      ))}
    </svg>
  );
}
