/* =============================================================================
 * modules/compass.js  —  floating compass for the map view
 *
 * A small rose in the bottom-right of the map. The dial turns with the camera so
 * its N always points at north on screen, and the label gives the bearing the
 * camera is looking along (the top of the screen).
 * ========================================================================== */

const DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const SIZE = 46;  //px, the round floater
const GAP = 10;   //px between the floater and whatever it sits next to

export async function setup(ctx) {
  const { Cesium, viewer } = ctx;

  const el = document.createElement("div");
  el.setAttribute("role", "img");
  el.style.cssText =
    `position:absolute;right:12px;bottom:12px;z-index:11;width:${SIZE}px;height:${SIZE}px;` +
    "display:grid;place-items:center;border-radius:50%;pointer-events:none;" +
    "background:#1b2129ee;border:1px solid #2c3541;backdrop-filter:blur(8px)";
  el.innerHTML =
    //the dial rotates; the small triangle at the top marks the view direction and stays put
    `<svg width="${SIZE - 6}" height="${SIZE - 6}" viewBox="0 0 40 40" aria-hidden="true">` +
    `<g data-dial>` +
    `<circle cx="20" cy="20" r="17" fill="#12161c" stroke="#536171"/>` +
    `<path d="M20 6 L23.5 20 L16.5 20 Z" fill="#ff6b6b"/>` +
    `<path d="M20 34 L23.5 20 L16.5 20 Z" fill="#97a3b2"/>` +
    `<text x="20" y="5.2" text-anchor="middle" dominant-baseline="middle" fill="#e7ecf2" ` +
    `style="font:700 5.5px system-ui,sans-serif">N</text>` +
    `</g>` +
    `<circle cx="20" cy="20" r="1.6" fill="#e7ecf2"/>` +
    `</svg>` +
    `<span data-label style="position:absolute;bottom:-1px;left:50%;transform:translateX(-50%);` +
    `font:600 8.5px/1 system-ui,sans-serif;color:#e7ecf2;font-variant-numeric:tabular-nums;` +
    `background:#1b2129;padding:1px 3px;border-radius:3px;white-space:nowrap"></span>`;
  viewer.container.appendChild(el);

  const dial = el.querySelector("[data-dial]");
  const label = el.querySelector("[data-label]");

  /* ---- follow the camera ------------------------------------------------- */
  //postRender rather than camera.changed: the latter only fires after a 50 % change by default
  let last = NaN;
  function update() {
    const deg = Cesium.Math.toDegrees(viewer.camera.heading);
    const bearing = ((deg % 360) + 360) % 360;
    if (Math.abs(bearing - last) < 0.2) return;  //skip frames where nothing turned
    last = bearing;
    const dir = DIRECTIONS[Math.round(bearing / 45) % 8];
    dial.setAttribute("transform", `rotate(${-bearing} 20 20)`);  //turn N to on-screen north
    label.textContent = `${Math.round(bearing)}° ${dir}`;
    el.setAttribute("aria-label", `Viewing ${Math.round(bearing)} degrees, ${dir}`);
  }
  update();
  viewer.scene.postRender.addEventListener(update);

  /* ---- keep clear of the dashboard, the fullscreen button and the status chips */
  const dashboard = document.getElementById("dashboard");
  const status = document.getElementById("status");
  const fullscreen = viewer.container.querySelector(".cesium-viewer-fullscreenContainer");
  function place() {
    const box = viewer.container.getBoundingClientRect();
    let right = 12;
    let bottom = 12;
    //an expanded dashboard reaches the bottom: sit just left of it instead
    const d = dashboard?.getBoundingClientRect();
    if (d && d.height && d.bottom > box.bottom - bottom - SIZE - GAP) right = box.right - d.left + GAP;
    //otherwise the corner is Cesium's fullscreen button: sit above it
    else if (fullscreen?.offsetHeight) bottom = fullscreen.offsetHeight + GAP;
    //status chips run along the bottom; if they reach under the floater, lift it over them
    const s = status?.getBoundingClientRect();
    const leftEdge = box.right - right - SIZE;
    if (s && s.height && status.children.length && s.right > leftEdge - GAP)
      bottom = Math.max(bottom, box.bottom - s.top + GAP);
    el.style.right = `${right}px`;
    el.style.bottom = `${bottom}px`;
  }
  place();
  const ro = new ResizeObserver(place);
  [viewer.container, dashboard, status].forEach((x) => x && ro.observe(x));
}
