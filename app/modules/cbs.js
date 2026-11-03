/* =============================================================================
 * modules/cbs.js - component 6: CBS socio-demographic dashboard
 * OWNER: Atanas Malinkov
 *
 * Bloemhof against the municipality of Rotterdam, from CBS "Kerncijfers wijken
 * en buurten", fetched in Python (analysis/cbs/fetch_cbs.py) into
 *   data/processed/cbs_indicators.json
 * {
 *   "buurt": "Bloemhof", "gemeente": "Rotterdam",
 *   "people": { year, table, rows: [ {label, unit, bloemhof, rotterdam} ] },
 *   "groups": [ { key, title, year, note, categories: [ {label, bloemhof, rotterdam} ] } ],  //shares in %
 *   "income": { year, table, rows: [ {label, unit, bloemhof, rotterdam} ] }
 * }
 * People, age, households and origin are the newest edition, income lags two
 * years. It describes today's residents, so it does not follow the scenario switch.
 * ========================================================================== */

//one colour per category, in a fixed order; age is ordered, so one hue light to dark
const COLOURS = {
  age: ["#cfe3f7", "#9cc5ee", "#5fa0de", "#2a78d6", "#1a4f94"],
  households: ["#2a78d6", "#eb6834", "#1baf7a"],
  origin: ["#1baf7a", "#2a78d6", "#eb6834"],
};

const fmt = (v, unit) => v == null ? "-"
  : unit === "%" ? `${v.toLocaleString("en-GB", { maximumFractionDigits: 1 })} %`
  : unit === "people" ? v.toFixed(1)  //household size keeps its decimal, 2.0 not 2
  : v.toLocaleString("en-GB", { maximumFractionDigits: 1 });

//dark text on light segments, light text on dark ones
function inkFor(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#0b1a2a" : "#ffffff";
}

//two 100 % stacked bars, Bloemhof above Rotterdam, with the shares on the segments
function stackedBars(group, names) {
  const colours = COLOURS[group.key];
  const W = 300, rowH = 22, gap = 8, labelW = 64, barW = W - labelW;
  const rows = [["bloemhof", names.buurt], ["rotterdam", names.gemeente]];
  let svg = `<svg viewBox="0 0 ${W} ${2 * rowH + gap}" width="100%" role="img" aria-label="${group.title}, ${names.buurt} against ${names.gemeente}">`;
  rows.forEach(([key, name], r) => {
    const y = r * (rowH + gap);
    svg += `<text x="0" y="${y + rowH / 2 + 4}" fill="var(--text-dim)" font-size="11">${name}</text>`;
    let x = labelW;
    group.categories.forEach((c, i) => {
      const w = (barW * (c[key] || 0)) / 100;
      const col = colours[i % colours.length];
      svg += `<g><title>${name}, ${c.label}: ${fmt(c[key], "%")}</title>` +  //hover tooltip
        `<rect x="${x}" y="${y}" width="${Math.max(0, w - 2)}" height="${rowH}" rx="2" fill="${col}"/>` +  //2px gap between segments
        (w > 28 ? `<text x="${x + (w - 2) / 2}" y="${y + rowH / 2 + 4}" text-anchor="middle" font-size="10.5" fill="${inkFor(col)}">${Math.round(c[key])}%</text>` : "") +
        `</g>`;
      x += w;
    });
  });
  svg += `</svg>`;
  const legend = group.categories.map((c, i) =>
    `<span style="display:inline-flex;align-items:center;gap:4px;margin-right:10px">` +
    `<span style="width:10px;height:10px;border-radius:2px;background:${colours[i % colours.length]}"></span>${c.label}</span>`).join("");
  return `<h4>${group.title} <span class="muted">· ${group.note}, ${group.year}</span></h4>` + svg +
    `<div class="muted" style="font-size:11px;margin:2px 0 10px">${legend}</div>`;
}

//a Bloemhof / Rotterdam table for the people and income figures
function table(title, block, names) {
  return `<h4>${title} <span class="muted">· ${block.year}</span></h4>` +
    `<table class="kv"><thead><tr><th></th><th>${names.buurt}</th><th>${names.gemeente}</th></tr></thead><tbody>` +
    block.rows.map((r) =>
      `<tr><td>${r.label}${r.unit && r.unit !== "%" ? ` <span class="muted">(${r.unit})</span>` : ""}</td>` +
      `<td>${fmt(r.bloemhof, r.unit)}</td><td class="muted">${fmt(r.rotterdam, r.unit)}</td></tr>`).join("") +
    `</tbody></table>`;
}

export async function setup(ctx) {
  const body = ctx.registerPanel({
    id: "cbs",
    title: "CBS demographics",
    subtitle: "Bloemhof against Rotterdam · today's residents, all scenarios",
    order: 20,
  });

  const data = await ctx.loadJson(ctx.config.dataSources.processed.cbsIndicators);
  if (!data?.people) {
    ctx.placeholder(body, {
      what: "CBS figures not fetched yet.",
      produces: "data/processed/cbs_indicators.json",
      owner: "analysis/cbs/fetch_cbs.py",
    });
    return;
  }

  const names = { buurt: data.buurt || "Bloemhof", gemeente: data.gemeente || "Rotterdam" };
  body.innerHTML =
    table("People", data.people, names) +
    (data.groups || []).map((g) => stackedBars(g, names)).join("") +
    (data.income ? table("Income", data.income, names) : "") +
    `<p class="muted">CBS Kerncijfers wijken en buurten, table ${data.people.table} (${data.people.year})` +
    (data.income ? ` and ${data.income.table} (${data.income.year}, the newest with income per buurt)` : "") +
    `. Low and high income are households in the national lowest 40 % and highest 20 % of disposable income. ` +
    `Shares are computed from CBS counts, so both areas are measured the same way.</p>`;
}
