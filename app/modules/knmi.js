/* =============================================================================
 * modules/knmi.js  —  component 4: KNMI weather dashboard + AI prediction
 * OWNER: <put your name here>
 *
 * IMPORTANT, verified 2026-09-21:
 *  - The old dataset "Actueel10mindataKNMIstations" v2 STOPPED UPDATING on
 *    2025-10-02. The live one is
 *    "10-minute-in-situ-meteorological-observations" version "1.0".
 *  - KNMI serves those observations as NetCDF, which the browser cannot parse.
 *    So: analysis/knmi/fetch_knmi.py downloads + converts to JSON in
 *    data/processed/, and this module reads the JSON.
 *  - THE BROWSER CANNOT CALL THE KNMI API AT ALL. A plain GET does come back
 *    with "Access-Control-Allow-Origin: *", but the Authorization header makes
 *    the browser send a CORS preflight first, and KNMI's OPTIONS response
 *    carries no CORS headers — so the fetch is blocked. Verified 2026-09-21.
 *    Everything KNMI therefore goes through Python. Do not re-add a fetch()
 *    to api.dataplatform.knmi.nl here; it will fail in every browser.
 *  - The EDR API (nicer, CoverageJSON) returns 403 for the anonymous key.
 *    Register your own key at developer.dataplatform.knmi.nl if you want it.
 * ========================================================================== */

export async function setup(ctx) {
  const body = ctx.registerPanel({
    id: "knmi",
    title: "KNMI weather",
    subtitle: `Station ${ctx.config.studyArea.knmiStation} — Rotterdam`,
    order: 10,
  });

  body.innerHTML = `
    <div id="knmiFeed" class="feed">Checking KNMI feed…</div>
    <div id="knmiNow"></div>
    <div id="knmiHist"></div>
    <div id="knmiPred"></div>`;

  const feedEl = body.querySelector("#knmiFeed");
  const nowEl  = body.querySelector("#knmiNow");
  const histEl = body.querySelector("#knmiHist");
  const predEl = body.querySelector("#knmiPred");

  /* ---- 1. how fresh is the data? ----------------------------------------
   * fetch_knmi.py stamps every file it writes with `fetched_at`; we report
   * that rather than calling KNMI directly (see the CORS note above). */
  const current = await ctx.loadJson(ctx.config.dataSources.processed.knmiCurrent);

  if (current?.fetched_at) {
    const ageMin = Math.round((Date.now() - new Date(current.fetched_at).getTime()) / 60000);
    const stale = ageMin > 60;
    feedEl.className = `feed feed--${stale ? "warn" : "ok"}`;
    feedEl.innerHTML =
      `<strong>${stale ? "Data is stale." : "Data is fresh."}</strong> ` +
      `Last fetched ${ageMin} min ago` +
      (current.source_file ? `<br><code>${current.source_file}</code>` : "") +
      (stale ? `<br>Run <code>analysis/knmi/fetch_knmi.py</code> again.` : "");
  } else {
    feedEl.className = "feed feed--warn";
    feedEl.innerHTML =
      `Nothing fetched yet. Run <code>python analysis/knmi/fetch_knmi.py</code>.`;
  }

  /* ---- 2. current conditions (from the Python fetcher) ------------------ */
  if (current) {
    const rows = Object.entries(current.values || current);
    nowEl.innerHTML =
      `<h4>Current conditions</h4><table class="kv"><tbody>` +
      rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("") +
      `</tbody></table>`;
  } else {
    ctx.placeholder(nowEl, {
      what: "Real-time observations not fetched yet.",
      produces: "data/processed/knmi_current.json",
      owner: "analysis/knmi/fetch_knmi.py",
    });
  }

  /* ---- 3. historical series -------------------------------------------- */
  const history = await ctx.loadJson(ctx.config.dataSources.processed.knmiHistory);
  if (history) {
    histEl.innerHTML = `<h4>History</h4><p class="muted">${
      Array.isArray(history) ? history.length : "?"
    } daily records loaded. TODO: draw the chart.</p>`;
  } else {
    ctx.placeholder(histEl, {
      what: "Historical daily series not fetched yet.",
      produces: "data/processed/knmi_daily_history.json",
      owner: "analysis/knmi/fetch_knmi.py",
    });
  }

  /* ---- 4. AI prediction ------------------------------------------------- */
  const forecast = await ctx.loadJson(ctx.config.dataSources.processed.knmiForecast);
  if (forecast) {
    predEl.innerHTML = `<h4>Model prediction</h4><p class="muted">${
      forecast.model || "model"
    }: ${forecast.horizon || "?"} ahead. TODO: draw the chart.</p>`;
  } else {
    ctx.placeholder(predEl, {
      what: "Predictive model not trained yet.",
      produces: "data/processed/knmi_forecast.json",
      owner: "analysis/knmi/train_forecast.py",
    });
  }
}
