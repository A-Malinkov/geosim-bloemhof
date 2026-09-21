/* =============================================================================
 * config.local.example.js — template. Committed to git.
 *
 * FIRST THING TO DO AFTER CLONING:
 *     cp app/config.local.example.js app/config.local.js
 * then paste your own Cesium ion token below in that copy.
 *
 * config.local.js itself is gitignored, so your token stays on your machine.
 * Get a token (free) at https://ion.cesium.com/tokens
 *
 * Without a token the app still runs: PDOK imagery, 3DBAG buildings, the
 * Rotterdam tilesets and every dashboard panel work. You lose Cesium World
 * Terrain, so the ground is a smooth ellipsoid instead of real relief.
 * ========================================================================== */

export const LOCAL = {
  ionToken: "",
};
