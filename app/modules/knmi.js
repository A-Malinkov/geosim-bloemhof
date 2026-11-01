/* =============================================================================
 * modules/knmi.js  —  component 4: KNMI weather dashboard + AI prediction
 * OWNER: Atanas Malinkov
 *
 * TWO DATA PATHS, AND YOU NEED BOTH
 * ---------------------------------
 * 1. LIVE, in this file, straight from the browser.
 *    Open-Meteo serves KNMI's own HARMONIE-AROME model (2 km over the
 *    Netherlands, hourly updates) with CORS headers and no API key, so the page
 *    can poll it and refresh itself. This is what makes the dashboard *live*.
 *
 * 2. KNMI's own station sensors, via Python.
 *    analysis/knmi/fetch_knmi.py -> data/processed/knmi_current.json etc.
 *    Still to be written; this module already reads the files.
 *
 * WHY NOT JUST CALL KNMI DIRECTLY? THE BROWSER CANNOT.
 * Verified 2026-09-21 and still true. A plain curl GET to
 * api.dataplatform.knmi.nl succeeds and even returns
 * "Access-Control-Allow-Origin: *", which is misleading: the Authorization
 * header makes the browser send a CORS preflight first, and KNMI's OPTIONS
 * response carries no CORS headers, so the fetch is blocked in every browser.
 * Their observations are NetCDF anyway, which the browser cannot parse.
 * DO NOT re-add a fetch() to api.dataplatform.knmi.nl here.
 * The EDR API (CoverageJSON, nicer) returns 403 for the anonymous key; register
 * your own at developer.dataplatform.knmi.nl if you want it.
 *
 * ATTRIBUTION: Open-Meteo data is CC BY 4.0 and must be credited. The credit is
 * rendered in the panel and added to the status bar. Do not remove it.
 * ========================================================================== */

/* WMO 4677 weather codes, as used by Open-Meteo. */
const WMO = {
  0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
  45: "Fog", 48: "Depositing rime fog",
  51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
  56: "Freezing drizzle", 57: "Dense freezing drizzle",
  61: "Slight rain", 63: "Rain", 65: "Heavy rain",
  66: "Freezing rain", 67: "Heavy freezing rain",
  71: "Slight snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
  80: "Slight showers", 81: "Showers", 82: "Violent showers",
  85: "Slight snow showers", 86: "Snow showers",
  95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm",
};

/* Charts the user can switch between — this is the "user controls the
 * displayed content" part, not decoration. */
const SERIES = [
  { key: "temperature_2m",      label: "temp",   unit: "°C",  colour: "#eb6834" },
  { key: "wind_speed_10m",      label: "wind",   unit: "m/s", colour: "#2a78d6" },
  { key: "wind_gusts_10m",      label: "gusts",  unit: "m/s", colour: "#4a3aa7" },
  { key: "precipitation",       label: "rain",   unit: "mm",  colour: "#1baf7a" },
  { key: "relative_humidity_2m", label: "humidity", unit: "%", colour: "#e87ba4" },
];

const CURRENT_VARS = [
  "temperature_2m", "apparent_temperature", "relative_humidity_2m",
  "precipitation", "weather_code", "cloud_cover",
  "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "is_day",
].join(",");

const HOURLY_VARS = SERIES.map((s) => s.key).join(",");

const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                 "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
const compass = (deg) => COMPASS[Math.round(((deg % 360) / 22.5)) % 16];

/** One request: current conditions plus a 72 h hourly series. */
async function fetchLive(cfg, sa) {
  const om = cfg.dataSources.openMeteo;
  const url = new URL(om.forecast);
  url.search = new URLSearchParams({
    latitude: sa.lat,
    longitude: sa.lon,
    models: om.model,
    wind_speed_unit: "ms",            // m/s, as KNMI and wind studies use
    timezone: "Europe/Amsterdam",
    forecast_days: String(om.forecastDays ?? 3),
    current: CURRENT_VARS,
    hourly: HOURLY_VARS,
  }).toString();

  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Open-Meteo HTTP ${res.status}`);
  const json = await res.json();
  if (json.error) throw new Error(json.reason || "Open-Meteo error");
  return json;
}

/** A wind arrow pointing the way the wind is blowing TO. */
function windArrow(dirFrom) {
  const to = (dirFrom + 180) % 360;     // meteorological direction is "from"
  return `<svg viewBox="0 0 40 40" width="38" height="38" aria-hidden="true">
    <circle cx="20" cy="20" r="18" fill="none" stroke="#2c3541" stroke-width="1"/>
    <text x="20" y="7.5" text-anchor="middle" font-size="7" fill="#97a3b2">N</text>
    <g transform="rotate(${to} 20 20)">
      <path d="M20 7 L25 26 L20 22 L15 26 Z" fill="#4dd0e1"/>
    </g></svg>`;
}

/** Inline SVG line chart for one hourly series, with "now" marked. */
function chart(times, values, spec, nowIso) {
  const pts = times.map((t, i) => [t, values[i]])
                   .filter(([, v]) => v !== null && v !== undefined);
  if (pts.length < 2) return `<p class="muted">no data for ${spec.label}</p>`;

  const w = 280, h = 76, padL = 26, padB = 13, padT = 6;
  const vs = pts.map((p) => p[1]);
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (spec.key === "precipitation") lo = 0;
  if (hi - lo < 1e-6) { hi = lo + 1; }
  const pad = (hi - lo) * 0.12;
  lo -= pad; hi += pad;

  const X = (i) => padL + (i / (pts.length - 1)) * (w - padL - 4);
  const Y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (h - padT - padB);

  const line = pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
  const area = `${line}L${X(pts.length - 1).toFixed(1)},${(h - padB).toFixed(1)}`
             + `L${X(0).toFixed(1)},${(h - padB).toFixed(1)}Z`;

  // vertical rule at the current hour
  const nowHour = nowIso ? nowIso.slice(0, 13) : null;
  const ni = pts.findIndex((p) => p[0].slice(0, 13) === nowHour);
  const nowRule = ni >= 0
    ? `<line x1="${X(ni).toFixed(1)}" y1="${padT}" x2="${X(ni).toFixed(1)}" y2="${h - padB}" `
      + `stroke="#e7ecf2" stroke-width="1" opacity="0.55"/>`
    : "";

  // midnight ticks
  const ticks = pts.map((p, i) => [p[0], i])
    .filter(([t]) => t.slice(11, 16) === "00:00")
    .map(([t, i]) => `<text x="${X(i).toFixed(1)}" y="${h - 3}" font-size="7.5" `
      + `fill="#97a3b2" text-anchor="middle">${t.slice(8, 10)}/${t.slice(5, 7)}</text>`)
    .join("");

  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="84" role="img"
       aria-label="${spec.label} over the next days">
    <text x="0" y="${(padT + 6).toFixed(1)}" font-size="7.5" fill="#97a3b2">${hi.toFixed(1)}</text>
    <text x="0" y="${(h - padB).toFixed(1)}" font-size="7.5" fill="#97a3b2">${lo.toFixed(1)}</text>
    <line x1="${padL}" y1="${h - padB}" x2="${w}" y2="${h - padB}" stroke="#2c3541" stroke-width="1"/>
    ${nowRule}
    <path d="${area}" fill="${spec.colour}" opacity="0.13"/>
    <path d="${line}" fill="none" stroke="${spec.colour}" stroke-width="2"
          stroke-linejoin="round" stroke-linecap="round"/>
    ${ticks}
  </svg>`;
}

/** Two-line overlay chart (e.g. predicted vs actual, or a monthly mean band). */
function chart2(labels, a, b, aName, bName, aCol, bCol, unit) {
  const n = labels.length;
  const vals = [...a, ...b].filter((v) => v !== null && v !== undefined);
  if (vals.length < 2) return "";
  const w = 280, h = 80, padL = 26, padB = 13, padT = 6;
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1e-6) hi = lo + 1;
  const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
  const X = (i) => padL + (i / Math.max(1, n - 1)) * (w - padL - 4);
  const Y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (h - padT - padB);
  const path = (arr) => {
    let d = "", pen = false;
    arr.forEach((v, i) => {
      if (v === null || v === undefined) { pen = false; return; }
      d += `${pen ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="88" role="img"
      aria-label="${aName} and ${bName}">
    <text x="0" y="${(padT + 6).toFixed(1)}" font-size="7.5" fill="#97a3b2">${hi.toFixed(1)}</text>
    <text x="0" y="${(h - padB).toFixed(1)}" font-size="7.5" fill="#97a3b2">${lo.toFixed(1)}</text>
    <line x1="${padL}" y1="${h - padB}" x2="${w}" y2="${h - padB}" stroke="#2c3541"/>
    <path d="${path(a)}" fill="none" stroke="${aCol}" stroke-width="1.8" stroke-linejoin="round"/>
    <path d="${path(b)}" fill="none" stroke="${bCol}" stroke-width="1.8" stroke-linejoin="round"/>
  </svg>
  <p class="muted" style="margin:1px 0 0">
    <span style="color:${aCol}">&#9632;</span> ${aName}
    <span style="color:${bCol};margin-left:8px">&#9632;</span> ${bName}
    <span style="margin-left:8px">${unit}</span></p>`;
}

/* ========================================================================== */
export async function setup(ctx) {
  const sa = ctx.config.studyArea;
  const om = ctx.config.dataSources.openMeteo;

  const body = ctx.registerPanel({
    id: "knmi",
    title: "KNMI weather",
    subtitle: `${sa.name}, Rotterdam — live`,
    order: 10,
  });

  body.innerHTML = `
    <div id="knmiStatus" class="feed">Connecting to the live feed…</div>
    <div id="knmiNow"></div>
    <div id="knmiChartWrap" hidden>
      <div class="seg" id="knmiSeg">
        ${SERIES.map((s, i) =>
          `<button data-k="${s.key}" class="${i === 0 ? "on" : ""}">${s.label}</button>`).join("")}
      </div>
      <div id="knmiChart"></div>
    </div>
    <div id="knmiObs"></div>
    <div id="knmiHist"></div>
    <div id="knmiPred"></div>
    <p class="muted" id="knmiCredit"></p>`;

  const statusEl = body.querySelector("#knmiStatus");
  const nowEl = body.querySelector("#knmiNow");
  const chartWrap = body.querySelector("#knmiChartWrap");
  const chartEl = body.querySelector("#knmiChart");
  const obsEl = body.querySelector("#knmiObs");
  const histEl = body.querySelector("#knmiHist");
  const predEl = body.querySelector("#knmiPred");
  body.querySelector("#knmiCredit").textContent = om.attribution;

  let latest = null;          // last good payload
  let fetchedAt = null;       // when we got it
  let active = SERIES[0].key;
  let failures = 0;

  body.querySelectorAll("#knmiSeg button").forEach((b) =>
    b.addEventListener("click", () => {
      body.querySelectorAll("#knmiSeg button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      active = b.dataset.k;
      renderChart();
    }));

  function renderChart() {
    if (!latest?.hourly) return;
    const spec = SERIES.find((s) => s.key === active);
    chartEl.innerHTML =
      chart(latest.hourly.time, latest.hourly[spec.key], spec, latest.current?.time) +
      `<p class="muted" style="margin:2px 0 0">${spec.label} (${spec.unit}) · ` +
      `next ${om.forecastDays ?? 3} days · the pale line is now</p>`;
    chartWrap.hidden = false;
  }

  function renderNow() {
    if (!latest?.current) return;
    const c = latest.current, u = latest.current_units || {};
    const dir = c.wind_direction_10m;
    nowEl.innerHTML = `
      <div class="wxnow">
        <div class="wxnow__temp">${c.temperature_2m?.toFixed(1) ?? "—"}<span>${u.temperature_2m || "°C"}</span></div>
        <div class="wxnow__desc">
          <strong>${WMO[c.weather_code] ?? "—"}</strong><br>
          feels like ${c.apparent_temperature?.toFixed(1) ?? "—"} °C
        </div>
        <div class="wxnow__wind">${dir != null ? windArrow(dir) : ""}</div>
      </div>
      <table class="kv"><tbody>
        <tr><td>wind</td><td>${c.wind_speed_10m?.toFixed(1) ?? "—"} m/s from
            ${dir != null ? `${compass(dir)} (${dir}°)` : "—"}</td></tr>
        <tr><td>gusts</td><td>${c.wind_gusts_10m?.toFixed(1) ?? "—"} m/s</td></tr>
        <tr><td>humidity</td><td>${c.relative_humidity_2m ?? "—"} %</td></tr>
        <tr><td>cloud</td><td>${c.cloud_cover ?? "—"} %</td></tr>
        <tr><td>precipitation</td><td>${c.precipitation ?? "—"} mm</td></tr>
      </tbody></table>`;
  }

  /* The ticking "x ago" is what makes it visibly live rather than a snapshot. */
  function renderStatus() {
    if (!fetchedAt) return;
    const age = Math.round((Date.now() - fetchedAt) / 1000);
    const ago = age < 60 ? `${age}s ago`
              : age < 3600 ? `${Math.round(age / 60)} min ago`
              : `${Math.round(age / 3600)} h ago`;
    const stale = age > (om.refreshSeconds ?? 300) * 3;
    statusEl.className = `feed feed--${stale ? "warn" : "ok"}`;
    statusEl.innerHTML =
      `<span class="live${stale ? " live--stale" : ""}"></span>` +
      `<strong>Live</strong> — KNMI HARMONIE-AROME 2 km, updated ${ago}.` +
      `<br><code>model time ${latest?.current?.time ?? "—"} · ` +
      `refreshes every ${Math.round((om.refreshSeconds ?? 300) / 60)} min</code>`;
  }

  async function refresh() {
    try {
      const data = await fetchLive(ctx.config, sa);
      latest = data;
      fetchedAt = Date.now();
      failures = 0;
      renderNow();
      renderChart();
      renderStatus();
    } catch (err) {
      failures += 1;
      console.warn("[knmi] live fetch failed", err);
      if (!latest) {
        statusEl.className = "feed feed--warn";
        statusEl.innerHTML =
          `Could not reach the live weather feed (${err.message}).` +
          `<br><code>check your internet connection</code>`;
      } else {
        renderStatus();   // keep the last good data on screen, just ageing
      }
    }
  }

  await refresh();
  if (latest) ctx.note("Weather: live", "ok");

  // tick the age label every second; refetch on the configured interval
  setInterval(renderStatus, 1000);
  setInterval(() => {
    // don't burn requests while the tab is hidden
    if (document.visibilityState === "visible") refresh();
  }, (om.refreshSeconds ?? 300) * 1000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && fetchedAt &&
        Date.now() - fetchedAt > (om.refreshSeconds ?? 300) * 1000) refresh();
  });

  /* ---- KNMI's own station sensors, via Python ---------------------------- */
  const obs = await ctx.loadJson(ctx.config.dataSources.processed.knmiCurrent,
                                 { quiet: true });
  if (obs) {
    const u = obs.units || {};
    const rows = Object.entries(obs.values || {})
      .filter(([, v]) => v !== null && v !== undefined);
    obsEl.innerHTML =
      `<h4>KNMI station sensors</h4>` +
      `<table class="kv"><tbody>` +
      rows.map(([k, v]) =>
        `<tr><td>${k.replace(/_/g, " ")}</td><td>${v} ${u[k] ?? ""}</td></tr>`).join("") +
      `</tbody></table>` +
      `<p class="muted">Measured at ${obs.station_name ?? obs.station} ` +
      `(${obs.station}), ${obs.distance_km} km away · ` +
      `observation ${String(obs.observation_time).slice(0, 16).replace("T", " ")}` +
      `<br>These are instrument readings. The live panel above is KNMI's ` +
      `forecast model — the two will not match exactly.</p>`;
  } else {
    ctx.placeholder(obsEl, {
      what: "KNMI station observations not fetched yet. These are the actual "
          + "sensor readings required by §4.4; the live panel above is KNMI's "
          + "forecast model.",
      produces: "data/processed/knmi_current.json",
      owner: "analysis/knmi/fetch_knmi.py",
    });
  }

  /* ---- historical series -------------------------------------------------- */
  const hist = await ctx.loadJson(ctx.config.dataSources.processed.knmiHistory,
                                  { quiet: true });
  if (hist?.records?.length) {
    // aggregate to monthly means; 2,000 daily points in a 280 px chart is mush
    const byMonth = new Map();
    for (const r of hist.records) {
      if (r.T_mean_C === null) continue;
      const key = r.date.slice(0, 7);
      const m = byMonth.get(key) || { t: 0, w: 0, n: 0 };
      m.t += r.T_mean_C;
      m.w += r.wind_mean_ms ?? 0;
      m.n += 1;
      byMonth.set(key, m);
    }
    const keys = [...byMonth.keys()].sort();
    const temps = keys.map((k) => +(byMonth.get(k).t / byMonth.get(k).n).toFixed(2));
    const winds = keys.map((k) => +(byMonth.get(k).w / byMonth.get(k).n).toFixed(2));
    const years = new Set(keys.map((k) => k.slice(0, 4))).size;
    histEl.innerHTML =
      `<h4>History</h4>` +
      chart2(keys, temps, winds, "temp", "wind", "#eb6834", "#2a78d6", "°C / m·s⁻¹") +
      `<p class="muted">Monthly means, ${keys.length} months over ${years} years ` +
      `at station ${hist.station}. ${hist.records.length.toLocaleString("en-GB")} ` +
      `daily records.</p>`;
  } else {
    ctx.placeholder(histEl, {
      what: "Historical series not fetched yet.",
      produces: "data/processed/knmi_daily_history.json",
      owner: "analysis/knmi/fetch_knmi.py",
    });
  }

  /* ---- AI prediction ----------------------------------------------------- */
  const forecast = await ctx.loadJson(ctx.config.dataSources.processed.knmiForecast,
                                      { quiet: true });
  if (forecast) {
    const m = forecast.metrics || {};
    const tRes = forecast.results?.temperature_C?.horizons || {};
    const demo = forecast.demo_series;

    // per-horizon comparison against the persistence baseline
    const hRows = Object.entries(tRes).map(([hz, models]) => {
      const best = models._best;
      const b = models[best] || {};
      const skill = b.skill_vs_persistence;
      return `<tr><td>${hz}</td><td>${best}</td><td>${b.mae?.toFixed(2) ?? "—"}</td>` +
             `<td><span class="delta ${skill > 0 ? "down" : "up"}">` +
             `${skill == null ? "—" : (skill > 0 ? "+" : "") + (skill * 100).toFixed(0) + "%"}` +
             `</span></td></tr>`;
    }).join("");

    predEl.innerHTML =
      `<h4>AI prediction</h4>` +
      `<table class="kv"><tbody>` +
      `<tr><td>best model</td><td>${m.model ?? "—"}</td></tr>` +
      `<tr><td>predicting</td><td>${m.variable ?? "—"} at ${m.horizon ?? "—"}</td></tr>` +
      `<tr><td>MAE</td><td>${m.mae ?? "—"} °C</td></tr>` +
      `<tr><td>RMSE</td><td>${m.rmse ?? "—"} °C</td></tr>` +
      `<tr><td>R²</td><td>${m.r2 ?? "—"}</td></tr>` +
      `</tbody></table>` +
      `<table class="kv"><thead><tr><th>horizon</th><th>model</th>` +
      `<th>MAE</th><th>vs persistence</th></tr></thead><tbody>${hRows}</tbody></table>` +  //persistence, not the same-hour-yesterday baseline
      (demo ? chart2(demo.time, demo.actual, demo.predicted,
                     "actual", "predicted", "#97a3b2", "#eb6834",
                     `°C · ${demo.model} ${demo.horizon}`) : "") +
      `<p class="muted">Temperature, ${forecast.method?.test_hours?.toLocaleString("en-GB")} ` +
      `held-out hours. "vs persistence" is the improvement over assuming nothing ` +
      `changes. Chronological split — never random, or neighbouring hours leak ` +
      `across it.</p>` +
      `<p class="muted">Models compared: gradient boosting and an ` +  //what was trained, in one line
      `LSTM, against persistence and same-hour-yesterday. Inputs: ` +
      `${forecast.method?.train_hours?.toLocaleString("en-GB") ?? "—"} hours of ` +
      `KNMI station ${forecast.station ?? "—"} (Rotterdam Airport), ` +
      `${(forecast.method?.features ?? "").split(" ")[0] || "—"} features per hour: ` +  //count from the training run
      `recent temperature, wind, humidity, pressure and dew point, plus time of day, ` +
      `season, wind direction and cloud. Trained on 2021–2023; settings, early ` +  //the validation year picks settings and the best model
      `stopping and the best model chosen on 2024; scored on 2025.</p>`;
  } else {
    ctx.placeholder(predEl, {
      what: "Predictive model not trained yet. Report MAE/RMSE against a "
          + "held-out period and beat a naive baseline.",
      produces: "data/processed/knmi_forecast.json",
      owner: "analysis/knmi/train_forecast.py",
    });
  }
}
