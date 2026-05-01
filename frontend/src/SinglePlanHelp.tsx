/** Plain-English glossary for the single-state Generate Plan view.
 *  Mirrors HelpPanel.tsx but trimmed to single-state context. */
export function SinglePlanHelp() {
  return (
    <details className="help-panel">
      <summary>📖 What do these controls mean? (click to open)</summary>
      <div className="help-body">

        <section className="help-section">
          <h3>The 30-second version</h3>
          <p>
            Pick a state, choose how strict to be on different things, and click
            <strong> Generate plan</strong>. The engine runs ReCom MCMC server-side and
            shows a live progress bar; when it's done you see the resulting district
            map and a per-district scorecard. You can download a self-contained PDF.
          </p>
          <p>
            The only hard rule is <strong>population balance</strong>: every district
            must have roughly the same number of people — within ε of the target.
          </p>
        </section>

        <section className="help-section">
          <h3>State picker</h3>
          <p>Only states with two or more U.S. House seats are listed; one-seat
          states have nothing to district.</p>
        </section>

        <section className="help-section">
          <h3>Engine controls</h3>
          <dl>
            <dt>Unit</dt>
            <dd>
              <strong>blockgroup</strong> = small neighborhood-sized pieces (~thousands
              of nodes per state). Fast and the academic standard.{' '}
              <strong>block</strong> = individual census blocks (~hundreds of thousands).
              Slow, only useful when you need block-precise lines.
            </dd>
            <dt>Initial partition (seed strategy)</dt>
            <dd>
              How the engine draws its first attempt before improving it.{' '}
              <strong>tree</strong> is recommended — it matches how the engine
              improves the map so the chain converges faster. Other options
              (<code>centroid</code>, <code>sweep-ew</code>, <code>sweep-ns</code>) are
              mostly for experimentation.
            </dd>
            <dt>ε (population tolerance)</dt>
            <dd>
              The biggest district can't differ from the smallest by more than ε of
              the target population. <strong>Keep at 1.0% for legally viable plans.</strong>{' '}
              Higher values are useful only for what-if exploration.
            </dd>
            <dt>Chain length</dt>
            <dd>
              Number of ReCom variations to try. More = better optimization, longer
              wait. 500 is plenty for most states; bump to 1000–3000 for big states.
            </dd>
            <dt>Random seed</dt>
            <dd>
              Same seed + same settings → identical map every time. Leave blank to
              use the wall clock (different result each run). Use this when sharing
              reproducible plans.
            </dd>
          </dl>
        </section>

        <section className="help-section">
          <h3>Variable weights</h3>
          <p className="muted small">
            Higher weight = engine prioritizes that metric in its scoring. Set to 0
            to ignore. Hover any slider for a one-line description.
          </p>
          <dl>
            <dt>population_deviation</dt>
            <dd>
              Already capped by ε; this slider decides whether to push for
              "as-close-as-possible" or settle for "good enough within the legal envelope."
            </dd>
            <dt>polsby_popper (compactness)</dt>
            <dd>
              How tidy / round the district shapes are. Higher = rounder; lower =
              you might get long stringy shapes. <strong>1.0</strong> = perfect circle;
              real districts typically score 0.2–0.3.
            </dd>
            <dt>county_splits</dt>
            <dd>
              How many counties get cut across district lines. Higher weight = engine
              keeps counties whole. Set this high if your state law requires it.
            </dd>
            <dt>cut_edges · perimeter_total</dt>
            <dd>
              More technical proxies for "smooth borders". Pick at most one — they
              reward similar things.
            </dd>
            <dt>total_area_sqmi · reock</dt>
            <dd>Niche. Leave at 0 unless you know what you want.</dd>
          </dl>
        </section>

        <section className="help-section">
          <h3>After the chain finishes</h3>
          <ul className="hint-list">
            <li>The <strong>district map</strong> shows the best plan found, numbered
              1, 2, 3… to match the per-district table.</li>
            <li><span className="kbd">Show district numbers</span> toggles the labels.</li>
            <li>Click any district to see the cities/places it contains, with real populations.</li>
            <li>Use the <strong>Current US House districts</strong> opacity slider to
              overlay the officially-adopted current districts on top — drag to fade
              between "yours" and "theirs". A side-by-side scorecard appears below.</li>
            <li><strong>📄 Download PDF</strong> exports a self-contained PDF with
              embedded plan data; drop it back into the app later to re-render the map
              from the PDF alone.</li>
          </ul>
        </section>

      </div>
    </details>
  );
}
