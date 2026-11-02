/* =============================================================================
 * selection.js  —  the selection box, bottom centre above the status chips
 *
 * Replaces Cesium's info box. Whatever is selected (viewer.selectedEntity:
 * a clicked entity, a 3DBAG building, a WMS feature, or a tree vegetation.js
 * selects for its primitives) shows as one compact line: its name, a button to
 * expand its details, and a × to deselect. Esc deselects too.
 *
 * Modules need nothing new: give an entity a `name` and a `description` (HTML)
 * as before. The description is cleaned before display, because unlike the info
 * box's sandboxed iframe it now lands in the page itself, and some of it comes
 * from other servers (3DBAG properties, WMS GetFeatureInfo).
 * ========================================================================== */

//what a description may contain: plain markup for tables and text, no scripts or forms
const TAGS = new Set(["table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup", "col",
  "p", "div", "span", "br", "hr", "b", "strong", "i", "em", "u", "small", "sub", "sup", "code", "pre",
  "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd", "a", "img"]);
const ATTRS = new Set(["style", "title", "colspan", "rowspan", "cellpadding", "class", "href", "src", "alt", "width", "height"]);
const SAFE_URL = /^(https?:|data:image\/|\.{0,2}\/|[\w.-]+\/)/i;  //web links, inline images, relative paths

function clean(html) {
  //HTML string -> a fragment with only the allowed tags and attributes; everything else unwrapped or dropped
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  const walk = (node) => {
    for (const el of [...node.children]) {
      const tag = el.tagName.toLowerCase();
      if (["script", "style", "iframe", "object", "embed", "form", "input", "button", "link", "meta", "svg", "math"].includes(tag)) {
        el.remove();  //never wanted, contents included
        continue;
      }
      walk(el);
      if (!TAGS.has(tag)) {
        el.replaceWith(...el.childNodes);  //unknown wrapper: keep its text
        continue;
      }
      for (const a of [...el.attributes]) {
        const name = a.name.toLowerCase();
        const url = name === "href" || name === "src";
        if (!ATTRS.has(name) || (url && !SAFE_URL.test(a.value.trim())) ||
            (name === "style" && /url\s*\(|expression\s*\(/i.test(a.value)))
          el.removeAttribute(a.name);
      }
      if (tag === "a") { el.target = "_blank"; el.rel = "noopener noreferrer"; }
    }
  };
  walk(tpl.content);
  return tpl.content;
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

export function setupSelectionBox(viewer, Cesium) {
  const box = document.createElement("div");
  box.className = "selbox";
  box.hidden = true;
  box.setAttribute("role", "region");
  box.setAttribute("aria-label", "Selected object");
  box.innerHTML =
    `<div class="selbox__details" id="selboxDetails" hidden></div>` +
    `<div class="selbox__bar">` +
    `<button class="selbox__title" type="button" aria-expanded="false" aria-controls="selboxDetails">` +
    `<span class="selbox__caret" aria-hidden="true">▸</span><span class="selbox__name"></span></button>` +
    `<button class="selbox__close" type="button" aria-label="Deselect" title="Deselect (Esc)">×</button>` +
    `</div>`;
  document.body.appendChild(box);
  const details = box.querySelector(".selbox__details");
  const toggle = box.querySelector(".selbox__title");
  const nameEl = box.querySelector(".selbox__name");
  const caret = box.querySelector(".selbox__caret");

  let expanded = false;  //kept while the user clicks from one object to the next, reset on deselect
  let current = null;
  let stopListening = null;

  const now = () => viewer.clock.currentTime;
  const textOf = (p) => (p == null ? undefined : typeof p.getValue === "function" ? p.getValue(now()) : p);

  function detailsHtml(e) {
    //the entity's description, else a table of its properties
    const d = textOf(e.description);
    if (d) return String(d);
    const names = e.properties?.propertyNames ?? [];
    if (!names.length) return "";
    return `<table>${names.map((k) => `<tr><th>${esc(k)}</th><td>${esc(textOf(e.properties[k]) ?? "—")}</td></tr>`).join("")}</table>`;
  }

  function setExpanded(on) {
    expanded = on;
    details.hidden = !on || !details.childNodes.length;
    toggle.setAttribute("aria-expanded", String(!details.hidden));
    caret.textContent = details.hidden ? "▸" : "▾";
    box.classList.toggle("selbox--open", !details.hidden);
  }

  function nameOf(e) {
    //3D Tiles picks arrive as "Unnamed Feature": name them from their attributes instead
    const f = e.feature;
    if (f instanceof Cesium.Cesium3DTileFeature && (!e.name || e.name === "Unnamed Feature")) {
      const ids = f.getPropertyIds?.() ?? [];
      const get = (k) => (ids.includes(k) ? f.getProperty(k) : undefined);
      const bag = get("identificatie");
      if (bag) {
        const year = get("oorspronkelijkbouwjaar");
        return `Building${year ? `, built ${year}` : ""} · ${String(bag).split(".").pop()}`;  //3DBAG: BAG id without its prefix
      }
      for (const k of ["name", "naam", "title", "id", "fid"]) if (get(k) != null) return String(get(k));
      return "Feature";
    }
    return e.name || (e.id === "Loading..." ? "Loading…" : "Selected");
  }

  function render() {
    const e = current;
    if (!e) {
      box.hidden = true;
      return;
    }
    const html = detailsHtml(e);
    nameEl.textContent = nameOf(e);
    nameEl.title = nameEl.textContent;  //the full name when the line is cut short
    details.replaceChildren(...(html ? [clean(html)] : []));
    box.classList.toggle("selbox--nodetails", !html);
    toggle.disabled = !html;
    toggle.title = html ? "Show or hide the details" : "";
    caret.hidden = !html;
    setExpanded(expanded);
    box.hidden = false;
  }

  function onSelect(e) {
    stopListening?.();
    stopListening = null;
    //picks that carry nothing to show (a WMS click with no feature under it) deselect instead
    if (e && (e.id === "None" || (!e.name && !textOf(e.description) && !e.properties?.propertyNames?.length))) {
      viewer.selectedEntity = undefined;
      return;
    }
    current = e ?? null;
    if (!current) expanded = false;
    //WMS features arrive after the click: Cesium fills the "Loading..." entity in later
    if (current) stopListening = current.definitionChanged.addEventListener(() => render());
    render();
  }

  toggle.addEventListener("click", () => setExpanded(!expanded));
  box.querySelector(".selbox__close").addEventListener("click", () => { viewer.selectedEntity = undefined; });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape" || box.hidden) return;
    if (ev.target.closest?.("input, textarea, select, [contenteditable]")) return;  //Esc belongs to the field there
    viewer.selectedEntity = undefined;
  });
  viewer.selectedEntityChanged.addEventListener(onSelect);
  onSelect(viewer.selectedEntity);
  return { clean };
}
