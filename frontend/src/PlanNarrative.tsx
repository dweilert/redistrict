/**
 * Plain-English narrative explaining why a plan turned out the way it did,
 * based on the weights the user picked and the resulting scorecard metrics.
 * Designed for a non-technical reader (a county commissioner, say).
 */

interface Weights {
  population_deviation?: number;
  polsby_popper?: number;
  county_splits?: number;
  cut_edges?: number;
  total_area_sqmi?: number;
  perimeter_total?: number;
  reock?: number;
  [k: string]: number | undefined;
}

interface Scorecard {
  total_population: number;
  target_population: number;
  max_abs_deviation_pct: number;
  polsby_popper_mean: number;
  county_splits: number;
  cut_edges: number;
  per_district: Array<{ district: number; population: number; deviation_pct: number; polsby_popper: number }>;
}

interface Props {
  stateName: string;
  nDistricts: number;
  epsilon: number;       // 0..1
  chainLength: number;
  seedStrategy: string;
  weights: Weights;
  scorecard: Scorecard;
}

function ppShape(pp: number): string {
  if (pp >= 0.45) return 'quite tidy / round';
  if (pp >= 0.30) return 'reasonably round';
  if (pp >= 0.20) return 'typical of real districts';
  if (pp >= 0.12) return 'somewhat irregular';
  return 'visibly stringy';
}

function devVerdict(maxDevPct: number, epsilonPct: number): string {
  if (maxDevPct < 0.1) return `extremely tight — well under the ${epsilonPct.toFixed(1)}% legal cap`;
  if (maxDevPct < 0.5) return `well within the ${epsilonPct.toFixed(1)}% legal cap`;
  if (maxDevPct < epsilonPct) return `inside the ${epsilonPct.toFixed(1)}% legal cap`;
  return `at or above the ${epsilonPct.toFixed(1)}% cap (a tighter ε would force the engine to try harder)`;
}

function rankedWeights(w: Weights): Array<{ key: string; v: number }> {
  return Object.entries(w)
    .filter(([_, v]) => (v ?? 0) > 0)
    .map(([key, v]) => ({ key, v: v as number }))
    .sort((a, b) => b.v - a.v);
}

export function PlanNarrative({ stateName, nDistricts, epsilon, chainLength, seedStrategy, weights, scorecard }: Props) {
  const epsilonPct = epsilon * 100;
  const target = scorecard.target_population;
  const maxDev = scorecard.max_abs_deviation_pct;
  const ppMean = scorecard.polsby_popper_mean;
  const splits = scorecard.county_splits;

  const ranked = rankedWeights(weights);
  const top = ranked[0];

  const popLine = (
    <>
      Each of the {nDistricts} districts was sized to about{' '}
      <strong>{target.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong>{' '}
      people. The biggest gap from that target is{' '}
      <strong>{maxDev.toFixed(3)}%</strong> — {devVerdict(maxDev, epsilonPct)}.
    </>
  );

  const ppLine = (
    <>
      The average district shape compactness (Polsby–Popper) came out to{' '}
      <strong>{ppMean.toFixed(3)}</strong> — {ppShape(ppMean)}. (1.0 would be a perfect
      circle; real congressional districts typically score 0.20–0.30.)
    </>
  );

  const countyLine = (
    <>
      The plan splits <strong>{splits}</strong> counties across district lines.{' '}
      {weights.county_splits && weights.county_splits >= 1
        ? 'The engine actively tried to keep counties whole.'
        : 'The county-splits weight was at zero, so the engine did not try to preserve county boundaries.'}
    </>
  );

  let priorityLine: React.ReactNode = null;
  if (top) {
    const friendly: Record<string, string> = {
      population_deviation: 'population balance',
      polsby_popper: 'compactness (round, tidy district shapes)',
      county_splits: 'keeping counties whole',
      cut_edges: 'smooth, non-jagged borders',
      total_area_sqmi: 'total district area',
      perimeter_total: 'total district perimeter',
      reock: 'the Reock compactness measure',
    };
    const top1 = friendly[top.key] ?? top.key;
    const second = ranked[1];
    const top2 = second ? friendly[second.key] ?? second.key : null;
    priorityLine = (
      <>
        You told the engine to prioritize <strong>{top1}</strong> (weight {top.v}){' '}
        {top2 && (
          <>followed by <strong>{top2}</strong> (weight {second!.v}){' '}</>
        )}
        — those choices shaped the trade-offs above. Setting any weight to 0 means the
        engine ignored that criterion.
      </>
    );
  } else {
    priorityLine = (
      <>
        All weights were at zero — the engine only enforced the hard population-balance
        rule and made no other trade-offs.
      </>
    );
  }

  // Most-balanced and least-balanced district highlights.
  const sorted = [...scorecard.per_district].sort(
    (a, b) => Math.abs(a.deviation_pct) - Math.abs(b.deviation_pct)
  );
  const closest = sorted[0];
  const farthest = sorted[sorted.length - 1];

  return (
    <details className="plan-narrative" open>
      <summary>📝 What this plan means, in plain English</summary>
      <div className="plan-narrative-body">
        <p>
          We drew <strong>{nDistricts} U.S. House districts</strong> for {stateName}.
          The engine tried <strong>{chainLength}</strong> different map variations
          (using the <em>{seedStrategy}</em> initial-partition strategy) and kept the
          best one.
        </p>

        <p><strong>Population balance.</strong> {popLine}</p>

        <p><strong>District shapes.</strong> {ppLine}</p>

        <p><strong>County boundaries.</strong> {countyLine}</p>

        {closest && farthest && nDistricts > 1 && (
          <p>
            The most-balanced district came in at{' '}
            <strong>District {closest.district + 1}</strong> ({closest.deviation_pct >= 0 ? '+' : ''}
            {closest.deviation_pct.toFixed(3)}% from target); the farthest from balance
            was <strong>District {farthest.district + 1}</strong>{' '}
            ({farthest.deviation_pct >= 0 ? '+' : ''}{farthest.deviation_pct.toFixed(3)}%).
          </p>
        )}

        <p><strong>Why it came out this way.</strong> {priorityLine}</p>

        <p className="muted small">
          Want a different result? Move the sliders and click <em>Generate plan</em>{' '}
          again. Try cranking <em>polsby_popper</em> for tidier shapes,{' '}
          <em>county_splits</em> for less county splitting, or tighten ε for stricter
          population balance.
        </p>
      </div>
    </details>
  );
}
