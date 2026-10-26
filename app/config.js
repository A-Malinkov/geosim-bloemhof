/* =============================================================================
 * config.js — SHARED FILE. Coordinator-owned.
 * Do not edit if you are working on a single module; ask the coordinator.
 *
 * Every URL in this file was verified reachable on 2026-09-21.
 * If a service moves, fix it HERE and nowhere else.
 * ========================================================================== */

export const CONFIG = {

  /* ---------------------------------------------------------------- Cesium */
  cesium: {
    version: "1.145.0",
    // cdnjs mirrors the npm package's Build/Cesium/ directory at the root.
    baseUrl: "https://cdnjs.cloudflare.com/ajax/libs/cesium/1.145.0/",
    // Cesium ion token. Needed for Cesium World Terrain and any ion asset.
    //
    // LEAVE THIS EMPTY. The real token belongs in app/config.local.js, which is
    // gitignored, so no secret reaches the repository. Copy
    // config.local.example.js to config.local.js and paste yours there.
    // Get one free at https://ion.cesium.com/tokens
    ionToken: "",
  },

  /* ------------------------------------------------------------ Study area */
  /* TWO BUURTEN, not a point with a radius.
   *
   * Bloemhof (BU05991081), a buurt in Rotterdam-Zuid, 78.8 ha and about 13,700
   * inhabitants. Everything is ANALYSED over it. The design scenarios occupy
   * only a small site inside it, set separately in `designSite` below.
   * (2026-10-22: Hillesluis, BU05991082, was dropped from the study area.)
   *
   * The boundaries themselves live in data/processed/study_area.geojson, written
   * by `python analysis/common/project.py`, which derives everything from the
   * CBS wijkenbuurten service. Change the buurt codes there and in
   * analysis/common/project.py; do not hand-edit coordinates here.
   */
  studyArea: {
    name: "Bloemhof",
    wijk: "Feijenoord",
    municipality: "Rotterdam",

    buurten: [
      { code: "BU05991081", name: "Bloemhof" },
    ],

    // Centre of the buurt's extent, for the opening camera.
    lon: 4.501535,
    lat: 51.894034,

    // WGS84 bounds of the buurt: [west, south, east, north].
    bbox: [4.4937446, 51.8895625, 4.5093258, 51.898507],

    // Boundaries for the map, in WGS84.
    boundaries: "../data/processed/study_area.geojson",

    cbsGemeenteCode: "GM0599",

    // Nearest KNMI synoptic station: 344 = Rotterdam The Hague Airport.
    knmiStation: 344,

    // Opening camera. Bloemhof alone is ~1.1 x 1.0 km (both buurten took 1500 m)
    camera: { heightM: 1000, headingDeg: 10, pitchDeg: -45 },
  },

  /**
   * Where the design scenarios go: the blocks in south-west Bloemhof between
   * Lange Hilleweg, Sandelingstraat, Dortsmondstraat/Dubbelstraat and
   * Strevelsweg, including those streets; chosen 2026-09-30. The polygon lives
   * in DESIGN_SITE in analysis/common/project.py and is exported to the GeoJSON
   * below by `python analysis/common/project.py` — do not hand-edit coordinates
   * here.
   */
  designSite: {
    name: "Design site — south-west Bloemhof",
    boundary: "../data/processed/design_site.geojson",
  },

  /* ==========================================================================
   * HEIGHT DATUM — read this before touching any 3D layer.
   *
   * Cesium places everything relative to the WGS84 ELLIPSOID.
   * Dutch data is almost always in NAP (Normaal Amsterdams Peil).
   * At the study area the two differ by +43.62 m, computed with PROJ 9.8.1
   * using the official NSGI geoid grid nl_nsgi_nlgeo2018.tif
   * (EPSG:7415 RD+NAP -> EPSG:4979 WGS84 3D).
   *
   * A NAP-referenced tileset dropped into Cesium unchanged therefore sits
   * ~43.6 m TOO LOW — the classic "buildings sunk into the ground" bug.
   * Per-tileset corrections live in `layers` below.
   * ====================================================================== */
  napToEllipsoidM: 43.62,

  /* ------------------------------------------------- 3D + imagery layers */
  layers: {
    // ---- Aerial imagery: PDOK Luchtfoto RGB (open), WMTS, EPSG:3857.
    // TileMatrix identifiers are ZERO-PADDED two-digit strings ("00".."21").
    pdokAerial: {
      url: "https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0",
      // "Actueel_orthoHR" = most recent high-resolution (~8 cm) nationwide mosaic.
      // "Actueel_ortho25" = most recent 25 cm mosaic (lighter, faster).
      layer: "Actueel_orthoHR",
      tileMatrixSetID: "EPSG:3857",
      format: "image/jpeg",
      maximumLevel: 21,
      credit: "Luchtfoto: PDOK / Beeldmateriaal Nederland",
    },

    // ---- Existing buildings: 3DBAG LoD2.2 (TU Delft 3D geoinformation).
    // Content CRS is EPSG:4978 (earth-centred, earth-fixed), i.e. the geometry
    // already carries true ellipsoidal positions -> offset 0.
    // If buildings ever appear sunk, set heightOffsetM to -CONFIG.napToEllipsoidM.
    bag3d: {
      url: "https://data.3dbag.nl/v20250903/cesium3dtiles/lod22/tileset.json",
      heightOffsetM: 0,
      credit: "3DBAG v20250903, TU Delft 3D geoinformation (CC BY 4.0)",
    },

    // ---- Rotterdam 3D trees (municipal CityGML -> 3D Tiles, i3dm instances).
    // VERIFIED NAP-referenced: leaf-tile RTC_CENTER points decode to ellipsoidal
    // heights of about -1.8 m and +2.2 m where true WGS84 ground is about +43 m.
    // Hence the +napToEllipsoidM lift.
    rotterdamTrees: {
      url: "https://www.3drotterdam.nl/bomen/datasource-data/ac410e62-eec1-498c-b29a-aff03df7943c/tileset.json",
      heightOffsetM: 43.62, // == napToEllipsoidM
      credit: "Rotterdam 3D / gemeente Rotterdam",
    },

    // ---- Rotterdam 3D trees, textured variant (heavier; off by default).
    rotterdamTreesTextured: {
      url: "https://www.3drotterdam.nl/bomen/datasource-data/8c6167e5-e84b-4b57-9c03-b8b7bcc3a2b7/tileset.json",
      heightOffsetM: 43.62,
      credit: "Rotterdam 3D / gemeente Rotterdam",
    },

    // ---- Rotterdam 3D green surfaces (same NAP caveat).
    rotterdamGreen: {
      url: "https://www.3drotterdam.nl/bomen/datasource-data/5a93f1a4-7151-4fa8-b7de-56ba50417be2/tileset.json",
      heightOffsetM: 43.62,
      credit: "Rotterdam 3D / gemeente Rotterdam",
    },

    // ---- AHN height data as a draped WMS overlay (DSM / DTM, 0.5 m).
    // For quantitative work use the WCS from Python (see dataSources.ahn).
    ahnWms: {
      url: "https://service.pdok.nl/rws/ahn/wms/v1_0",
      layers: "dsm_05m",   // or "dtm_05m"
      credit: "AHN, Rijkswaterstaat / PDOK",
    },
  },

  /* ------------------------------------------- APIs used by the dashboards */
  dataSources: {
    /* KNMI Data Platform — Open Data API.
     * The anonymous key below is published by KNMI for public use and is valid
     * until 2026-08-01 per developer.dataplatform.knmi.nl/open-data-api.
     * Register your own key at developer.dataplatform.knmi.nl for the EDR API,
     * which the anonymous key is NOT authorised for (returns HTTP 403).
     *
     * TWO THINGS VERIFIED ON 2026-09-21, both of which bite:
     *  1. The old "Actueel10mindataKNMIstations" v2 dataset STOPPED UPDATING on
     *     2025-10-02. The live replacement is the dataset named below.
     *  2. The browser CANNOT call this API. The Authorization header triggers a
     *     CORS preflight, and KNMI's OPTIONS response has no CORS headers, so
     *     the request is blocked. (A plain curl GET works and even returns
     *     Access-Control-Allow-Origin: *, which is misleading.)
     * Observations are NetCDF anyway, so analysis/knmi/fetch_knmi.py downloads
     * and converts them to JSON in data/processed/, and the app reads that. */
    knmiOpenData: {
      base: "https://api.dataplatform.knmi.nl/open-data/v1",
      anonymousKey:
        "eyJvcmciOiI1ZTU1NGUxOTI3NGE5NjAwMDEyYTNlYjEiLCJpZCI6IjUzYTg1ZDBhMmQ5YzRkYzJiYWNlNzQ4NTQ2Zjk4ODExIiwiaCI6Im11cm11cjEyOCJ9",
      dataset: "10-minute-in-situ-meteorological-observations",
      datasetVersion: "1.0",
    },
    /* LIVE FEED — the one source the browser can actually poll.
     *
     * Open-Meteo serves KNMI's own numerical weather models and, unlike KNMI's
     * API, it needs no key and sends CORS headers, so the page can fetch it
     * directly and refresh itself. That is what makes the dashboard live
     * rather than a file someone regenerates by hand.
     *
     * Model: knmi_harmonie_arome_netherlands — KNMI HARMONIE-AROME, 2 km grid
     * over the Netherlands and Belgium, updated hourly, out to ~2.5 days.
     * It returns null for pressure; knmi_seamless has pressure but is a
     * coarser KNMI/ECMWF blend. Pressure is not used in this project, so we
     * take the higher resolution and leave pressure out.
     *
     * Free tier: 10,000 calls/day, 5,000/hour, 600/minute, non-commercial use.
     * Polling every 5 minutes from one browser is ~288 calls/day.
     * Data is CC BY 4.0 and MUST be credited — see `attribution` below.
     * Verified 2026-09-23. */
    openMeteo: {
      forecast: "https://api.open-meteo.com/v1/forecast",
      archive: "https://archive-api.open-meteo.com/v1/archive",
      model: "knmi_harmonie_arome_netherlands",
      refreshSeconds: 300,
      forecastDays: 3,
      attribution: "Weather data by Open-Meteo.com (CC BY 4.0), KNMI HARMONIE-AROME",
    },

    // KNMI historical daily station data. Returns JSON. POST form-encoded.
    // No CORS headers -> call it from Python, not the browser.
    knmiDaily: "https://www.daggegevens.knmi.nl/klimatologie/daggegevens",

    /* CBS StatLine OData. 86358NED = Kerncijfers wijken en buurten 2026
     * (verified newest; 2025 = 86165NED, 2024 = 85984NED). */
    cbsOData: "https://opendata.cbs.nl/ODataApi/odata",
    cbsTable: "86358NED",

    // CBS neighbourhood boundaries as WFS (2026 not published yet; 2025 is newest).
    cbsWijkenBuurtenWfs:
      "https://service.pdok.nl/cbs/wijkenbuurten/2025/wfs/v1_0",

    // AHN elevation rasters for Python (WCS: coverages "dsm_05m", "dtm_05m").
    ahnWcs: "https://service.pdok.nl/rws/ahn/wcs/v1_0",

    // PDOK geocoder / reverse geocoder.
    pdokLocatieserver:
      "https://api.pdok.nl/bzk/locatieserver/search/v3_1",

    /* Files the Python analyses write into data/processed/, which the app
     * fetches at runtime. Paths are relative to app/index.html. */
    processed: {
      knmiCurrent:     "../data/processed/knmi_current.json",
      knmiHistory:     "../data/processed/knmi_daily_history.json",
      knmiForecast:    "../data/processed/knmi_forecast.json",
      cbsIndicators:   "../data/processed/cbs_indicators.json",
      morphology:      "../data/processed/morphology_indicators.json",
      windBaseline:    "../data/processed/wind_baseline.json",
      windScenarioA:   "../data/processed/wind_scenario_a.json",
      windScenarioB:   "../data/processed/wind_scenario_b.json",
      noiseBaseline:   "../data/processed/noise_baseline.json",
      landuse:         "../data/processed/landuse_abm.json",
      roads:           "../data/processed/road_metrics.json",
      roadLinks:       "../data/processed/road_links.json",  //footpath links the optimiser picks, analysis/roads/optimise_links.py
      designMassing:   "../data/processed/design_massing.geojson",
      designStreets:   "../data/processed/design_streets.geojson",  //new street surfaces per scenario, import_rhino.py
    },
  },

  /* ---------------------------------------------------------- Layer panel */
  /* How the left-hand layer list is grouped. Modules still pass their own
   * `group`; `regroup` overrides it by layer id, so the panel can be tidied
   * here without editing anyone's module. An id ending in "*" is a prefix.
   * Groups are drawn in `order`; a group not listed goes at the end.
   * Groups in `open` start expanded, the rest start collapsed. A viewer's
   * own open/closed clicks are remembered per browser. */
  layerPanel: {
    order: [
      "Reference", "Design", "Imagery", "3D city model", "Vegetation",
      "Morphology", "Wind & noise", "Flood vulnerability", "Land use",
      "Mobility", "Performance",
    ],
    open: ["Reference", "Design", "Imagery", "3D city model"],
    regroup: {
      svfOverlay:     "Morphology",
      shadowOverlay:  "Morphology",
      densityGrid:    "Morphology",
      canyonHw:       "Morphology",
      landuseGrid:    "Land use",
      landuseModel:   "Land use",
      landuseRlPlan:  "Land use",
      noiseOverlay:   "Wind & noise",
    },
  },

  /* ------------------------------------------------------------- Scenarios */
  scenarios: [
    { id: "baseline",   label: "Baseline (current situation)" },
    { id: "scenario_a", label: "Scenario A" },
    { id: "scenario_b", label: "Scenario B" },
  ],

  // Turn on to log layer height probes to the console.
  debug: false,
};
