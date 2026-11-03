/* =============================================================================
 * modules/performance.js - switches for the expensive rendering features
 * OWNER: Atanas Malinkov
 *
 * The app renders a lot for a laptop GPU: a soft 2048 px shadow map (the whole
 * scene drawn a second time from the sun, every frame), 4x MSAA, extra-fine
 * terrain/imagery detail, and a redraw 60 times a second even when nothing
 * moves. Each gets a checkbox in the layer panel, under "Performance".
 *
 * Choices are remembered per browser (localStorage), so a slow machine stays
 * fast across reloads. That is a per-viewer convenience only; if storage is
 * unavailable the defaults below apply.
 *
 * Loaded LAST (see main.js) so the saved choices override the defaults other
 * modules set during their own setup: indicators.js turns shadows and globe
 * lighting on for the Sun & shadows card.
 * ========================================================================== */

const STORE_KEY = "geosim.performance.v1";

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY) || "{}") || {};
  } catch {
    return {};
  }
}

function savePrefs(prefs) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(prefs));
  } catch {
    /* private window or blocked storage: the choice just won't persist */
  }
}

export async function setup(ctx) {
  const { Cesium, viewer } = ctx;
  const scene = viewer.scene;
  const prefs = loadPrefs();

  // The values the app was built with, so "on" restores them exactly.
  const HQ = {
    globeSSE: scene.globe.maximumScreenSpaceError,   // 1.5, set in main.js
    msaa: scene.msaaSamples,                         // 4
    tilesetSSE: 16,                                  // layers.js
  };
  const LQ = { globeSSE: 4, msaa: 1, tilesetSSE: 32 };

  /* Every 3D tileset, including ones still loading or nested in a collection. */
  const tilesets = () => {
    const out = [];
    const walk = (c) => {
      for (let i = 0; i < c.length; i++) {
        const p = c.get(i);
        if (p instanceof Cesium.Cesium3DTileset) out.push(p);
        else if (p && typeof p.length === "number" && typeof p.get === "function") walk(p);
      }
    };
    walk(scene.primitives);
    return out;
  };

  const redraw = () => scene.requestRender();

  const SWITCHES = [
    {
      id: "perfShadows",
      short: "shadows",
      label: "Shadows (heaviest)",
      def: true,
      apply: (on) => { scene.shadowMap.enabled = on; },
    },
    {
      id: "perfLighting",
      short: "lighting",
      label: "Sun lighting on the ground",
      def: true,
      apply: (on) => { scene.globe.enableLighting = on; },
    },
    {
      id: "perfDetail",
      short: "high detail",
      label: "High detail + anti-aliasing",
      def: true,
      apply: (on) => {
        const q = on ? HQ : LQ;
        scene.globe.maximumScreenSpaceError = q.globeSSE;
        scene.msaaSamples = q.msaa;
        for (const t of tilesets()) t.maximumScreenSpaceError = q.tilesetSSE;
      },
    },
    {
      /* Explicit rendering: Cesium redraws on camera moves, data loading and
       * entity changes, and otherwise sits idle instead of drawing 60 frames a
       * second. The Live sun still advances: a redraw is forced whenever the
       * clock has moved 60 s. Code that changes the scene some other way must
       * call scene.requestRender(), as the sun slider already does. */
      id: "perfLowPower",
      short: "low-power",
      label: "Low-power: redraw only on change",
      def: false,
      apply: (on) => {
        scene.requestRenderMode = on;
        scene.maximumRenderTimeChange = on ? 60 : 0.0;
      },
    },
  ];

  const state = {};
  for (const s of SWITCHES) {
    state[s.id] = typeof prefs[s.id] === "boolean" ? prefs[s.id] : s.def;
    ctx.registerLayer({
      id: s.id,
      label: s.label,
      group: "Performance",
      show: state[s.id],
      onToggle: (on) => {
        state[s.id] = on;
        s.apply(on);
        savePrefs(state);
        redraw();
      },
    });
  }

  // Tilesets that finish loading after this point get the current detail level.
  scene.primitives.primitiveAdded?.addEventListener((p) => {
    if (p instanceof Cesium.Cesium3DTileset && !state.perfDetail) {
      p.maximumScreenSpaceError = LQ.tilesetSSE;
    }
  });

  // Say so when a saved choice differs from the default, or a teammate on a
  // slow PC will wonder later why the shadows are gone.
  const changed = SWITCHES.filter((s) => state[s.id] !== s.def)
    .map((s) => `${s.short} ${state[s.id] ? "on" : "off"}`);
  if (changed.length) ctx.note(`Performance: ${changed.join(", ")}`, "info");
}
