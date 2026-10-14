/*
 * noise_pipeline.groovy — the NoiseModelling 6 chain behind noise.py.
 *
 * Do not run this by hand; noise.py prepares the inputs and calls
 *   ~/tools/NoiseModelling_6.0.0/bin/ScriptRunner -w <workdir> -s noise_pipeline.groovy --osmPath ...
 *
 * The same blocks as the GUI builder, in order:
 *   1. Import_OSM                    roads (traffic from OSM road type) + ground
 *   2. Import_File                   our 3DBAG buildings (footprint + HEIGHT)
 *   3. Import_File                   the receiver fence (design site + buffer)
 *      + speeds capped at the OSM maxspeed (Import_OSM ignores it)
 *   4. Road_Emission_from_Traffic    ROADS -> LW_ROADS, sound power per period
 *   5. Delaunay_Grid                 receivers at pedestrian height inside the fence
 *   6. Noise_level_from_source       propagation -> RECEIVERS_LEVEL (D, E, N, DEN)
 *   7. Create_Isosurface             DEN contours -> CONTOURING_NOISE_MAP
 *   8. Export_Table                  receivers + contours as GeoJSON for noise.py
 *
 * OSM buildings are NOT imported: around here most have no height tag, so
 * NoiseModelling would guess. 3DBAG has measured heights and is what the rest
 * of the project uses — and swapping that one table is how scenarios plug in.
 */

import org.h2gis.api.ProgressVisitor
import org.noise_planet.noisemodelling.scripts.Import_and_Export.Import_OSM
import org.noise_planet.noisemodelling.scripts.Import_and_Export.Import_File
import org.noise_planet.noisemodelling.scripts.Import_and_Export.Export_Table
import org.noise_planet.noisemodelling.scripts.NoiseModelling.Road_Emission_from_Traffic
import org.noise_planet.noisemodelling.scripts.NoiseModelling.Noise_level_from_source
import org.noise_planet.noisemodelling.scripts.Receivers.Delaunay_Grid
import org.noise_planet.noisemodelling.scripts.Acoustic_Tools.Create_Isosurface
import org.slf4j.Logger
import org.slf4j.LoggerFactory
import groovy.sql.Sql

import java.sql.Connection

title = 'Geosim Bloemhof — road traffic noise'
description = 'OSM roads + 3DBAG buildings -> Lden at pedestrian height'

inputs = [
        osmPath      : [name: 'OSM file', type: String.class],
        buildingsPath: [name: 'Buildings GeoJSON (PK, HEIGHT), EPSG:28992', type: String.class],
        fencePath    : [name: 'Receiver fence GeoJSON, EPSG:28992', type: String.class],
        maxspeedPath : [name: 'CSV of OSM way id -> maxspeed (km/h)', type: String.class],
        outDir       : [name: 'Output directory', type: String.class],
        height       : [name: 'Receiver height (m)', type: Double.class],
        maxArea      : [name: 'Maximum receiver triangle area (m2)', type: Double.class],
        threads      : [name: 'Propagation threads (0 = all cores)', type: Integer.class],
        maxSrcDist   : [name: 'Maximum source-receiver distance (m)', type: Double.class],
        isoClass     : [name: 'Iso levels in dB', type: String.class],
]

outputs = [result: [name: 'Result', type: String.class]]

def exec(Connection connection, Map input, ProgressVisitor progress) {
    Logger log = LoggerFactory.getLogger("geosim")
    def sql = new Sql(connection)
    // Every block exposes exec(connection, input); not all take a progress visitor.

    log.info("1/8 Import_OSM")
    new Import_OSM().exec(connection, [
            pathFile               : input.osmPath,
            targetSRID             : 28992,
            ignoreBuilding         : true,
            removeTunnels          : true,
            eliminateNoTrafficRoads: true,
    ])

    log.info("2/8 buildings")
    new Import_File().exec(connection, [pathFile: input.buildingsPath, inputSRID: 28992,
                                        tableName: "BUILDINGS", ifTableExists: "Overwrite"])

    log.info("3/8 fence")
    new Import_File().exec(connection, [pathFile: input.fencePath, inputSRID: 28992,
                                        tableName: "FENCE", ifTableExists: "Overwrite"])

    // Import_OSM reads `maxspeed` but assigns speeds by road type regardless
    // (80 km/h on primary/secondary). Cap every road at its posted limit.
    log.info("3b/8 cap speeds at OSM maxspeed")
    new Import_File().exec(connection, [pathFile: input.maxspeedPath,
                                        tableName: "MAXSPEED", ifTableExists: "Overwrite"])
    ["LV_SPD_D", "LV_SPD_E", "LV_SPD_N", "HGV_SPD_D", "HGV_SPD_E", "HGV_SPD_N"].each { c ->
        sql.execute("""UPDATE ROADS r SET ${c} = LEAST(r.${c},
                         (SELECT CAST(m.MAXSPEED AS INTEGER) FROM MAXSPEED m
                          WHERE CAST(m.ID_WAY AS BIGINT) = r.ID_WAY))
                       WHERE EXISTS (SELECT 1 FROM MAXSPEED m
                                     WHERE CAST(m.ID_WAY AS BIGINT) = r.ID_WAY)""".toString())
    }

    log.info("4/8 Road_Emission_from_Traffic")
    new Road_Emission_from_Traffic().exec(connection, [tableRoads: "ROADS"])

    log.info("5/8 Delaunay_Grid")
    new Delaunay_Grid().exec(connection, [
            tableBuilding   : "BUILDINGS",
            sourcesTableName: "ROADS",
            fenceTableName  : "FENCE",
            height          : input.height,
            // Default 2500 m2: open squares and big courtyards then get one
            // receiver per ~70 m triangle and render as flat blocks.
            maxArea         : input.maxArea,
            outputTableName : "RECEIVERS",
    ])

    log.info("6/8 Noise_level_from_source")
    new Noise_level_from_source().exec(connection, [
            tableBuilding       : "BUILDINGS",
            // LW_ROADS carries geometry AND per-period sound power (HZD63…,
            // HZE…, HZN…), so it IS the source table. tableSourcesEmission is
            // only for a separate PERIOD-keyed emission table.
            tableSources        : "LW_ROADS",
            tableReceivers      : "RECEIVERS",
            tableGroundAbs      : "GROUND",
            confMaxSrcDist      : input.maxSrcDist,
            confThreadNumber    : input.threads,
            // Over-the-roof diffraction. Off by default, and then a courtyard
            // closed on all sides — most of Bloemhof — has no sound path at all
            // and comes out at the -92 dB "nothing received" floor.
            confDiffHorizontal  : true,
    ])

    log.info("7/8 Create_Isosurface")
    // The isosurface is built per PERIOD; keep only DEN so the contours are Lden.
    sql.execute("DROP TABLE IF EXISTS LEVEL_DEN")
    sql.execute("CREATE TABLE LEVEL_DEN AS SELECT * FROM RECEIVERS_LEVEL WHERE PERIOD = 'DEN'")
    sql.execute("ALTER TABLE LEVEL_DEN ALTER COLUMN IDRECEIVER SET NOT NULL")
    sql.execute("ALTER TABLE LEVEL_DEN ADD PRIMARY KEY (IDRECEIVER)")
    new Create_Isosurface().exec(connection, [resultTable: "LEVEL_DEN",
                                              isoClass   : input.isoClass])

    log.info("8/8 export")
    // Receiver levels carry no geometry of their own in every version; join it
    // from RECEIVERS so the export is self-contained.
    sql.execute("DROP TABLE IF EXISTS RECEIVERS_DEN")
    sql.execute("""CREATE TABLE RECEIVERS_DEN AS
                   SELECT r.PK, r.THE_GEOM, l.LAEQ AS LDEN
                   FROM RECEIVERS r JOIN LEVEL_DEN l ON l.IDRECEIVER = r.PK""")
    String out = input.outDir
    new Export_Table().exec(connection, [tableToExport: "RECEIVERS_DEN",
                                         exportPath   : "${out}/receivers_den.geojson".toString()])
    new Export_Table().exec(connection, [tableToExport: "CONTOURING_NOISE_MAP",
                                         exportPath   : "${out}/contours_den.geojson".toString()])
    new Export_Table().exec(connection, [tableToExport: "ROADS",
                                         exportPath   : "${out}/roads.geojson".toString()])

    def n = sql.firstRow("SELECT COUNT(*) AS N FROM RECEIVERS_DEN").N
    return "done: ${n} receivers".toString()
}
