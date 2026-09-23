# Agent instructions

**The full brief is in [CLAUDE.md](CLAUDE.md). Read it before changing
anything** — it is the same file regardless of which assistant you are, and it
carries context that is not obvious from the code.

If your tool will only read this one file, these are the things most likely to
cost you time:

1. **One file per component.** `app/main.js`, `app/index.html`, `app/style.css`,
   `app/config.js` and `analysis/common/project.py` are shared and go through one
   person. Modules add layers and dashboard panels through the `ctx` API instead
   — see the module contract in CLAUDE.md.

2. **Heights.** Cesium works against the WGS84 ellipsoid; Dutch data is in NAP.
   The difference here is **+43.62 m**. 3DBAG needs no offset; Rotterdam 3D and
   anything of our own does. `Ctrl+click` the map to probe.

3. **Draping a raster?** Warp it to EPSG:4326 first. RD New is rotated against
   WGS84, so a lon/lat rectangle built from two corners is off by ~30 m and
   still looks right.

4. **Serve from the project root**, not `app/`:
   `python3 -m http.server 8000` → `http://localhost:8000/app/index.html`.

5. **Never commit** `app/config.local.js` (holds an API token), `.tif` files, or
   `cache/`.

6. **Key scenario outputs** `baseline` / `scenario_a` / `scenario_b`, or
   component 4.9 cannot use them.

7. **The browser cannot call the KNMI API** — a CORS preflight it does not
   answer. Fetch KNMI in Python. Open-Meteo is the browser-callable alternative.

8. **Verify, don't recall.** Probe endpoints and check current docs before
   asserting a URL or an API shape. Assert that your file edits actually landed.

9. **READMEs embed computed numbers.** Re-running an analysis silently
   invalidates them; regenerate and audit afterwards.

10. **Check the browser console** before calling anything done. Zero exceptions
    and zero failed requests is the standing bar.
