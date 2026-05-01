/**
 * Catalog tab: lists every saved plan for a state (plus the always-on Census
 * current entry) with set-default / view / delete actions.
 *
 * Used both inside the nationwide state-detail modal and the single-state
 * result view, so the parent passes:
 *   - selectedPlanUuid: which entry the map is currently showing
 *   - onSelect(planUuid): switch the map to a different entry
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';

interface Props {
  usps: string;
  selectedPlanUuid: string | null;
  onSelect: (planUuid: string) => void;
}

export function CatalogPanel({ usps, selectedPlanUuid, onSelect }: Props) {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ['catalog', usps],
    queryFn: () => api.catalogList(usps),
    staleTime: 10_000,
  });

  const setDefault = useMutation({
    mutationFn: (plan_uuid: string) => api.catalogSetDefault(usps, plan_uuid),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['catalog', usps] }),
  });
  const del = useMutation({
    mutationFn: (plan_uuid: string) => api.catalogDelete(usps, plan_uuid),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['catalog', usps] }),
  });

  if (!list.data) return <div className="muted small">Loading catalog…</div>;
  const def = list.data.default_plan_uuid;

  return (
    <div className="catalog-panel">
      <div className="catalog-header">
        <strong>Catalog for {usps}</strong>
        <span className="muted small">{list.data.entries.length} entries</span>
      </div>
      <ul className="catalog-list">
        {list.data.entries.map((e) => {
          const isDefault = e.plan_uuid === def;
          const isSelected = e.plan_uuid === selectedPlanUuid;
          const sc = e.scorecard as {
            available?: boolean;
            max_abs_deviation_pct?: number;
            polsby_popper_mean?: number;
            county_splits?: number;
          };
          return (
            <li
              key={e.plan_uuid}
              className={`catalog-row ${isSelected ? 'selected' : ''}`}
            >
              <div className="catalog-row-main">
                <div className="catalog-row-name">
                  {isDefault && <span className="default-star" title="Current default">⭐</span>}
                  <span className={`catalog-source-badge src-${e.source}`}>
                    {e.source === 'census' ? '🇺🇸 Census' :
                      e.source === 'nationwide' ? '🌐 Nationwide' :
                      '🔧 Tuned'}
                  </span>
                  <span className="catalog-name">{e.name}</span>
                </div>
                <div className="catalog-row-stats muted small">
                  {sc.max_abs_deviation_pct !== undefined &&
                    <>dev {sc.max_abs_deviation_pct.toFixed(3)}% · </>}
                  {sc.polsby_popper_mean !== undefined &&
                    <>PP {sc.polsby_popper_mean.toFixed(3)} · </>}
                  {sc.county_splits !== undefined &&
                    <>splits {sc.county_splits}</>}
                  {e.created_at && <> · {e.created_at.replace('T', ' ').slice(0, 16)}</>}
                </div>
              </div>
              <div className="catalog-row-actions">
                <button
                  onClick={() => onSelect(e.plan_uuid)}
                  className={isSelected ? 'active' : ''}
                  title="Show this plan on the map"
                >
                  {isSelected ? '✓ viewing' : 'view'}
                </button>
                {!isDefault && (
                  <button
                    onClick={() => setDefault.mutate(e.plan_uuid)}
                    disabled={setDefault.isPending}
                    title="Make this the state's default plan (used in the nationwide 'Catalog defaults' view)"
                  >
                    set default
                  </button>
                )}
                {e.source !== 'census' && (
                  <button
                    onClick={() => {
                      if (confirm(`Delete '${e.name}'?`)) del.mutate(e.plan_uuid);
                    }}
                    disabled={del.isPending}
                    className="danger"
                    title="Remove this entry from the catalog"
                  >
                    delete
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
