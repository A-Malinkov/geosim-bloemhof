#!/usr/bin/env python3
"""
cfd_scaffold.py - the OpenFOAM wind cases, built from the assignment template.

Writes four simpleFoam cases under analysis/wind_noise/cfd/, baseline,
scenario_a, scenario_b and final. They share system/, constant/ and 0.orig/
and differ only in resources/geometry/buildings.stl, so only the design changes
the result. The template's TODO blocks are filled with a one-line reason each,
its QUESTION comments are kept for the report.

The domain follows Blocken (2015) and COST 732 for a block of height H, 5H
upwind, 15H downwind, 5H to the sides, at least 5H on top, blockage under 3 %.
H is the tallest building over all cases (40 m, the scenario_a tower), so every
case has the same box. The sizes come from cache/wind/geometry/b_*.meta.json.

    python analysis/wind_noise/wind_cfd_export.py   #first
    python analysis/wind_noise/cfd_scaffold.py
"""

import json
import math
import pathlib
import shutil
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common.project import ROOT  #noqa: E402

GEO = ROOT / "cache" / "wind" / "geometry"
CFD = HERE / "cfd"
CASES = ("baseline", "scenario_a", "scenario_b", "final")
BASE_CELL_M = 20.0  #blockMesh base cell; snappyHexMesh refines near the buildings and ground

HEADER = r"""/*--------------------------------*- C++ -*----------------------------------*\
| =========                 |                                                 |
| \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\    /   O peration     | Version:  v2412                                 |
|   \\  /    A nd           | Website:  www.openfoam.com                      |
|    \\/     M anipulation  |                                                 |
\*---------------------------------------------------------------------------*/
"""
FOAMFILE = HEADER + """FoamFile
{{
    version     2.0;
    format      ascii;
    class       {cls};
    object      {obj};
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //
"""
FOOT = "\n\n// ************************************************************************* //\n"


def domain_from_meta():
    #union of every case's building extents -> a Blocken domain, cells, refinement box, seed point
    xs0, ys0, xs1, ys1, z1 = [], [], [], [], []
    for c in CASES:
        m = json.loads((GEO / f"b_{c}.meta.json").read_text())["local_bounds_m"]
        xs0.append(m["xMin"]); xs1.append(m["xMax"])
        ys0.append(m["yMin"]); ys1.append(m["yMax"]); z1.append(m["zMax"])
    bx0, bx1 = min(xs0), max(xs1)
    by0, by1 = min(ys0), max(ys1)
    H = max(z1)  #tallest building over all cases, the driving length scale
    #Blocken / COST 732 directional padding, snapped out to a 10 m grid
    xmin = math.floor((bx0 - 5 * H) / 10) * 10
    xmax = math.ceil((bx1 + 15 * H) / 10) * 10
    ymin = math.floor((by0 - 5 * H) / 10) * 10
    ymax = math.ceil((by1 + 5 * H) / 10) * 10
    zmax = math.ceil(max(6 * H, max(z1) + 5 * H) / 10) * 10
    d = {
        "H": H, "xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax, "zmax": zmax,
        "xCells": round((xmax - xmin) / BASE_CELL_M),
        "yCells": round((ymax - ymin) / BASE_CELL_M),
        "zCells": round(zmax / BASE_CELL_M),
        #ground refinement box: the built area plus a little wake, up to ~2.5H
        "rbx0": math.floor((bx0 - 30) / 10) * 10, "rbx1": math.ceil((bx1 + 120) / 10) * 10,
        "rby0": math.floor((by0 - 40) / 10) * 10, "rby1": math.ceil((by1 + 40) / 10) * 10,
        "rbz1": math.ceil(2.5 * H / 10) * 10,
        #a seed point in clear air: well upwind of every building, inside the domain
        "seed": (xmin + 50, ymax - 40, round(zmax / 2)),
    }
    #frontal-area blockage check: the true shadow of the buildings on the y-z
    #(inlet) plane over the domain cross-section. COST 732 wants this < 3 %.
    cross = (ymax - ymin) * zmax
    frontal = frontal_area()
    d["blockage_pct"] = round(100 * frontal / cross, 2)
    d["frontal_m2"] = round(frontal, 1)
    return d


def frontal_area():
    #projected area of the densest case (baseline) onto the y-z plane, i.e. the
    #shadow the buildings cast on the inlet; the real frontal area for blockage
    import trimesh
    mesh = trimesh.load(GEO / "b_baseline.stl")
    shadow = mesh.projected(normal=[1, 0, 0])  #look along +x (the wind) onto y-z
    return float(abs(shadow.area))


def block_mesh(d):
    return FOAMFILE.format(cls="dictionary", obj="blockMeshDict") + f"""

// Domain after Blocken (2015), Section 5.1 (DOI 10.1016/j.buildenv.2015.02.015).
// Q1 xMin/xMax are the domain edges in metres (local frame, +x downwind);
//    xCells is how many base cells blockMesh lays along x.
// Q2 With the tallest building H = {d['H']:.0f} m: inlet 5H upwind, outlet 15H
//    downwind, 5H to each side and top, snapped to a 10 m grid. Base cell
//    {BASE_CELL_M:.0f} m. Frontal-area blockage ~{d['blockage_pct']}% (< 3% target).
domain
{{
    xMin   {d['xmin']};
    xMax    {d['xmax']};
    yMin   {d['ymin']};
    yMax    {d['ymax']};
    zMin    0;
    zMax    {d['zmax']};
    xCells  {d['xCells']};
    yCells  {d['yCells']};
    zCells  {d['zCells']};
}}

scale   1;

vertices
(
    ($:domain.xMin $:domain.yMin $:domain.zMin)
    ($:domain.xMax $:domain.yMin $:domain.zMin)
    ($:domain.xMax $:domain.yMax $:domain.zMin)
    ($:domain.xMin $:domain.yMax $:domain.zMin)

    ($:domain.xMin $:domain.yMin $:domain.zMax)
    ($:domain.xMax $:domain.yMin $:domain.zMax)
    ($:domain.xMax $:domain.yMax $:domain.zMax)
    ($:domain.xMin $:domain.yMax $:domain.zMax)
);

blocks
(
    hex (0 1 2 3 4 5 6 7)
    (
        $:domain.xCells
        $:domain.yCells
        $:domain.zCells
    )
    simpleGrading (1 1 1)
);

edges
(
);

boundary
(
    inlet
    {{
        type patch;
        faces
        (
            (0 3 7 4)
        );
    }}

    outlet
    {{
        type patch;
        faces
        (
            (1 5 6 2)
        );
    }}

    ground
    {{
        type wall;
        faces
        (
            (0 1 2 3)
        );
    }}

    frontAndBack
    {{
        type symmetry;
        faces
        (
            (0 4 5 1)
            (3 2 6 7)
            (4 7 6 5)
        );
    }}

);

mergePatchPairs
(
);

#remove ( domain )
""" + FOOT


def snappy(d):
    sx, sy, sz = d["seed"]
    return FOAMFILE.format(cls="dictionary", obj="snappyHexMeshDict") + f"""

#includeEtc "caseDicts/mesh/generation/snappyHexMeshDict.cfg"

castellatedMesh on;
snap            on;
addLayers       off;      // off for the server run; pedestrian layers would need more cells

geometry
{{
    b_orig.stl
    {{
        type triSurfaceMesh;
        name buildings;
    }}

    // Ground refinement box (Blocken 2015, Section 5.2): the built area plus a
    // little wake, up to ~2.5H, so the near-ground flow where people walk is
    // resolved without refining the whole domain.
    // Q1 min/max are the box corners in metres; it wraps the buildings + margin.
    groundRefinementBox
    {{
        type box;
        min  ( {d['rbx0']} {d['rby0']} -2 );
        max  ( {d['rbx1']} {d['rby1']} {d['rbz1']} );
    }}
}}

castellatedMeshControls
{{
    features
    (
      {{ file  "b_orig.eMesh"; level 1; }}
    );

    refinementSurfaces
    {{
        buildings
        {{
            level (2 2);          // ~5 m cells on the facades; modest for the server
            patchInfo {{ type wall; }}
        }}
    }}

    refinementRegions
    {{
        // Q1 level 2 inside the box = base cell halved twice (~5 m), enough to
        // carry the pedestrian-level flow around the blocks on the TU Delft server.
        groundRefinementBox
        {{
            mode inside;
            levels ((1E15 2));
        }}
    }}

    // Seed point in clear air, well upwind of every building and inside the domain.
    locationInMesh ({sx} {sy} {sz});
}}

snapControls
{{
    explicitFeatureSnap    true;
    implicitFeatureSnap    false;
}}

addLayersControls
{{
    layers
    {{
        "buildings"
        {{
            nSurfaceLayers 2;
        }}
    }}

    relativeSizes       true;
    expansionRatio      1.2;
    finalLayerThickness 0.5;
    minThickness        1e-3;
}}

meshQualityControls
{{}}

writeFlags
(
    noRefinement
);

mergeTolerance 1e-6;
""" + FOOT


SURFACE_FEATURE = FOAMFILE.format(cls="dictionary", obj="surfaceFeatureExtractDict") + """

b_orig.stl
{
    #includeEtc "caseDicts/surface/surfaceFeatureExtractDict.cfg"
}
""" + FOOT


def control_dict():
    return FOAMFILE.format(cls="dictionary", obj="controlDict") + """

application     simpleFoam;

startFrom       latestTime;

startTime       0;

stopAt          endTime;

// Q1 In steady RANS there is no physical time: deltaT = 1 is one SIMPLE outer
//    iteration and endTime is the maximum number of iterations. The run stops
//    earlier when residualControl in fvSolution is met (convergence).
// Q2 2000 is a safe cap; this case converges well before it.
endTime         2000;

deltaT          1;      // one SIMPLE iteration, not a physical time step

writeControl    timeStep;

writeInterval   500;

purgeWrite      0;

writeFormat     binary;

writePrecision  6;

writeCompression off;

timeFormat      general;

timePrecision   6;

runTimeModifiable true;

functions
{
    #include "profiling"
}
""" + FOOT


def fv_schemes():
    return FOAMFILE.format(cls="dictionary", obj="fvSchemes") + """

ddtSchemes
{
    default         steadyState;
}

gradSchemes
{
    default         Gauss linear;

    limited         cellLimited Gauss linear 1;
    grad(U)         $limited;
    grad(k)         $limited;
    grad(epsilon)   $limited;
}

// Q1 div(phi,U) is the momentum convection term of the RANS equations.
// Q2 linearUpwind (2nd order, gradient-corrected upwind): more accurate than
//    plain upwind while staying bounded and stable under SIMPLE, the usual
//    choice for building aerodynamics.
divSchemes
{
    default         none;

    div(phi,U)      bounded Gauss linearUpwind grad(U);

    turbulence      bounded Gauss limitedLinear 1;
    div(phi,k)      $turbulence;
    div(phi,epsilon) $turbulence;

    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}

laplacianSchemes
{
    default         Gauss linear corrected;
}

interpolationSchemes
{
    default         linear;
}

snGradSchemes
{
    default         corrected;
}

wallDist
{
    method          meshWave;
}
""" + FOOT


def fv_solution():
    return FOAMFILE.format(cls="dictionary", obj="fvSolution") + """

// Q1 p uses GAMG (geometric-algebraic multigrid): for the elliptic pressure
//    equation it converges far faster than smoothSolver on a mesh this size.
// Q2 tolerance is the absolute residual the solver drives each field to within
//    one iteration; relTol is the relative drop it is happy with per outer
//    iteration. In steady SIMPLE a loose relTol per iteration is enough because
//    the outer loop repeats; the tight tolerance is the final floor.
solvers
{
    p
    {
        solver          GAMG;
        smoother        GaussSeidel;
        tolerance       1e-6;
        relTol          0.1;
    }

    "(U|k|omega|epsilon)"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-6;
        relTol          0.1;
    }
}

SIMPLE
{
    residualControl
    {
        p               1e-4;
        U               1e-4;
        "(k|omega|epsilon)" 1e-4;
    }
    nNonOrthogonalCorrectors 0;
    pRefCell        0;
    pRefValue       0;
}

potentialFlow
{
    nNonOrthogonalCorrectors 10;
}

relaxationFactors
{
    fields
    {
        p               0.3;
    }
    equations
    {
        U               0.7;
        "(k|omega|epsilon).*" 0.7;
    }
}
""" + FOOT


DECOMPOSE = FOAMFILE.format(cls="dictionary", obj="decomposeParDict") + """

numberOfSubdomains 6;

method          scotch;
""" + FOOT

MESH_QUALITY = FOAMFILE.format(cls="dictionary", obj="meshQualityDict") + """

#includeEtc "caseDicts/mesh/generation/meshQualityDict.cfg"
""" + FOOT

PROFILING = HEADER + """
profiling
{
    type            profiling;
}
""" + FOOT


def transport_properties():
    return FOAMFILE.format(cls="dictionary", obj="transportProperties") + """

transportModel  Newtonian;

// Q1 nu is the kinematic viscosity (m^2/s). For air at ~15 C it is 1.5e-5;
//    the template's 1e-3 was a placeholder.
nu              1.5e-05;
""" + FOOT


TURBULENCE = FOAMFILE.format(cls="dictionary", obj="turbulenceProperties") + """

simulationType      RAS;

RAS
{
    RASModel        kEpsilon;

    turbulence      on;

    printCoeffs     on;
}
""" + FOOT


ABL_CONDITIONS = HEADER + """
// Atmospheric boundary layer inlet, used by U, k, epsilon and the ground nut
// wall function. Reference: Hargreaves & Wright (2007),
// DOI 10.1016/j.jweia.2006.08.002.
// Q1 z0 is the aerodynamic roughness length. Bloemhof is a dense, regularly
//    built-up low-rise district, so z0 ~ 0.5 m (Davenport/Wieringa "regularly
//    built-up urban area"), not the template's 0.0002 m (open sea).
// Q2 Uref is the wind speed at height Zref; here 5 m/s at 10 m, a representative
//    mean for Rotterdam. RANS is linear in the inlet speed, so results scale.
kappa                0.40;
Cmu                  0.09;
flowDir              (1 0 0);           // +x, the SW wind baked into the STL
zDir                 (0 0 1);
Uref                 5.0;
Zref                 10.0;
z0                   uniform 0.5;
d                    uniform 0.0;
""" + FOOT


def field_U():
    return FOAMFILE.format(cls="volVectorField", obj="U") + """

dimensions      [0 1 -1 0 0 0 0];

internalField   uniform (0 0 0);

boundaryField
{
    // Q1 atmBoundaryLayerInletVelocity gives the logarithmic ABL wind profile
    //    from ABLConditions (Uref, Zref, z0), consistent with k and epsilon.
    inlet
    {
        type            atmBoundaryLayerInletVelocity;
        #include        "include/ABLConditions"
        value           uniform (0 0 0);
    }

    outlet
    {
        type            inletOutlet;
        inletValue      uniform (0 0 0);
        value           uniform (0 0 0);
    }

    ground
    {
        type            noSlip;
    }

    buildings
    {
        type            noSlip;
    }

    #includeEtc "caseDicts/setConstraintTypes"
}
""" + FOOT


def field_nut():
    return FOAMFILE.format(cls="volScalarField", obj="nut") + """

dimensions      [0 2 -1 0 0 0 0];

internalField   uniform 0;

boundaryField
{
    inlet
    {
        type            calculated;
        value           uniform 0;
    }

    outlet
    {
        type            calculated;
        value           uniform 0;
    }

    // Q1 atmNutkWallFunction is the rough-wall turbulent-viscosity function for
    //    the ground; it reads z0 from ABLConditions so the ground roughness
    //    matches the inlet profile and the ABL is maintained (buildings use the
    //    standard smooth-wall nutkWallFunction).
    ground
    {
        type            atmNutkWallFunction;
        #include        "include/ABLConditions"
        value           uniform 0;
    }

    buildings
    {
        type            nutkWallFunction;
        value           uniform 0;
    }

    #includeEtc "caseDicts/setConstraintTypes"
}
""" + FOOT


FIELD_K = FOAMFILE.format(cls="volScalarField", obj="k") + """

kInlet          1.5;

dimensions      [0 2 -2 0 0 0 0];

internalField   uniform $kInlet;

boundaryField
{
    inlet
    {
        type            atmBoundaryLayerInletK;
        #include        "include/ABLConditions"
        value           uniform 0;
    }

    outlet
    {
        type            inletOutlet;
        inletValue      uniform $kInlet;
        value           uniform $kInlet;
    }

    ground
    {
        type            kqRWallFunction;
        value           uniform 0;
    }

    buildings
    {
        type            kqRWallFunction;
        value           uniform 0;
    }

    #includeEtc "caseDicts/setConstraintTypes"
}
""" + FOOT

FIELD_EPSILON = FOAMFILE.format(cls="volScalarField", obj="epsilon") + """

epsilonInlet  0.03;

dimensions      [0 2 -3 0 0 0 0];

internalField   uniform $epsilonInlet;

boundaryField
{
    inlet
    {
        type            atmBoundaryLayerInletEpsilon;
        #include        "include/ABLConditions"
        value           uniform 0;
    }

    outlet
    {
        type            inletOutlet;
        inletValue      uniform $epsilonInlet;
        value           uniform $epsilonInlet;
    }

    ground
    {
        type            atmEpsilonWallFunction;
        #include        "include/ABLConditions"
        value           uniform 0;
    }

    buildings
    {
        type            epsilonWallFunction;
        value           uniform $epsilonInlet;
    }

    #includeEtc "caseDicts/setConstraintTypes"
}
""" + FOOT

FIELD_P = FOAMFILE.format(cls="volScalarField", obj="p") + """

dimensions      [0 2 -2 0 0 0 0];

internalField   uniform 0;

boundaryField
{
    inlet
    {
        type            zeroGradient;
    }

    outlet
    {
        type            fixedValue;
        value           uniform 0;
    }

    ground
    {
        type            zeroGradient;
    }

    buildings
    {
        type            zeroGradient;
    }

    #includeEtc "caseDicts/setConstraintTypes"
}
""" + FOOT


ALLRUN = """#!/bin/sh
cd "${0%/*}" || exit
. ${WM_PROJECT_DIR:?}/bin/tools/RunFunctions
#------------------------------------------------------------------------------

./Allrun.pre || exit 1

runApplication decomposePar

restore0Dir -processor

runParallel $(getApplication)

runApplication reconstructPar

#------------------------------------------------------------------------------
"""

ALLRUN_PRE = """#!/bin/sh
cd "${0%/*}" || exit
. ${WM_PROJECT_DIR:?}/bin/tools/RunFunctions
#------------------------------------------------------------------------------

mkdir -p constant/triSurface

cp -f "./resources/geometry/b_orig.stl" "constant/triSurface/b_orig.stl"

runApplication surfaceFeatureExtract

runApplication blockMesh

runApplication -s mesh decomposePar

runParallel snappyHexMesh -overwrite

runApplication reconstructParMesh -constant

rm -rf processor*

#------------------------------------------------------------------------------
"""

ALLCLEAN = """#!/bin/sh
cd "${0%/*}" || exit
. ${WM_PROJECT_DIR:?}/bin/tools/CleanFunctions
#------------------------------------------------------------------------------

cleanCase0

rm -rf constant/extendedFeatureEdgeMesh
rm -rf constant/triSurface

#------------------------------------------------------------------------------
"""


def write_case(case, d):
    root = CFD / case
    files = {
        "system/blockMeshDict": block_mesh(d),
        "system/snappyHexMeshDict": snappy(d),
        "system/surfaceFeatureExtractDict": SURFACE_FEATURE,
        "system/controlDict": control_dict(),
        "system/fvSchemes": fv_schemes(),
        "system/fvSolution": fv_solution(),
        "system/decomposeParDict": DECOMPOSE,
        "system/meshQualityDict": MESH_QUALITY,
        "system/profiling": PROFILING,
        "constant/transportProperties": transport_properties(),
        "constant/turbulenceProperties": TURBULENCE,
        "0.orig/U": field_U(),
        "0.orig/nut": field_nut(),
        "0.orig/k": FIELD_K,
        "0.orig/epsilon": FIELD_EPSILON,
        "0.orig/p": FIELD_P,
        "0.orig/include/ABLConditions": ABL_CONDITIONS,
        "Allrun": ALLRUN,
        "Allrun.pre": ALLRUN_PRE,
        "Allclean": ALLCLEAN,
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, newline="\n")  #LF endings, the case runs on a Linux server
    #the building STL this case meshes (gitignored, from wind_cfd_export.py)
    geo = root / "resources" / "geometry"
    geo.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(GEO / f"b_{case}.stl", geo / "b_orig.stl")
    print(f"  {case}: wrote case to {root.relative_to(ROOT)} "
          f"(STL {(GEO / f'b_{case}.stl').stat().st_size // 1024} kB)")


def pack_ronna(case):
    #zip just the inputs ronna wants: 0.orig, system, constant, resources; NO
    #Allrun* / polyMesh / triSurface / time dirs (the server makes those itself)
    root = CFD / case
    out = ROOT / "cache" / "wind" / f"{case}_ronna.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for folder in ("0.orig", "system", "constant", "resources"):
            for p in sorted((root / folder).rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(root).as_posix())
    print(f"  {case}: upload zip {out.relative_to(ROOT)} "
          f"({out.stat().st_size // 1024} kB)")
    return out


def main():
    for c in CASES:
        if not (GEO / f"b_{c}.stl").exists():
            sys.exit(f"missing {GEO / f'b_{c}.stl'}: run wind_cfd_export.py first")
    d = domain_from_meta()
    print(f"domain (H={d['H']:.0f} m): "
          f"x [{d['xmin']}, {d['xmax']}], y [{d['ymin']}, {d['ymax']}], z [0, {d['zmax']}]  "
          f"cells {d['xCells']}x{d['yCells']}x{d['zCells']}, blockage {d['blockage_pct']}%")
    print(f"locationInMesh {d['seed']}")
    CFD.mkdir(parents=True, exist_ok=True)
    for c in CASES:
        write_case(c, d)
        pack_ronna(c)
    print("\ndone. Upload cache/wind/<case>_ronna.zip at https://ronna.tudelft.nl/openfoam/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
