/**
 * Banner that polls /api/census-files on app start and warns the user when a
 * newer version of any Census source file is available upstream. Each file has
 * a one-click "Update now" button.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';

export function UpdateBanner() {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ['census-files'],
    queryFn: () => api.censusFiles(),
    // Check once on app start; user can manually re-check via the Update button.
    staleTime: 60 * 60 * 1000,
    refetchOnMount: 'always',
  });

  const dl = useMutation({
    mutationFn: (key: string) => api.downloadCensusFile(key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['census-files'] }),
  });

  if (!status.data) return null;
  const stale = status.data.filter((f) => f.update_available);
  if (stale.length === 0) return null;

  return (
    <div className="update-banner">
      <strong>📥 New Census data available</strong>
      <span className="muted small">
        Background data files have updates upstream — download to refresh.
      </span>
      <ul>
        {stale.map((f) => (
          <li key={f.key}>
            <span>
              <strong>{f.label}</strong> — {f.why}
              {f.local_last_modified && (
                <span className="muted small">
                  {' '}
                  (you have: {f.local_last_modified})
                </span>
              )}
            </span>
            <button
              onClick={() => dl.mutate(f.key)}
              disabled={dl.isPending && dl.variables === f.key}
            >
              {dl.isPending && dl.variables === f.key
                ? 'Downloading…'
                : 'Update now'}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
