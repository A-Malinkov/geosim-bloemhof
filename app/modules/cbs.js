/* =============================================================================
 * modules/cbs.js  —  component 6: CBS socio-demographic dashboards
 * OWNER: <put your name here>
 *
 * Source: CBS StatLine OData, table 86358NED "Kerncijfers wijken en buurten
 * 2026" (verified newest on 2026-09-21; 2025 = 86165NED, 2024 = 85984NED).
 * Study buurt: Bloemhof = BU05991081, gemeente Rotterdam = GM0599.
 *
 * CBS OData does not reliably send CORS headers, so fetch in Python
 * (analysis/cbs/fetch_cbs.py) and write data/processed/cbs_indicators.json.
 *
 * Expected shape:
 * {
 *   "buurt": "Bloemhof", "code": "BU05991081", "year": 2026,
 *   "indicators": [
 *     { "label": "Inhabitants", "value": 14230, "unit": "",
 *       "gemeente": 670000, "nl": null }
 *   ]
 * }
 * ========================================================================== */

export async function setup(ctx) {
  const sa = ctx.config.studyArea;
  const body = ctx.registerPanel({
    id: "cbs",
    title: "CBS demographics",
    subtitle: `${sa.name} (${sa.cbsBuurtCode}) · table ${ctx.config.dataSources.cbsTable}`,
    order: 20,
  });

  const data = await ctx.loadJson(ctx.config.dataSources.processed.cbsIndicators);

  if (!data) {
    ctx.placeholder(body, {
      what: "CBS figures not fetched yet.",
      produces: "data/processed/cbs_indicators.json",
      owner: "analysis/cbs/fetch_cbs.py + app/modules/cbs.js",
    });
    return;
  }

  const rows = data.indicators || [];
  body.innerHTML =
    `<table class="kv"><thead><tr>` +
    `<th>Indicator</th><th>${data.buurt || "Buurt"}</th><th>Rotterdam</th>` +
    `</tr></thead><tbody>` +
    rows.map((r) => {
      const fmt = (v) =>
        v == null ? "—" : typeof v === "number" ? v.toLocaleString("en-GB") : v;
      return `<tr><td>${r.label}${r.unit ? ` <span class="muted">(${r.unit})</span>` : ""}</td>` +
             `<td>${fmt(r.value)}</td><td class="muted">${fmt(r.gemeente)}</td></tr>`;
    }).join("") +
    `</tbody></table>` +
    `<p class="muted">TODO: add the charts (see the dataviz notes in docs/).</p>`;
}
