/**
 * Plain-English glossary for the Nationwide batch launch panel.
 * Mirrors the content of redistrict/help_text.py — kept in sync manually.
 *
 * Designed to be SCANNABLE: short paragraphs, visual chips for each control,
 * good vertical rhythm. The tool icons mirror the real controls so the user
 * can match "what I'm reading about" with "what I see on the right".
 */

const SLIDER_CHIP = (
  <span className="ctrl-chip" aria-hidden="true">
    <span className="ctrl-chip-track">
      <span className="ctrl-chip-fill" style={{ width: '60%' }} />
      <span className="ctrl-chip-thumb" />
    </span>
  </span>
);

const DROPDOWN_CHIP = (
  <span className="ctrl-chip ctrl-chip-dropdown" aria-hidden="true">
    <span className="ctrl-chip-text">▾</span>
  </span>
);

const NUMBER_CHIP = (
  <span className="ctrl-chip ctrl-chip-number" aria-hidden="true">
    123
  </span>
);

interface KnobProps {
  chip: React.ReactNode;
  name: string;
  oneLine: string;
  details?: React.ReactNode;
}

function Knob({ chip, name, oneLine, details }: KnobProps) {
  return (
    <div className="knob-help">
      <div className="knob-help-header">
        {chip}
        <span className="knob-help-name">{name}</span>
        <span className="knob-help-oneliner">{oneLine}</span>
      </div>
      {details && <div className="knob-help-details">{details}</div>}
    </div>
  );
}

export function HelpPanel() {
  return (
    <details className="help-panel">
      <summary>📖 What do these controls mean? <span className="muted small">(click to open)</span></summary>
      <div className="help-body">

        <section className="help-section">
          <h3>The 30-second version</h3>
          <p>
            This tool draws U.S. House districts using <strong>only total population</strong> —
            no race, party, income, or anything else.
          </p>
          <p>
            <strong>The hard rule:</strong> every district must contain roughly the same
            number of people — within about 1%. That's federal law since 1964.
          </p>
          <p>
            <strong>The knobs:</strong> sliders below let you tell the engine which OTHER
            things you care about — compact shapes, keeping counties whole, etc.
          </p>
        </section>

        <section className="help-section">
          <h3>Engine controls</h3>
          <Knob
            chip={DROPDOWN_CHIP}
            name="Unit of analysis"
            oneLine="How fine-grained the map is."
            details={<>
              <strong>Blockgroup</strong> = neighborhood-sized pieces, fast, academic
              standard. <strong>Block</strong> = individual city blocks, slow, high
              detail. Stick with blockgroup.
            </>}
          />
          <Knob
            chip={DROPDOWN_CHIP}
            name="Initial partition (seed strategy)"
            oneLine="How the engine draws its first attempt."
            details={<>
              <strong>tree</strong> is recommended — matches how the engine improves
              the map. The others are mostly for experimentation.
            </>}
          />
          <Knob
            chip={SLIDER_CHIP}
            name="Population tolerance ε"
            oneLine="Maximum gap between biggest and smallest district population."
            details={<>
              <strong>Keep at 1.0% for legal plans.</strong> Higher values are useful
              only for what-if exploration.
            </>}
          />
          <Knob
            chip={SLIDER_CHIP}
            name="Chain length"
            oneLine="How many map variations to try before picking the best."
            details={<>
              500 is plenty for most states. Bump to 1000–3000 for big states like
              Texas or California.
            </>}
          />
          <Knob
            chip={NUMBER_CHIP}
            name="Random seed"
            oneLine="Same seed + same settings = identical map every time."
            details={<>Leave blank to randomize each run. Useful for sharing reproducible plans.</>}
          />
          <Knob
            chip={SLIDER_CHIP}
            name="Workers"
            oneLine="One state per worker process running in parallel."
            details={<>
              With 10 CPUs available, 6 leaves headroom for the UI and system. Bump
              to 8 if you want max throughput.
            </>}
          />
        </section>

        <section className="help-section">
          <h3>Variable weights — optional</h3>
          <p className="muted small">
            Higher weight = engine prioritizes that metric. Weight 0 = ignored.
          </p>
          <Knob
            chip={SLIDER_CHIP}
            name="population_deviation"
            oneLine="Pushes population balance even tighter than ε."
          />
          <Knob
            chip={SLIDER_CHIP}
            name="polsby_popper (compactness)"
            oneLine="How round vs. stringy the districts look."
            details={<>
              <strong>1.0</strong> = perfect circle. Real districts typically score
              0.2–0.3. Higher weight = rounder, tidier shapes.
            </>}
          />
          <Knob
            chip={SLIDER_CHIP}
            name="county_splits"
            oneLine="How many counties get cut across district lines."
            details={<>Higher = engine keeps counties whole. Set this high if your state law requires it.</>}
          />
          <Knob
            chip={SLIDER_CHIP}
            name="cut_edges"
            oneLine="Number of dual-graph edges crossing district boundaries."
            details={<>Lower = smoother borders. Pick this OR polsby_popper — they reward the same thing.</>}
          />
          <Knob
            chip={SLIDER_CHIP}
            name="total_area · perimeter · reock"
            oneLine="Niche — leave at 0 unless you have a specific reason."
          />
        </section>

        <section className="help-section">
          <h3>What the live map shows</h3>
          <div className="phase-key">
            <span><span className="phase phase-queued">queued</span> waiting to be picked up</span>
            <span><span className="phase phase-districting">processing</span> a worker is on it now</span>
            <span><span className="phase phase-done">done</span> finished — actual districts when "Show districts" is on</span>
            <span><span className="phase phase-failed">failed</span> click 🔁 Retry to redo it</span>
            <span><span className="phase phase-skipped">skipped</span> single-seat state (whole state = one district)</span>
          </div>
        </section>

        <section className="help-section">
          <h3>Map interaction</h3>
          <ul className="hint-list">
            <li>Click any of the counter tiles (Done / Running / Failed / Skipped) to see the list of states + their district counts.</li>
            <li>Click any state on the map for a detail panel.</li>
            <li>Use <span className="kbd">＋</span> <span className="kbd">−</span> <span className="kbd">⟳</span> on the top-right of the map to zoom and reset. Drag to pan. Mousewheel zooms too.</li>
          </ul>
        </section>

      </div>
    </details>
  );
}
