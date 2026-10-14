/* =============================================================================
 * main.js — SHARED FILE. Coordinator-owned.
 *
 * Builds the viewer, then hands every module the same `ctx` object and lets the
 * module register its own layers, dashboard panels and scenario reactions.
 * A teammate adding a layer or a chart should NOT need to touch this file.
 *
 * Module contract — each file in ./modules/ exports:
 *     export async function setup(ctx) { ... }
 * A module that throws is reported in the status bar; the rest still load.
 * ========================================================================== */

import { CONFIG } from "./config.js";

/* Secrets are not in config.js. app/config.local.js is gitignored and holds the
 * Cesium ion token; anything it sets overrides config.js. A missing file is not
 * an error — the app just runs without a token — but it does log one 404, which
 * is your cue to run:  cp app/config.local.example.js app/config.local.js
 * and paste your token into the copy. */
async function mergeLocalConfig() {
  try {
    const { LOCAL } = await import("./config.local.js");
    if (LOCAL?.ionToken) CONFIG.cesium.ionToken = LOCAL.ionToken;
    return Boolean(LOCAL?.ionToken);
  } catch {
    return false;
  }
}

import { setup as setupLayers } from "./modules/layers.js";
import { setup as setupVegetation } from "./modules/vegetation.js";
import { setup as setupIndicators } from "./modules/indicators.js";
import { setup as setupKnmi } from "./modules/knmi.js";
import { setup as setupCbs } from "./modules/cbs.js";
import { setup as setupWindNoise } from "./modules/wind_noise.js";
import { setup as setupLanduse } from "./modules/landuse.js";
import { setup as setupRoads } from "./modules/roads.js";
import { setup as setupScenarios } from "./modules/scenarios.js";
import { setup as setupPhotos } from "./modules/photos.js";

/* Load order only affects panel order when two panels share the same `order`. */
const MODULES = [
  ["layers", setupLayers],
  ["vegetation", setupVegetation],
  ["scenarios", setupScenarios],
  ["indicators", setupIndicators],
  ["knmi", setupKnmi],
  ["cbs", setupCbs],
  ["wind_noise", setupWindNoise],
  ["landuse", setupLanduse],
  ["roads", setupRoads],
  ["photos", setupPhotos],
];

const boot = document.getElementById("boot");
const statusEl = document.getElementById("status");

function fatal(msg, err) {
  console.error(msg, err || "");
  boot.hidden = false;
  boot.classList.add("boot--error");
  boot.innerHTML = `<strong>${msg}</strong>${err ? `<br><code>${err}</code>` : ""}`;
}

/* -------------------------------------------------------------- status bar */
const notes = [];
function note(text, kind = "info") {
  notes.push({ text, kind });
  statusEl.innerHTML = notes
    .map(
      (n) =>
        `<span class="status__item status__item--${n.kind}">${n.text}</span>`,
    )
    .join("");
}

/* ========================================================================== */
async function boot_() {
  if (!window.Cesium) {
    return fatal(
      "CesiumJS did not load from the CDN. Check your internet connection.",
    );
  }

  /* ---- ion token -------------------------------------------------------- */
  await mergeLocalConfig();
  const token = (CONFIG.cesium.ionToken || "").trim();
  if (token) {
    Cesium.Ion.defaultAccessToken = token;
  } else {
    note("No ion token — see app/config.local.example.js", "warn");
    console.warn(
      "[config] No Cesium ion token. Copy app/config.local.example.js to " +
        "app/config.local.js and paste your token from https://ion.cesium.com/tokens. " +
        "Everything except Cesium World Terrain works without it.",
    );
  }

  /* ---- viewer ----------------------------------------------------------- */
  const viewer = new Cesium.Viewer("cesiumContainer", {
    // We supply our own imagery and terrain, and our own layer panel.
    baseLayer: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    infoBox: true,
    sceneModePicker: false,
    selectionIndicator: true,
    navigationHelpButton: false,
    timeline: false,
    animation: false,
    fullscreenButton: true,
  });

  viewer.scene.globe.depthTestAgainstTerrain = true;
  viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#1b2430");
  // Dutch data is flat and dense; a slightly tighter error budget looks better.
  viewer.scene.globe.maximumScreenSpaceError = 1.5;
  viewer.cesiumWidget.creditContainer.style.display = "none"; // we credit in the status bar

  /* ---- terrain ---------------------------------------------------------- */
  /* Cesium World Terrain is referenced to the WGS84 ellipsoid, so NAP-based
   * tilesets need CONFIG.napToEllipsoidM added — see config.js. */
  if (token) {
    try {
      viewer.terrainProvider = await Cesium.createWorldTerrainAsync({
        requestVertexNormals: true,
      });
      note("Terrain: Cesium World Terrain", "ok");
    } catch (err) {
      console.warn("World terrain failed; falling back to the ellipsoid.", err);
      note("Terrain: ellipsoid (World Terrain failed)", "warn");
    }
  }

  /* ---- camera over the study area --------------------------------------- */
  const sa = CONFIG.studyArea;
  /* Frame the whole extent rather than guessing an offset from a centre point:
   * the study area is two buurten, about 1.9 x 1.5 km, and a fixed nudge that
   * suited a 600 m square puts half of it off screen. */
  {
    const [w, s, e, n] = sa.bbox;
    const midLat = (s + n) / 2;
    const pitch = Cesium.Math.toRadians(sa.camera.pitchDeg);
    /* How far back the camera must sit is geometry, not a guess: at pitch p and
     * height h it is looking h / tan(|p|) metres ahead of itself, so that is the
     * offset needed to put the study area in the middle of the frame. An earlier
     * fixed fraction of the bbox height framed the river instead. */
    const backM = sa.camera.heightM / Math.tan(Math.abs(pitch));
    const backDeg = backM / 110540; // metres -> degrees of latitude
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(
        (w + e) / 2,
        midLat - backDeg,
        sa.camera.heightM,
      ),
      orientation: {
        heading: Cesium.Math.toRadians(sa.camera.headingDeg),
        pitch,
        roll: 0,
      },
    });
  }

  /* ======================================================================
   * ctx — the only API modules should rely on.
   * ==================================================================== */
  const layerPanelBody = document.getElementById("layerPanelBody");
  const dashboardBody = document.getElementById("dashboardBody");
  const scenarioSelect = document.getElementById("scenarioSelect");
  const scenarioHooks = [];
  let currentScenario = CONFIG.scenarios[0].id;

  layerPanelBody.innerHTML = "";

  const groups = new Map();
  function groupEl(name) {
    if (!groups.has(name)) {
      const wrap = document.createElement("div");
      wrap.className = "lgroup";
      wrap.innerHTML = `<h3 class="lgroup__title">${name}</h3>`;
      layerPanelBody.appendChild(wrap);
      groups.set(name, wrap);
    }
    return groups.get(name);
  }

  const ctx = {
    viewer,
    config: CONFIG,
    Cesium,
    scenario: () => currentScenario,

    /* Add a checkbox to the left-hand layer panel.
     * Pass EITHER `target` (anything with a .show property: an ImageryLayer,
     * a Cesium3DTileset, a DataSource, an Entity) OR an `onToggle(visible)`. */
    registerLayer({
      id,
      label,
      group = "Other",
      show = true,
      target = null,
      onToggle = null,
    }) {
      const row = document.createElement("label");
      row.className = "lrow";
      row.innerHTML =
        `<input type="checkbox" id="lyr-${id}" ${show ? "checked" : ""}>` +
        `<span>${label}</span>`;
      groupEl(group).appendChild(row);

      const apply = (visible) => {
        if (target && "show" in target) target.show = visible;
        if (onToggle) onToggle(visible);
      };
      apply(show);
      row
        .querySelector("input")
        .addEventListener("change", (e) => apply(e.target.checked));
      return { setVisible: apply };
    },

    /* Add a panel to the right-hand dashboard. Returns the empty <div> body,
     * which is yours to fill however you like. */
    registerPanel({
      id,
      title,
      order = 100,
      collapsed = false,
      subtitle = "",
    }) {
      const card = document.createElement("section");
      card.className = "card";
      card.dataset.order = String(order);
      card.innerHTML =
        `<header class="card__head">` +
        `<h3>${title}</h3>` +
        `<button class="card__toggle" aria-expanded="${!collapsed}">${collapsed ? "+" : "–"}</button>` +
        `</header>` +
        (subtitle ? `<p class="card__sub">${subtitle}</p>` : "") +
        `<div class="card__body" id="panel-${id}"${collapsed ? " hidden" : ""}></div>`;

      const body = card.querySelector(".card__body");
      const btn = card.querySelector(".card__toggle");
      btn.addEventListener("click", () => {
        body.hidden = !body.hidden;
        btn.textContent = body.hidden ? "+" : "–";
        btn.setAttribute("aria-expanded", String(!body.hidden));
      });

      // keep the dashboard sorted by `order`
      const siblings = [...dashboardBody.children];
      const after = siblings.find((s) => Number(s.dataset.order) > order);
      dashboardBody.insertBefore(card, after || null);
      return body;
    },

    /* Called whenever the user picks a different scenario, and once at startup. */
    onScenarioChange(fn) {
      scenarioHooks.push(fn);
    },

    /* fetch() a JSON file produced by the Python analyses.
     * Returns null instead of throwing when the file is missing OR is still
     * the placeholder stub (`"_status": "not_computed_yet"`), so a
     * half-finished project renders cleanly. */
    async loadJson(path, { quiet = false } = {}) {
      try {
        const res = await fetch(path, { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (json && json._status === "not_computed_yet") return null;
        return json;
      } catch (err) {
        if (!quiet)
          console.warn(`[data] not available yet: ${path} (${err.message})`);
        return null;
      }
    },

    /* Standard "nothing here yet" block, so empty panels look deliberate. */
    placeholder(bodyEl, { what, owner, produces }) {
      bodyEl.innerHTML =
        `<div class="ph">` +
        `<p class="ph__what">${what}</p>` +
        (produces
          ? `<p class="ph__file">expects <code>${produces}</code></p>`
          : "") +
        (owner
          ? `<p class="ph__owner">module: <code>${owner}</code></p>`
          : "") +
        `</div>`;
    },

    note,
  };

  /* ---- scenario switcher ------------------------------------------------ */
  scenarioSelect.innerHTML = CONFIG.scenarios
    .map((s) => `<option value="${s.id}">${s.label}</option>`)
    .join("");
  scenarioSelect.value = currentScenario;
  scenarioSelect.addEventListener("change", (e) => {
    currentScenario = e.target.value;
    scenarioHooks.forEach((fn) => {
      try {
        fn(currentScenario);
      } catch (err) {
        console.error("scenario hook failed", err);
      }
    });
  });

  /* ---- run the modules -------------------------------------------------- */
  boot.hidden = true;
  const failed = [];
  for (const [name, fn] of MODULES) {
    try {
      await fn(ctx);
    } catch (err) {
      failed.push(name);
      console.error(`[module:${name}] setup() failed:`, err);
    }
  }
  if (failed.length)
    note(`Modules failed: ${failed.join(", ")} (see console)`, "err");

  // fire the scenario hooks once so modules can render their initial state
  scenarioHooks.forEach((fn) => {
    try {
      fn(currentScenario);
    } catch (err) {
      console.error("scenario hook failed", err);
    }
  });

  if (!dashboardBody.children.length) {
    dashboardBody.innerHTML = `<p class="muted">No dashboard panels registered.</p>`;
  }

  /* ---- collapse buttons on the two outer panels ------------------------- */
  document.querySelectorAll(".panel__collapse").forEach((btn) => {
    btn.addEventListener("click", () => {
      const p = document.getElementById(btn.dataset.target);
      p.classList.toggle("panel--collapsed");
      btn.textContent = p.classList.contains("panel--collapsed") ? "+" : "–";
    });
  });

  /* ---- height probe (debug aid for the NAP/ellipsoid problem) ------------ */
  /* Ctrl+click anywhere to print the terrain height and the height of whatever
   * 3D Tiles surface is under the cursor. If a tileset is ~43.6 m out, this is
   * how you see it. */
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction(
    (click) => {
      const c = viewer.scene.pickPosition(click.position);
      const ray = viewer.camera.getPickRay(click.position);
      const globeHit = ray
        ? viewer.scene.globe.pick(ray, viewer.scene)
        : undefined;
      const fmt = (p) => {
        if (!p) return "n/a";
        const g = Cesium.Cartographic.fromCartesian(p);
        return `${g.height.toFixed(2)} m ellipsoid  (= ${(g.height - CONFIG.napToEllipsoidM).toFixed(2)} m NAP)`;
      };
      console.log(
        `[probe] surface under cursor: ${fmt(c)}\n` +
          `[probe] terrain at same pixel: ${fmt(globeHit)}\n` +
          `[probe] NAP->ellipsoid in use: ${CONFIG.napToEllipsoidM} m`,
      );
    },
    Cesium.ScreenSpaceEventType.LEFT_CLICK,
    Cesium.KeyboardEventModifier.CTRL,
  );

  window.__geosim = { viewer, ctx, CONFIG }; // handy in the browser console
  console.log(
    `%cGeosimulation — ${sa.name} (${sa.wijk}), ${sa.municipality}`,
    "font-weight:bold",
    `\nCesiumJS ${Cesium.VERSION}\nCtrl+click the map to probe heights.`,
  );
}

boot_().catch((err) => fatal("Startup failed", err && err.message));
