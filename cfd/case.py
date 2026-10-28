"""0/, constant/, and system/ for simpleFoam or rhoSimpleFoam."""
import os
import re
import shutil

from .dictio import vec, write

WALL = '"body.*"'

RESULTS_ARTIFACTS = frozenset((
    "report.txt", "results.csv", "summary.json", "case_meta.env", "spanwise_cl.csv", "axial_load.csv",
    "history.csv", "history.svg",
))


def prune_for_results_only(rundir):
    """Remove mesh, fields, VTK, and postProcessing; keep report and CSV artifacts."""
    for name in os.listdir(rundir):
        if name in RESULTS_ARTIFACTS or name.startswith("log."):
            continue
        path = os.path.join(rundir, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.isfile(path):
            os.remove(path)


THERMO = """
thermoType
{
    type            hePsiThermo;
    mixture         pureMixture;
    transport       sutherland;
    thermo          hConst;
    equationOfState perfectGas;
    specie          specie;
    energy          sensibleEnthalpy;
}
mixture
{
    specie { molWeight 28.96; }
    thermodynamics { Cp 1004.5; Hf 0; }
    transport { As 1.458e-06; Ts 110.4; }
}
""".strip()

TURBULENCE = """
simulationType RAS;
RAS { model kOmegaSST; RASModel kOmegaSST; turbulence on; printCoeffs on; }
""".strip()


def read_patches(boundary_path):
    names = []
    if not os.path.isfile(boundary_path):
        return names
    for line in open(boundary_path, errors="replace"):
        token = line.strip()
        if re.match(r"body[A-Za-z0-9_]*$", token):
            names.append(token)
    return names


def write_schemes(rundir, turbdiv, compressible):
    if compressible:
        extra = (
            "    div(phi,h)      %s;\n"
            "    div(phi,e)      %s;\n"
            "    div(phi,K)      %s;" % (turbdiv, turbdiv, turbdiv)
        )
        viscous = "div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear;"
    else:
        extra = ""
        viscous = "div((nuEff*dev2(T(grad(U))))) Gauss linear;"
    write(os.path.join(rundir, "system", "fvSchemes"), """
ddtSchemes      { default steadyState; }
gradSchemes     { default Gauss linear; grad(U) cellLimited Gauss linear 1; }
divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    div(phi,k)      %s;
    div(phi,omega)  %s;
%s
    %s
}
laplacianSchemes { default Gauss linear limited corrected 0.5; }
interpolationSchemes { default linear; }
snGradSchemes   { default limited corrected 0.5; }
wallDist        { method meshWave; }
""".strip() % (turbdiv, turbdiv, extra, viscous))


def write_fvsolution(rundir, compressible, transonic):
    if compressible:
        body = """
solvers
{
    p { solver GAMG; smoother GaussSeidel; tolerance 1e-8; relTol 0.01; }
    "(U|h|e|k|omega)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0.1; }
}
SIMPLE
{
    nNonOrthogonalCorrectors 1;
    transonic       %s;
    consistent      yes;
    residualControl { p 1e-5; U 1e-6; "(h|e|k|omega)" 1e-6; }
}
relaxationFactors
{
    fields { p 0.3; rho 0.01; }
    equations { U 0.7; h 0.7; e 0.7; "(k|omega)" 0.7; }
}
""".strip() % ("yes" if transonic else "no")
    else:
        body = """
solvers
{
    p { solver GAMG; smoother GaussSeidel; tolerance 1e-8; relTol 0.01; }
    "(U|k|omega)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0.01; }
}
SIMPLE
{
    nNonOrthogonalCorrectors 1;
    consistent yes;
    residualControl { p 1e-5; U 1e-6; "(k|omega)" 1e-6; }
}
relaxationFactors
{
    equations { U 0.9; ".*" 0.9; }
}
""".strip()
    write(os.path.join(rundir, "system", "fvSolution"), body)


def _field(path, class_, dims, internal, boundaries):
    write(path, "dimensions %s;\ninternalField uniform %s;\nboundaryField\n{\n%s\n}\n" % (
        dims, internal, boundaries.rstrip(),
    ), class_)


def _freestream_scalar(value, wall):
    return (
        "    farfield { type freestream; freestreamValue uniform %s; value uniform %s; }\n"
        "    %s { %s }" % (value, value, WALL, wall)
    )


def _force_coeffs(name, patches, rho, lift, drag, centre, speed, length, area):
    return """
    %s
    {
        type            forceCoeffs;
        libs            ("libforces.so");
        log             false;
        writeControl    timeStep;
        writeInterval   1;
        patches         %s;
        rho             rhoInf;
        rhoInf          %.8g;
        liftDir         %s;
        dragDir         %s;
        CofR            %s;
        pitchAxis       (0 1 0);
        magUInf         %.8g;
        lRef            %.8g;
        Aref            %.8g;
    }""" % (name, patches, rho, vec(lift), vec(drag), vec(centre), speed, length, area)


def _forces(name, patches, rho, centre):
    return """
    %s
    {
        type            forces;
        libs            ("libforces.so");
        log             false;
        writeControl    timeStep;
        writeInterval   1;
        patches         %s;
        rho             rhoInf;
        rhoInf          %.8g;
        CofR            %s;
    }""" % (name, patches, rho, vec(centre))


def _bins(name, patches, centre, direction):
    return """
    %s
    {
        type            binField;
        libs            ("libfieldFunctionObjects.so");
        log             false;
        writeControl    timeStep;
        writeInterval   1;
        binModel        singleDirectionUniformBin;
        fields          (force);
        patches         %s;
        CofR            %s;
        binData
        {
            nBin        40;
            direction   %s;
            cumulative  no;
        }
    }""" % (name, patches, vec(centre), direction)


def _cp(q_value, p_inf, compressible):
    if compressible:
        formula = (
            '            const dimensionedScalar q("q", p.dimensions(), %.8g);\n'
            '            const dimensionedScalar pInf("pInf", p.dimensions(), %.8g);\n'
            "            *CpPtr = (p - pInf)/q;" % (q_value, p_inf)
        )
    else:
        formula = (
            '            const dimensionedScalar q("q", p.dimensions(), %.8g);\n'
            "            *CpPtr = p/q;" % q_value
        )
    return """
    codedCp
    {
        type            coded;
        libs            ("libutilityFunctionObjects.so");
        name            CpField;
        writeControl    writeTime;
        codeExecute
        #{
            auto* CpPtr = mesh().getObjectPtr<volScalarField>("Cp");
            if (!CpPtr)
            {
                CpPtr = new volScalarField
                (
                    IOobject
                    (
                        "Cp",
                        mesh().time().timeName(),
                        mesh(),
                        IOobject::NO_READ,
                        IOobject::AUTO_WRITE,
                        IOobject::REGISTER
                    ),
                    mesh(),
                    dimensionedScalar(dimless, Zero)
                );
                regIOobject::store(CpPtr);
            }
            const auto& p = mesh().lookupObject<volScalarField>("p");
%s
        #};
    }""" % formula


def write_case(rundir, meshdir, cfg, setup, flow, atm, solver, transonic, nprocs):
    compressible = solver == "rho"
    application = "rhoSimpleFoam" if compressible else "simpleFoam"
    print("==> Case %s" % rundir)
    if os.path.isdir(rundir):
        shutil.rmtree(rundir)
    os.makedirs(os.path.join(rundir, "0"))
    os.makedirs(os.path.join(rundir, "system"))
    os.makedirs(os.path.join(rundir, "constant"))
    shutil.copytree(
        os.path.join(meshdir, "constant", "polyMesh"),
        os.path.join(rundir, "constant", "polyMesh"),
    )
    if not cfg.results_only:
        open(os.path.join(rundir, "case.foam"), "w").close()

    if compressible:
        write(os.path.join(rundir, "constant", "physicalProperties"), THERMO)
        write(os.path.join(rundir, "constant", "thermophysicalProperties"), THERMO)
    else:
        transport = "transportModel Newtonian;\nnu [0 2 -1 0 0 0 0] %.8g;\n" % atm["nu"]
        write(os.path.join(rundir, "constant", "transportProperties"), transport)
        write(os.path.join(rundir, "constant", "physicalProperties"), transport)
    write(os.path.join(rundir, "constant", "turbulenceProperties"), TURBULENCE)
    write(os.path.join(rundir, "constant", "momentumTransport"), TURBULENCE)

    velocity = "(%.8g %.8g %.8g)" % (flow["ux"], flow.get("uy", 0.0), flow["uz"])    
    _field(
        os.path.join(rundir, "0", "U"), "volVectorField", "[0 1 -1 0 0 0 0]", velocity,
        "    farfield { type freestreamVelocity; freestreamValue uniform %s; value uniform %s; }\n"
        "    %s { type noSlip; }" % (velocity, velocity, WALL),
    )
    if compressible:
        pressure = "%.8g" % atm["p"]
        _field(
            os.path.join(rundir, "0", "p"), "volScalarField", "[1 -1 -2 0 0 0 0]", pressure,
            "    farfield { type freestreamPressure; freestreamValue uniform %s; value uniform %s; }\n"
            "    %s { type zeroGradient; }" % (pressure, pressure, WALL),
        )
        temperature = "%.8g" % atm["T"]
        _field(
            os.path.join(rundir, "0", "T"), "volScalarField", "[0 0 0 1 0 0 0]", temperature,
            _freestream_scalar(temperature, "type zeroGradient;"),
        )
        _field(
            os.path.join(rundir, "0", "alphat"), "volScalarField", "[1 -1 -1 0 0 0 0]", "0",
            "    farfield { type calculated; value uniform 0; }\n"
            "    %s { type compressible::alphatWallFunction; Prt 0.85; value uniform 0; }" % WALL,
        )
    else:
        _field(
            os.path.join(rundir, "0", "p"), "volScalarField", "[0 2 -2 0 0 0 0]", "0",
            "    farfield { type freestreamPressure; freestreamValue uniform 0; value uniform 0; }\n"
            "    %s { type zeroGradient; }" % WALL,
        )
    k_value = "%.8g" % flow["k"]
    w_value = "%.8g" % flow["omega"]
    nut_value = "%.8g" % flow["nut"]
    _field(os.path.join(rundir, "0", "k"), "volScalarField", "[0 2 -2 0 0 0 0]", k_value,
           _freestream_scalar(k_value, "type kqRWallFunction; value uniform %s;" % k_value))
    _field(os.path.join(rundir, "0", "omega"), "volScalarField", "[0 0 -1 0 0 0 0]", w_value,
           _freestream_scalar(w_value, "type omegaWallFunction; value uniform %s;" % w_value))
    _field(os.path.join(rundir, "0", "nut"), "volScalarField", "[0 2 -1 0 0 0 0]", nut_value,
           _freestream_scalar(nut_value, "type nutUSpaldingWallFunction; value uniform 0;"))

    names = read_patches(os.path.join(rundir, "constant", "polyMesh", "boundary"))
    centre = (setup["ref_x"], setup["ref_y"], setup["ref_z"])
    all_patches = "(%s)" % WALL
    wing = None
    for name in names:
        if "wing" in name:
            wing = name
            break
    functions = [
        _force_coeffs(
            "forceCoeffs1", all_patches, atm["rho"], flow["lift"], flow["drag"],
            centre, cfg.speed, setup["ref_chord"], setup["ref_area"],
        ),
        _forces("forces1", all_patches, atm["rho"], centre),
    ]
    for name in names:
        functions.append(_force_coeffs(
            "coeff_%s" % name, "(%s)" % name, atm["rho"], flow["lift"], flow["drag"],
            centre, cfg.speed, setup["ref_chord"], setup["ref_area"],
        ))
    if cfg.profile == "plane":
        span_patches = "(%s)" % wing if wing else all_patches
        functions.append(_forces("spanForces", span_patches, atm["rho"], centre))
        functions.append(_bins("spanLoad", span_patches, centre, "(0 1 0)"))
    elif cfg.profile == "rocket":
        functions.append(_forces("axialForces", all_patches, atm["rho"], centre))
        functions.append(_bins("axialLoad", all_patches, centre, "(1 0 0)"))
    if not cfg.results_only:
        q_cp = 0.5 * cfg.speed ** 2 if not compressible else 0.5 * atm["rho"] * cfg.speed ** 2
        functions.append(_cp(q_cp, atm["p"], compressible))
    functions.append("""
    yPlus1
    {
        type            yPlus;
        libs            ("libfieldFunctionObjects.so");
        log             false;
        writeControl    writeTime;
    }""")
    if not cfg.results_only:
        functions.append("""
    wallShear1
    {
        type            wallShearStress;
        libs            ("libfieldFunctionObjects.so");
        log             false;
        writeControl    writeTime;
        patches         (%s);
    }""" % WALL)
    iters = int(cfg.iters)
    if cfg.results_only:
        write_interval = max(1, iters)
        purge_write = 1
    else:
        write_interval = 250
        purge_write = 2
    write(os.path.join(rundir, "system", "controlDict"), """
application     %s;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         %d;
deltaT          1;
writeControl    timeStep;
writeInterval   %d;
purgeWrite      %d;
writeFormat     binary;
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;

functions
{%s
}
""".strip() % (application, iters, write_interval, purge_write, "\n".join(functions)))
    write_schemes(rundir, "bounded Gauss limitedLinear 1", compressible)
    write_fvsolution(rundir, compressible, transonic)
    write(os.path.join(rundir, "system", "decomposeParDict"), """
numberOfSubdomains %d;
method scotch;
""".strip() % int(nprocs))
    return names
