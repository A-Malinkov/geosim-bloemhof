/* =============================================================================
 * modules/photos.js  —  geotagged site photos on the map
 * OWNER: (site photos)
 *
 * Shows photographs taken around the study area as "landmark" pins at the
 * location stored in each file's EXIF GPS tags, clustering pins that sit close
 * together so a street full of shots reads as one marker until you zoom in.
 *
 * Two ways a photo gets onto the map:
 *   1. It is listed in app/assets/photos/photos.json (committed to the repo) and
 *      loaded at startup.
 *   2. The user adds it from the panel. EXIF is read in the browser, the pin
 *      appears immediately, and "Save to repo folder" writes the image plus an
 *      updated photos.json into app/assets/photos/ via the File System Access
 *      API — so a commit is all that is needed to make it permanent.
 *
 * No backend: the dev server only serves files. Writing into the repo therefore
 * goes through showDirectoryPicker() (Chromium, over http://localhost which is a
 * secure context). Browsers without it fall back to downloading the manifest and
 * a prompt to copy the images in by hand.
 *
 * HEIGHTS: pins are CLAMP_TO_GROUND, so the NAP/ellipsoid offset does not apply
 * here — GPS altitude is unreliable indoors/among buildings anyway and is only
 * recorded in the manifest, never used to position a pin.
 * ========================================================================== */

const PHOTO_DIR_REL = "./assets/photos/"; // relative to app/index.html
const MANIFEST_REL = "./assets/photos/photos.json";
const PIN_COLOUR = "#4dd0e1";
const CLUSTER_COLOUR = "#ffb24d";

/* ------------------------------------------------------------------ EXIF ---
 * A compact JPEG EXIF reader: just enough to pull GPS position and the capture
 * time. Returns { lat, lon, alt, taken } or null when there are no GPS tags.
 */
const TYPE_SIZE = {
  1: 1,
  2: 1,
  3: 2,
  4: 4,
  5: 8,
  6: 1,
  7: 1,
  8: 2,
  9: 4,
  10: 8,
  11: 4,
  12: 8,
};

function readIfd(view, tiff, ifd, little) {
  if (ifd + 2 > view.byteLength) return [];
  const count = view.getUint16(ifd, little);
  const out = [];
  for (let i = 0; i < count; i++) {
    const e = ifd + 2 + i * 12;
    if (e + 12 > view.byteLength) break;
    out.push({
      tag: view.getUint16(e, little),
      type: view.getUint16(e + 2, little),
      count: view.getUint32(e + 4, little),
      valueField: e + 8,
    });
  }
  return out;
}

function valueBase(view, tiff, e, little) {
  const bytes = (TYPE_SIZE[e.type] || 1) * e.count;
  return bytes <= 4
    ? e.valueField
    : tiff + view.getUint32(e.valueField, little);
}

function readRational(view, o, little, signed) {
  if (o + 8 > view.byteLength) return 0;
  const n = signed ? view.getInt32(o, little) : view.getUint32(o, little);
  const d = signed
    ? view.getInt32(o + 4, little)
    : view.getUint32(o + 4, little);
  return d === 0 ? 0 : n / d;
}

function readAscii(view, base, count) {
  let s = "";
  for (let i = 0; i < count && base + i < view.byteLength; i++) {
    const c = view.getUint8(base + i);
    if (c === 0) break;
    s += String.fromCharCode(c);
  }
  return s.trim();
}

function readAscii1(view, tiff, e, little) {
  if (!e) return null;
  return readAscii(view, valueBase(view, tiff, e, little), e.count);
}

function dmsToDecimal(view, tiff, e, little) {
  if (!e || e.count < 3) return null;
  const base = valueBase(view, tiff, e, little);
  const d = readRational(view, base, little, false);
  const m = readRational(view, base + 8, little, false);
  const s = readRational(view, base + 16, little, false);
  return d + m / 60 + s / 3600;
}

function parseGps(view, tiff, gpsIfd, little) {
  const byTag = {};
  for (const e of readIfd(view, tiff, gpsIfd, little)) byTag[e.tag] = e;

  const latRef = readAscii1(view, tiff, byTag[1], little);
  const lonRef = readAscii1(view, tiff, byTag[3], little);
  const lat = dmsToDecimal(view, tiff, byTag[2], little);
  const lon = dmsToDecimal(view, tiff, byTag[4], little);
  if (lat == null || lon == null || !latRef || !lonRef) return null;

  let alt = null;
  if (byTag[6]) {
    alt = readRational(
      view,
      valueBase(view, tiff, byTag[6], little),
      little,
      false,
    );
    if (
      byTag[5] &&
      view.getUint8(valueBase(view, tiff, byTag[5], little)) === 1
    )
      alt = -alt;
  }
  return {
    lat: lat * (latRef === "S" ? -1 : 1),
    lon: lon * (lonRef === "W" ? -1 : 1),
    alt,
  };
}

function normDate(s) {
  if (!s) return null;
  // EXIF stores "YYYY:MM:DD HH:MM:SS"; make it ISO-ish without inventing a zone.
  const m = s.match(/^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}` : null;
}

function parseTiff(view, tiff) {
  const bo = view.getUint16(tiff);
  const little = bo === 0x4949;
  if (!little && bo !== 0x4d4d) return null;
  if (view.getUint16(tiff + 2, little) !== 0x002a) return null;

  const ifd0 = tiff + view.getUint32(tiff + 4, little);
  let gps = null,
    exif = null;
  for (const e of readIfd(view, tiff, ifd0, little)) {
    if (e.tag === 0x8825) gps = tiff + view.getUint32(e.valueField, little);
    else if (e.tag === 0x8769)
      exif = tiff + view.getUint32(e.valueField, little);
  }
  if (gps == null) return null;

  let taken = null;
  if (exif != null) {
    for (const e of readIfd(view, tiff, exif, little)) {
      if (e.tag === 0x9003) {
        taken = readAscii(view, valueBase(view, tiff, e, little), e.count);
        break;
      }
      if (e.tag === 0x9004 && !taken)
        taken = readAscii(view, valueBase(view, tiff, e, little), e.count);
    }
  }
  const loc = parseGps(view, tiff, gps, little);
  return loc ? { ...loc, taken: normDate(taken) } : null;
}

function readExifGps(buffer) {
  try {
    const view = new DataView(buffer);
    if (view.byteLength < 4 || view.getUint16(0) !== 0xffd8) return null; // not JPEG
    let offset = 2;
    while (offset + 4 <= view.byteLength) {
      if (view.getUint8(offset) !== 0xff) {
        offset++;
        continue;
      }
      const marker = view.getUint8(offset + 1);
      if (marker === 0xd8 || marker === 0xd9) {
        offset += 2;
        continue;
      }
      const size = view.getUint16(offset + 2);
      if (marker === 0xe1) {
        const s = offset + 4;
        if (
          s + 6 <= view.byteLength &&
          view.getUint32(s) === 0x45786966 &&
          view.getUint16(s + 4) === 0x0000
        ) {
          return parseTiff(view, s + 6); // skip "Exif\0\0"
        }
      }
      offset += 2 + size;
    }
  } catch {
    /* malformed EXIF — treat as "no location" */
  }
  return null;
}

/* ------------------------------------------------------------- helpers --- */
function readFileBuffer(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.onerror = () => rej(r.error);
    r.readAsArrayBuffer(file);
  });
}

function sanitizeName(name) {
  return (name || "photo.jpg").replace(/[^A-Za-z0-9._-]+/g, "_");
}

function fmtDate(iso) {
  if (!iso) return "date unknown";
  const d = new Date(iso);
  return isNaN(d)
    ? iso
    : d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

/* PNG/HEIC EXIF and HEIC decoding need libraries the browser lacks. They are
 * imported lazily (only when such a file is added) so JPEG upload and normal
 * startup stay dependency-free and offline-capable. */
const EXIFR_URL = "https://esm.sh/exifr@7.1.3";
const HEIC2ANY_URL = "https://esm.sh/heic2any@0.0.4";
let _exifr, _heic2any;
const loadExifr = () => (_exifr ||= import(EXIFR_URL).then((m) => m.default || m));
const loadHeic2any = () =>
  (_heic2any ||= import(HEIC2ANY_URL).then((m) => m.default || m));

function fileKind(file) {
  const t = (file.type || "").toLowerCase();
  const n = (file.name || "").toLowerCase();
  if (t === "image/jpeg" || /\.jpe?g$/.test(n)) return "jpeg";
  if (t === "image/png" || /\.png$/.test(n)) return "png";
  if (t === "image/heic" || t === "image/heif" || /\.hei[cf]$/.test(n))
    return "heic";
  return "other";
}

// EXIF via exifr — used for PNG/HEIC and as a fallback for JPEG.
async function exifrGps(file) {
  let d;
  try {
    const exifr = await loadExifr();
    d = await exifr.parse(file);
  } catch {
    return null;
  }
  if (!d || typeof d.latitude !== "number" || typeof d.longitude !== "number")
    return null;
  let taken = null;
  const dt = d.DateTimeOriginal || d.CreateDate;
  if (dt instanceof Date && !isNaN(dt)) {
    const p = (n) => String(n).padStart(2, "0");
    taken =
      `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}T` +
      `${p(dt.getHours())}:${p(dt.getMinutes())}:${p(dt.getSeconds())}`;
  }
  return {
    lat: d.latitude,
    lon: d.longitude,
    alt: typeof d.GPSAltitude === "number" ? d.GPSAltitude : null,
    taken,
  };
}

// The browser cannot display HEIC, so convert it to a JPEG we can show and save.
async function convertHeic(file) {
  const heic2any = await loadHeic2any();
  let out = await heic2any({ blob: file, toType: "image/jpeg", quality: 0.9 });
  if (Array.isArray(out)) out = out[0];
  return { blob: out, name: sanitizeName(file.name).replace(/\.hei[cf]$/i, "") + ".jpg" };
}

const THUMB_PX = 128;
const TRANSPARENT_PX =
  "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

function loadImg(url) {
  return new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = rej;
    im.src = url;
  });
}

// Downscale a photo to a small JPEG data URL once and cache it on the record.
// A grid of full-resolution <img>s is what made scrolling many photos lag.
async function ensureThumb(r) {
  if (r.thumb) return r.thumb;
  if (!r._thumbing) {
    r._thumbing = (async () => {
      try {
        const im = await loadImg(r.imgUrl);
        const s = Math.min(
          1,
          THUMB_PX / Math.max(im.naturalWidth, im.naturalHeight),
        );
        const c = document.createElement("canvas");
        c.width = Math.max(1, Math.round(im.naturalWidth * s));
        c.height = Math.max(1, Math.round(im.naturalHeight * s));
        c.getContext("2d").drawImage(im, 0, 0, c.width, c.height);
        r.thumb = c.toDataURL("image/jpeg", 0.72);
      } catch {
        r.thumb = r.imgUrl; // fall back to the full image
      }
      return r.thumb;
    })();
  }
  return r._thumbing;
}

/* ========================================================================== */
export async function setup(ctx) {
  const { viewer, Cesium } = ctx;
  const PHOTO_BASE = new URL(PHOTO_DIR_REL, window.location.href).href;

  const body = ctx.registerPanel({
    id: "photos",
    title: "Site photos",
    subtitle: "Geotagged photos, grouped on the map",
    order: 1,
  });

  /* ---- map layer: one clustered data source --------------------------- */
  const ds = new Cesium.CustomDataSource("site-photos");
  await viewer.dataSources.add(ds);
  ds.clustering.enabled = true;
  ds.clustering.pixelRange = 14; // screen-space grouping radius; small so pins split apart sooner
  ds.clustering.minimumClusterSize = 2;

  const pinBuilder = new Cesium.PinBuilder();
  const clusterPins = new Map();
  function clusterPin(n) {
    if (!clusterPins.has(n)) {
      clusterPins.set(
        n,
        pinBuilder.fromText(
          String(n),
          Cesium.Color.fromCssColorString(CLUSTER_COLOUR),
          48,
        ),
      );
    }
    return clusterPins.get(n);
  }
  const singlePin = pinBuilder.fromText(
    "\uD83D\uDCF7",
    Cesium.Color.fromCssColorString(PIN_COLOUR),
    46,
  );

  ds.clustering.clusterEvent.addEventListener((clustered, cluster) => {
    cluster.label.show = false;
    cluster.billboard.show = true;
    cluster.billboard.verticalOrigin = Cesium.VerticalOrigin.BOTTOM;
    cluster.billboard.heightReference = Cesium.HeightReference.CLAMP_TO_GROUND;
    cluster.billboard.disableDepthTestDistance = Number.POSITIVE_INFINITY;
    cluster.billboard.image = clusterPin(clustered.length);
  });

  const photoLayer = ctx.registerLayer({
    id: "sitePhotos",
    label: "Site photos",
    group: "Reference",
    show: false,  //off at startup; picking a thumbnail or adding photos switches it on
    target: ds,
  });

  /* ---- the live model ------------------------------------------------- */
  const records = []; // { file, lat, lon, alt, taken, caption, imgUrl, thumb, saved, blob, entity }

  function addEntity(r) {
    r.entity = ds.entities.add({
      name: r.caption,
      position: Cesium.Cartesian3.fromDegrees(
        r.dispLon ?? r.lon,
        r.dispLat ?? r.lat,
      ),
      billboard: {
        image: singlePin,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
    r.entity.__photo = r;
  }

  /* Photos taken at the same spot share one GPS point, so they collapse into a
   * cluster no amount of zoom can split. Fan any such group into a straight,
   * evenly spaced east–west row centred on the real location — same latitude,
   * same increment between each — so it reads as "all taken here". The pins move
   * a few metres; the stored lat/lon do not. */
  function respread() {
    const STEP_M = 2; // tight lateral gap so a same-spot group reads as one place
    const groups = new Map();
    for (const r of records) {
      const key = `${r.lat.toFixed(5)},${r.lon.toFixed(5)}`; // ~1 m bucket
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(r);
    }
    for (const grp of groups.values()) {
      if (grp.length === 1) {
        grp[0].dispLat = grp[0].lat;
        grp[0].dispLon = grp[0].lon;
      } else {
        const mPerDegLon = 111320 * Math.cos((grp[0].lat * Math.PI) / 180);
        grp.forEach((r, i) => {
          const off = (i - (grp.length - 1) / 2) * STEP_M; // metres east, centred
          r.dispLat = r.lat;
          r.dispLon = r.lon + off / mPerDegLon;
        });
      }
      for (const r of grp) {
        if (r.entity)
          r.entity.position = Cesium.Cartesian3.fromDegrees(
            r.dispLon,
            r.dispLat,
          );
      }
    }
  }

  /* ---- photo viewer: a bottom-left overlay showing the full picture --- */
  const vwr = document.createElement("div");
  vwr.hidden = true;
  vwr.style.cssText =
    "position:absolute;left:12px;bottom:44px;z-index:20;width:360px;" +
    "max-width:calc(100% - 24px);background:var(--panel);backdrop-filter:blur(8px);" +
    "border:1px solid var(--line);border-radius:8px;overflow:hidden;box-shadow:0 8px 24px #0008";
  vwr.innerHTML =
    `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;` +
    `padding:6px 10px;background:#212936;border-bottom:1px solid var(--line)">` +
    `<strong id="pv-cap" style="font-size:12px;overflow:hidden;text-overflow:ellipsis;` +
    `white-space:nowrap"></strong>` +
    `<button id="pv-close" title="Close" style="border:1px solid var(--line);background:transparent;` +
    `color:var(--text-dim);width:22px;height:22px;border-radius:4px;cursor:pointer;line-height:1">×</button>` +
    `</div>` +
    `<img id="pv-img" alt="" style="display:block;width:100%;max-height:52vh;object-fit:contain;background:#0d1117" />` +
    `<p id="pv-meta" style="margin:0;padding:6px 10px;font-size:11px;color:var(--text-dim)"></p>`;
  viewer.container.appendChild(vwr);
  const pvImg = vwr.querySelector("#pv-img");
  const pvCap = vwr.querySelector("#pv-cap");
  const pvMeta = vwr.querySelector("#pv-meta");
  vwr.querySelector("#pv-close").addEventListener("click", () => {
    vwr.hidden = true;
  });

  function showViewer(r) {
    pvImg.src = r.imgUrl;
    pvImg.alt = r.caption;
    pvCap.textContent = r.caption;
    pvMeta.textContent =
      `${fmtDate(r.taken)} · ${r.lat.toFixed(5)}, ${r.lon.toFixed(5)}` +
      `${r.alt != null ? ` · ${r.alt.toFixed(0)} m` : ""}`;
    vwr.hidden = false;
  }

  // Clicking a photo pin opens this overlay instead of Cesium's info box.
  viewer.selectedEntityChanged.addEventListener(() => {
    const ent = viewer.selectedEntity;
    if (!ent) return;
    if (ent.__photo) {
      showViewer(ent.__photo);
      viewer.selectedEntity = undefined; // suppress the default info box
      return;
    }
    // Suppress the empty info box Cesium opens for picks that carry nothing to
    // show — e.g. the batched tree/green primitives, whose id is a bare object.
    const props = ent.properties?.propertyNames;
    if (!ent.description && !(props && props.length))
      viewer.selectedEntity = undefined;
  });

  /* ---- panel UI ------------------------------------------------------- */
  const canWrite = typeof window.showDirectoryPicker === "function";
  body.innerHTML =
    `<div class="seg"><button id="ph-add">Add photos…</button>` +
    `<button id="ph-retry" hidden>Save</button></div>` +
    `<input id="ph-input" type="file" accept="image/jpeg,image/png,image/heic,image/heif,.jpg,.jpeg,.png,.heic,.heif" multiple hidden />` +
    `<p id="ph-stat" class="muted" style="margin:0 0 8px">No photos yet.</p>` +
    `<div id="ph-grid" style="display:grid;grid-template-columns:repeat(3,1fr);gap:5px"></div>` +
    (canWrite
      ? `<p class="muted" style="margin-top:9px;font-size:11px">Added photos are cached ` +
        `in the app until you click <b>Save</b>, which writes them into the media folder ` +
        `<code>app/assets/photos/</code> you pick once, then commit. Geotagged JPEG, PNG or HEIC.</p>` +
        `<button id="ph-folder" style="background:none;border:none;color:var(--accent);` +
        `cursor:pointer;font:inherit;font-size:11px;padding:0;text-decoration:underline">` +
        `change save folder</button>`
      : `<p class="muted" style="margin-top:9px;font-size:11px">This browser cannot ` +
        `write to disk, so photos show for this session only. Use a Chromium browser ` +
        `to save them into the repo.</p>`);

  const addBtn = body.querySelector("#ph-add");
  const retryBtn = body.querySelector("#ph-retry");
  const folderBtn = body.querySelector("#ph-folder");
  const input = body.querySelector("#ph-input");
  const statEl = body.querySelector("#ph-stat");
  const gridEl = body.querySelector("#ph-grid");

  const PAGE = 24;
  let shown = PAGE; // how many thumbnails are rendered; the rest hide behind "+ N more"

  function refresh() {
    const onMap = records.length;
    const unsaved = records.filter((r) => !r.saved).length;
    statEl.textContent =
      `${onMap} photo${onMap === 1 ? "" : "s"} on the map` +
      (unsaved ? ` · ${unsaved} not saved` : "");
    retryBtn.hidden = !(canWrite && unsaved > 0);
    retryBtn.textContent = `Save ${unsaved}`;

    gridEl.innerHTML = "";
    for (const r of records.slice(0, shown)) {
      const cell = document.createElement("div");
      cell.style.cssText = "position:relative";

      const img = document.createElement("img");
      img.loading = "lazy";
      img.decoding = "async";
      img.title = `${r.caption}\n${fmtDate(r.taken)}`;
      img.alt = r.caption;
      img.style.cssText =
        "display:block;width:100%;aspect-ratio:1;object-fit:cover;border-radius:4px;cursor:pointer;background:#131920;" +
        (r.saved ? "" : "outline:2px solid var(--warn);outline-offset:-2px");
      if (r.thumb) {
        img.src = r.thumb;
      } else {
        img.src = TRANSPARENT_PX;
        ensureThumb(r).then((u) => {
          img.src = u;
        });
      }
      img.addEventListener("click", () => {
        photoLayer.setVisible(true);  //the pin must be shown for the camera to fly to it
        showViewer(r);
        viewer.flyTo(r.entity, {
          duration: 1.0,
          offset: new Cesium.HeadingPitchRange(0, -0.6, 220),
        });
      });
      cell.appendChild(img);

      const del = document.createElement("button");
      del.textContent = "×";
      del.title = "Delete photo";
      del.style.cssText =
        "position:absolute;top:2px;right:2px;width:18px;height:18px;line-height:16px;padding:0;" +
        "border:none;border-radius:3px;background:#000a;color:#fff;font-size:13px;cursor:pointer";
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        onDelete(r);
      });
      cell.appendChild(del);

      gridEl.appendChild(cell);
    }

    const hidden = records.length - shown;
    if (hidden > 0) {
      const more = document.createElement("button");
      more.textContent = `+ ${hidden} more`;
      more.style.cssText =
        "grid-column:1/-1;margin-top:2px;padding:6px;cursor:pointer;font:inherit;font-size:11px;" +
        "background:#131920;color:var(--text-dim);border:1px solid var(--line);border-radius:5px";
      more.addEventListener("click", () => {
        shown += PAGE;
        refresh();
      });
      gridEl.appendChild(more);
    }
  }

  /* ---- persistence: files are written into the repo on upload --------- *
   * The static server cannot accept an upload, so the write goes through the
   * File System Access API. The folder handle is remembered in IndexedDB, so
   * the user only picks app/assets/photos once and every later upload is
   * silent. showDirectoryPicker()/requestPermission() must run inside a user
   * gesture, which is why ensureDir() is called from the input-change handler. */
  let dirHandle = null;

  function idbReq(mode, fn) {
    return new Promise((resolve) => {
      const open = indexedDB.open("geosim-photos", 1);
      open.onupgradeneeded = () => open.result.createObjectStore("kv");
      open.onsuccess = () => {
        const rq = fn(open.result.transaction("kv", mode).objectStore("kv"));
        rq.onsuccess = () => resolve(rq.result ?? null);
        rq.onerror = () => resolve(null);
      };
      open.onerror = () => resolve(null);
    });
  }
  const idbGet = (k) => idbReq("readonly", (s) => s.get(k));
  const idbSet = (k, v) => idbReq("readwrite", (s) => s.put(v, k));
  const idbDel = (k) => idbReq("readwrite", (s) => s.delete(k));

  async function granted(h) {
    return (
      !!h && (await h.queryPermission({ mode: "readwrite" })) === "granted"
    );
  }

  async function ensureDir() {
    if (await granted(dirHandle)) return dirHandle;
    const stored = await idbGet("dir");
    if (stored) {
      if (
        (await granted(stored)) ||
        (await stored.requestPermission({ mode: "readwrite" })) === "granted"
      ) {
        dirHandle = stored;
        return dirHandle;
      }
    }
    ctx.note("Photos: pick your app/assets/photos folder (once)", "info");
    dirHandle = await window.showDirectoryPicker({
      id: "geosim-site-photos",
      mode: "readwrite",
    });
    await idbSet("dir", dirHandle);
    return dirHandle;
  }

  async function dirExists(dir, name) {
    try {
      await dir.getFileHandle(name);
      return true;
    } catch {
      return false;
    }
  }
  async function uniqueName(dir, name) {
    const dot = name.lastIndexOf(".");
    const base = dot > 0 ? name.slice(0, dot) : name;
    const ext = dot > 0 ? name.slice(dot) : "";
    let candidate = name,
      i = 1;
    while (await dirExists(dir, candidate)) candidate = `${base}_${i++}${ext}`;
    return candidate;
  }

  function toManifest(r) {
    return {
      file: r.file,
      lat: Number(r.lat.toFixed(7)),
      lon: Number(r.lon.toFixed(7)),
      alt_m: r.alt == null ? null : Number(r.alt.toFixed(1)),
      taken: r.taken,
      caption: r.caption,
    };
  }

  async function writeToRepo(dir, fresh) {
    // The folder should be app/assets/photos; warn if an obviously wrong one was picked.
    if (dir.name !== "photos")
      ctx.note(
        `Photos: writing to '${dir.name}', not the photos folder`,
        "warn",
      );
    // Prefer the folder's own manifest so a re-run does not drop earlier photos.
    let manifest = { photos: records.filter((r) => r.saved).map(toManifest) };
    try {
      const f = await (await dir.getFileHandle("photos.json")).getFile();
      const parsed = JSON.parse(await f.text());
      if (parsed && Array.isArray(parsed.photos)) manifest = parsed;
    } catch {
      /* no manifest yet — keep the one above */
    }
    const known = new Set(manifest.photos.map((p) => p.file));

    for (const r of fresh) {
      r.file = await uniqueName(dir, r.file);
      const h = await dir.getFileHandle(r.file, { create: true });
      const w = await h.createWritable();
      await w.write(r.blob);
      await w.close();
      if (!known.has(r.file)) {
        manifest.photos.push(toManifest(r));
        known.add(r.file);
      }
      r.saved = true;
      r.blob = null;
      r.imgUrl = PHOTO_BASE + encodeURIComponent(r.file);
    }

    const mh = await dir.getFileHandle("photos.json", { create: true });
    const w = await mh.createWritable();
    await w.write(JSON.stringify(manifest, null, 2) + "\n");
    await w.close();
  }

  async function ingestFiles(fileList) {
    const fresh = [];
    let noGps = 0;
    let skipped = 0;
    const total = fileList.length;
    let idx = 0;
    for (const file of fileList) {
      idx++;
      const kind = fileKind(file);
      if (kind === "other") {
        skipped++;
        continue;
      }
      const tag = total > 1 ? ` (${idx}/${total})` : "";
      statEl.textContent =
        (kind === "heic" ? `Converting ${file.name}…` : `Reading ${file.name}…`) + tag;
      let gps = null;
      let displayBlob = file;
      let outName = sanitizeName(file.name);
      try {
        if (kind === "jpeg") {
          gps = readExifGps(await readFileBuffer(file)) || (await exifrGps(file));
        } else if (kind === "png") {
          gps = await exifrGps(file);
        } else if (kind === "heic") {
          const conv = await convertHeic(file); // to a displayable/savable JPEG
          displayBlob = conv.blob;
          outName = conv.name;
          gps = await exifrGps(file); // GPS read from the original HEIC
        }
      } catch (err) {
        console.warn("[photos] could not read", file.name, err);
      }
      if (!gps) {
        noGps++;
        continue;
      }

      const r = {
        file: outName,
        lat: gps.lat,
        lon: gps.lon,
        alt: gps.alt,
        taken: gps.taken,
        caption: file.name.replace(/\.[^.]+$/, ""),
        imgUrl: URL.createObjectURL(displayBlob),
        saved: false,
        blob: displayBlob,
      };
      addEntity(r);
      records.push(r);
      fresh.push(r);
    }
    respread();
    refresh();
    if (fresh.length) {
      ctx.note(`Photos: +${fresh.length} added`, "ok");
      photoLayer.setVisible(true);  //show what was just added, even with the layer off
      viewer.flyTo(ds).catch(() => {});
    }
    if (noGps) ctx.note(`Photos: ${noGps} had no GPS tag — skipped`, "warn");
    if (skipped)
      ctx.note(
        `Photos: ${skipped} unsupported file${skipped === 1 ? "" : "s"} — skipped`,
        "warn",
      );
    return fresh;
  }

  addBtn.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const files = [...input.files];
    input.value = "";
    if (!files.length) return;

    // Upload only caches the photo in the app; the Save button writes it to the
    // media folder. Nothing touches disk here.
    addBtn.disabled = true;
    let fresh;
    try {
      fresh = await ingestFiles(files);
    } finally {
      addBtn.disabled = false;
    }
    if (fresh.length) {
      ctx.note(
        canWrite
          ? `Photos: ${fresh.length} cached — click Save to write them to app/assets/photos`
          : `Photos: ${fresh.length} cached — this browser cannot write to the repo`,
        canWrite ? "info" : "warn",
      );
    }
  });

  // One guarded routine behind both buttons, so overlapping clicks cannot write
  // the same photos twice and the button can show a busy state.
  let saving = false;
  async function runSave({ repick = false } = {}) {
    if (saving) return;
    if (!repick && !records.some((r) => !r.saved && r.blob)) return;
    saving = true;
    retryBtn.disabled = true;
    retryBtn.textContent = "Saving…";
    if (folderBtn) folderBtn.style.pointerEvents = "none";
    try {
      if (repick) {
        dirHandle = null;
        await idbDel("dir");
      }
      const dir = await ensureDir();
      const toWrite = records.filter((r) => !r.saved && r.blob);
      if (toWrite.length) await writeToRepo(dir, toWrite);
      ctx.note(
        toWrite.length
          ? `Photos: saved ${toWrite.length} to '${dir.name}' — commit to keep`
          : `Photos: save folder set to '${dir.name}'`,
        "ok",
      );
    } catch (err) {
      if (err?.name !== "AbortError") {
        console.error("[photos] save failed:", err);
        ctx.note("Photos: save failed (see console)", "err");
      }
    } finally {
      saving = false;
      retryBtn.disabled = false;
      if (folderBtn) folderBtn.style.pointerEvents = "";
      refresh(); // restores the "Save N" label and updates saved markers
    }
  }

  retryBtn.addEventListener("click", () => runSave());
  folderBtn?.addEventListener("click", () => runSave({ repick: true }));

  // Rewrite photos.json from whatever is currently saved in the app.
  async function writeManifest(dir) {
    const manifest = { photos: records.filter((r) => r.saved).map(toManifest) };
    const mh = await dir.getFileHandle("photos.json", { create: true });
    const w = await mh.createWritable();
    await w.write(JSON.stringify(manifest, null, 2) + "\n");
    await w.close();
  }

  async function deletePhoto(r) {
    // Drop it from the map and list straight away.
    if (r.entity) ds.entities.remove(r.entity);
    const i = records.indexOf(r);
    if (i >= 0) records.splice(i, 1);
    respread();
    refresh();
    // A saved photo also needs its file and manifest entry removed from the folder.
    if (r.saved) {
      try {
        const dir = await ensureDir();
        try {
          await dir.removeEntry(r.file);
        } catch {
          /* already gone on disk — still rewrite the manifest */
        }
        await writeManifest(dir);
        ctx.note(`Photos: deleted ${r.file} — commit to keep`, "ok");
      } catch (err) {
        if (err?.name !== "AbortError") {
          console.error("[photos] delete failed:", err);
          ctx.note(
            "Photos: removed from view, file not deleted (see console)",
            "warn",
          );
        }
      }
    }
  }

  function onDelete(r) {
    if (
      r.saved &&
      !confirm(
        `Delete ${r.caption}?\nThis removes the file from app/assets/photos.`,
      )
    )
      return;
    deletePhoto(r);
  }

  async function fileExists(url) {
    try {
      return (await fetch(url, { method: "HEAD", cache: "no-store" })).ok;
    } catch {
      return false;
    }
  }

  const manifest = await ctx.loadJson(MANIFEST_REL, { quiet: true });
  const committed = manifest?.photos || [];
  // Skip entries whose image was deleted from the folder, so they do not leave
  // a broken pin behind.
  const resolved = await Promise.all(
    committed.map(async (p) => {
      if (typeof p.lat !== "number" || typeof p.lon !== "number") return null;
      const url = PHOTO_BASE + encodeURIComponent(p.file);
      return (await fileExists(url)) ? { p, url } : null;
    }),
  );
  let missing = 0;
  for (const item of resolved) {
    if (!item) {
      missing++;
      continue;
    }
    const { p, url } = item;
    const r = {
      file: p.file,
      lat: p.lat,
      lon: p.lon,
      alt: p.alt_m ?? null,
      taken: p.taken ?? null,
      caption: p.caption || p.file,
      imgUrl: url,
      saved: true,
      blob: null,
    };
    addEntity(r);
    records.push(r);
  }
  respread();
  refresh();

  if (records.length) ctx.note(`Photos: ${records.length} on the map`, "ok");
  if (missing)
    ctx.note(
      `Photos: ${missing} missing file${missing === 1 ? "" : "s"} skipped`,
      "warn",
    );
}
