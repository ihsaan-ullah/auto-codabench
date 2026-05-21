/* AutoCodabench: single top-right toggle to hide / show all tool details.
 *
 * Initial state: tool details visible, no help banner shown (clean first
 * impression — user opens chat, sees only the conversation + the chips).
 * Click "Hide tool details" → chips hidden.
 * Click "Show tool details (with guide)" → chips visible + help banner
 * appears under the toggle so the user knows what each chip type means.
 *
 * Implementation notes:
 *   - Chainlit renders steps as React components; their DOM class names
 *     are not stable across versions. We tag them with data-ac-step="1"
 *     using a MutationObserver that looks for buttons whose label starts
 *     with our "→ " step-name prefix (set in app.py).
 *   - CSS in chat.css (loaded via custom_css) hides anything tagged when
 *     body.ac-hide-tools is set.
 */
(function () {
    "use strict";

    const HELP_HTML = `
    <div class="ac-help-title">What you're seeing</div>
    <p>Each <code>→ tool</code> chip below my replies is one MCP call I made
    to ground or save a decision. The full audit trail (raw JSON of every
    call) is on disk under <code>auto_codabench/runs/&lt;your session&gt;/</code>.</p>

    <div class="ac-help-section">autocodabench (the bundle builder)</div>
    <ul>
      <li><code>open_run</code> — opens this session's run directory.</li>
      <li><code>log_event</code> — records a structured event. The <code>kind</code> tells you what kind of milestone:
        <ul>
          <li><b>phase_a_started</b> — proposal-crystallization phase began.</li>
          <li><b>question_asked</b> — I just asked you a focused question.</li>
          <li><b>ss_searched</b> — I queried OpenAlex.</li>
          <li><b>tension_surfaced</b> — I flagged a controversy in the literature.</li>
          <li><b>proposal_made</b> / <b>proposal_accepted</b> / <b>proposal_revised</b> — design-decision lifecycle.</li>
          <li><b>citation_unavailable</b> — a citation I wanted didn't resolve; proposal proceeds with a <code>[citation pending]</code> mark.</li>
          <li><b>proposal_done</b> — I wrote <code>project_proposal.md</code>.</li>
          <li><b>iter1_done</b> — planning is done.</li>
        </ul>
      </li>
      <li><code>snapshot_spec</code> — writes a file (proposal or spec) and keeps a versioned copy.</li>
      <li><code>current_run</code> — sanity-checks that a run is open.</li>
      <li><i>Session 2 only:</i> <code>init_bundle</code>, <code>write_competition_yaml</code>, <code>write_page</code>,
          <code>write_scoring_program</code>, <code>write_ingestion_program</code>, <code>write_solution</code>,
          <code>attach_data</code>, <code>validate_bundle</code>, <code>zip_bundle</code>,
          <code>upload_bundle</code> (publishes to Codabench, returns URL).</li>
    </ul>

    <div class="ac-help-section">alex-mcp (literature lookups via OpenAlex)</div>
    <ul>
      <li><code>search_works</code> — paper search by topic, title, or abstract.</li>
      <li><code>search_authors</code> / <code>autocomplete_authors</code> — find researchers.</li>
      <li><code>retrieve_author_works</code> — all peer-reviewed works for one author.</li>
      <li><code>search_pubmed</code> / <code>pubmed_author_sample</code> — PubMed cross-check, esp. biomed.</li>
      <li><code>search_orcid_authors</code> / <code>get_orcid_publications</code> — ORCID lookups.</li>
    </ul>

    <p>Want to disappear all of this? Click <b>Hide tool details</b>.</p>
    `;

    function injectControlBar() {
        if (document.getElementById("ac-control-bar")) return;
        const bar = document.createElement("div");
        bar.id = "ac-control-bar";
        bar.innerHTML = `
            <button id="ac-toggle" type="button" aria-expanded="true"
                title="Hide all tool-detail chips below my replies">
                Hide tool details
            </button>
            <div id="ac-help" style="display:none">${HELP_HTML}</div>
        `;
        document.body.appendChild(bar);

        // Initial state: tools visible, help hidden.
        document.body.classList.remove("ac-hide-tools");

        const btn = document.getElementById("ac-toggle");
        const help = document.getElementById("ac-help");
        btn.addEventListener("click", () => {
            const hidden = document.body.classList.toggle("ac-hide-tools");
            if (hidden) {
                btn.textContent = "Show tool details (with guide)";
                btn.setAttribute("aria-expanded", "false");
                help.style.display = "none";
            } else {
                btn.textContent = "Hide tool details";
                btn.setAttribute("aria-expanded", "true");
                help.style.display = "block";  // expose the guide on first expand
            }
        });
    }

    function tagSteps() {
        // Heuristic: a Chainlit Step chip is a clickable element whose
        // label text begins with our "→ " prefix (assigned in app.py).
        // Walk up two levels and tag the closest container so the whole
        // card hides as one unit.
        document.querySelectorAll("button, [role='button']").forEach((el) => {
            const txt = (el.textContent || "").trim();
            if (txt.startsWith("→ ") && !el.dataset.acStepBtn) {
                el.dataset.acStepBtn = "1";
                let host = el.closest("[data-step-id]")
                    || el.parentElement?.parentElement
                    || el.parentElement;
                if (host) host.setAttribute("data-ac-step", "1");
            }
        });
    }

    // Inject as soon as React has mounted; retry to catch reloads.
    const tryInject = () => {
        injectControlBar();
        tagSteps();
    };
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", tryInject);
    } else {
        tryInject();
    }
    // Catch late-mount + ongoing message streams.
    setTimeout(tryInject, 800);
    setTimeout(tryInject, 2500);
    new MutationObserver(tagSteps).observe(document.body, {
        childList: true,
        subtree: true,
    });
})();
