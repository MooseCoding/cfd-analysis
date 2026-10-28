"""blockMesh + snappyHexMesh, with a cache keyed by geometry, level, and layers."""
import os
import re
import shutil
import subprocess

from .dictio import vec, write
from .proc import die, run


def mesh_ok(meshdir):
    flag = os.path.join(meshdir, ".mesh_ok")
    log = os.path.join(meshdir, "log.checkMesh")
    if not (os.path.isfile(flag) and os.path.isfile(log)):
        return False
    return "Mesh OK" in open(log, errors="replace").read()


def _layer_block(setup, layers):
    count = layers if layers > 0 else 1
    if layers > 0:
        size = (
            "relativeSizes false;\n"
            "    firstLayerThickness %s;\n"
            "    minThickness %s;" % (setup["dy1"], setup["dy1"] / 5.0)
        )
    else:
        size = "relativeSizes true;\n    finalLayerThickness 0.5;\n    minThickness 0.05;"
    return count, size


def _write_dicts(meshdir, setup, layers):
    nlay, layer_size = _layer_block(setup, layers)
    add_layers = "true" if layers > 0 else "false"
    x0, x1 = setup["x0"], setup["x1"]
    y0, y1 = setup["y0"], setup["y1"]
    z0, z1 = setup["z0"], setup["z1"]
    write(os.path.join(meshdir, "system", "blockMeshDict"), """
convertToMeters 1;
vertices
(
    (%s %s %s) (%s %s %s) (%s %s %s) (%s %s %s)
    (%s %s %s) (%s %s %s) (%s %s %s) (%s %s %s)
);
blocks ( hex (0 1 2 3 4 5 6 7) (%s %s %s) simpleGrading (1 1 1) );
edges ();
boundary
(
    farfield
    {
        type patch;
        faces ( (0 4 7 3) (1 2 6 5) (0 1 5 4) (3 7 6 2) (0 3 2 1) (4 5 6 7) );
    }
);
mergePatchPairs ();
""".strip() % (
        x0, y0, z0, x1, y0, z0, x1, y1, z0, x0, y1, z0,
        x0, y0, z1, x1, y0, z1, x1, y1, z1, x0, y1, z1,
        setup["nx"], setup["ny"], setup["nz"],
    ))
    write(os.path.join(meshdir, "system", "surfaceFeaturesDict"), """
surfaces ("body.stl");
includedAngle 150;
subsetFeatures { nonManifoldEdges no; openEdges yes; }
writeObj no;
""".strip())
    write(os.path.join(meshdir, "system", "surfaceFeatureExtractDict"), """
body.stl
{
    extractionMethod    extractFromSurface;
    includedAngle       150;
    subsetFeatures { nonManifoldEdges no; openEdges yes; }
    writeObj            no;
}
""".strip())
    write(os.path.join(meshdir, "system", "controlDict"), """
application snappyHexMesh;
startFrom startTime; startTime 0; stopAt endTime; endTime 1; deltaT 1;
writeControl timeStep; writeInterval 1; writeFormat ascii;
""".strip())
    write(os.path.join(meshdir, "system", "fvSchemes"), """
ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes { default none; }
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
""".strip())
    write(os.path.join(meshdir, "system", "fvSolution"), "solvers\n{\n}\n")
    write(os.path.join(meshdir, "system", "snappyHexMeshDict"), """
castellatedMesh true;
snap            true;
addLayers       %s;

geometry
{
    body     { type triSurfaceMesh; file "body.stl"; }
    refNear  { type searchableBox; min %s; max %s; }
    refWake  { type searchableBox; min %s; max %s; }
}

castellatedMeshControls
{
    maxLocalCells %d;
    maxGlobalCells 8000000;
    minRefinementCells 10;
    maxLoadUnbalance 0.10;
    nCellsBetweenLevels 3;
    features ( { file "body.eMesh"; level %d; } );
    refinementSurfaces
    {
        body { level (%d %d); patchInfo { type wall; } }
    }
    resolveFeatureAngle 30;
    refinementRegions
    {
        refNear { mode inside; levels ((1e15 %d)); }
        refWake { mode inside; levels ((1e15 %d)); }
    }
    locationInMesh %s;
    allowFreeStandingZoneFaces true;
}

snapControls
{
    nSmoothPatch 3;
    tolerance 2.0;
    nSolveIter 100;
    nRelaxIter 10;
    nFeatureSnapIter 10;
    implicitFeatureSnap false;
    explicitFeatureSnap true;
    multiRegionFeatureSnap false;
}

addLayersControls
{
    %s
    expansionRatio 1.2;
    layers { "body.*" { nSurfaceLayers %d; } }
    nGrow 0;
    featureAngle 130;
    nRelaxIter 5;
    nSmoothSurfaceNormals 1;
    nSmoothNormals 3;
    nSmoothThickness 10;
    maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3;
    minMedialAxisAngle 90;
    nBufferCellsNoExtrude 0;
    nLayerIter 50;
    nRelaxedIter 20;
}

meshQualityControls
{
    maxNonOrtho 65;
    maxBoundarySkewness 4;
    maxInternalSkewness 4;
    maxConcave 80;
    minVol 1e-13;
    minTetQuality 1e-15;
    minArea -1;
    minTwist 0.02;
    minDeterminant 0.001;
    minFaceWeight 0.05;
    minVolRatio 0.01;
    minTriangleTwist -1;
    nSmoothScale 4;
    errorReduction 0.75;
    relaxed { maxNonOrtho 75; }
}

mergeTolerance 1e-6;
debug 0;
""".strip() % (
        add_layers,
        vec(setup["near_min"]), vec(setup["near_max"]),
        vec(setup["wake_min"]), vec(setup["wake_max"]),
        int(setup["cellcap"]),
        int(setup["lvl"]),
        int(setup["lvl"]), int(setup["lvl"]),
        int(setup["l1"]), int(setup["l2"]),
        vec(setup["loc"]),
        layer_size,
        nlay,
    ))


def build_mesh(meshdir, stl, setup, layers, remesh):
    label = os.path.basename(meshdir)
    if not remesh and mesh_ok(meshdir):
        print("==> Re-using mesh: %s   (use -m to rebuild)" % meshdir)
        return
    print("==> Meshing  [%s, level=%s, layers=%s]" % (label, setup["lvl"], layers))
    if os.path.isdir(meshdir):
        shutil.rmtree(meshdir)
    surface = os.path.join(meshdir, "constant", "triSurface")
    os.makedirs(os.path.join(meshdir, "system"))
    os.makedirs(surface)
    shutil.copy(stl, os.path.join(surface, "body.stl"))
    _write_dicts(meshdir, setup, layers)
    run(["blockMesh"], meshdir, os.path.join(meshdir, "log.blockMesh"))
    check_log = os.path.join(meshdir, "log.surfaceCheck")
    with open(check_log, "w") as handle:
        subprocess.run(
            ["surfaceCheck", "constant/triSurface/body.stl"],
            cwd=meshdir, stdout=handle, stderr=subprocess.STDOUT,
        )
    if shutil.which("surfaceFeatures"):
        run(["surfaceFeatures"], meshdir, os.path.join(meshdir, "log.surfaceFeatures"))
    else:
        run(["surfaceFeatureExtract"], meshdir, os.path.join(meshdir, "log.surfaceFeatures"))
    run(["snappyHexMesh", "-overwrite"], meshdir, os.path.join(meshdir, "log.snappyHexMesh"))
    log = os.path.join(meshdir, "log.checkMesh")
    with open(log, "w") as handle:
        subprocess.run(["checkMesh"], cwd=meshdir, stdout=handle, stderr=subprocess.STDOUT)
    text = open(log, errors="replace").read()
    for line in text.splitlines():
        if re.search(r"cells:|Mesh OK|Failed", line):
            print("  " + line.strip())
    if "Mesh OK" not in text:
        die("checkMesh did not report Mesh OK - see %s" % log)
    open(os.path.join(meshdir, ".mesh_ok"), "w").close()
