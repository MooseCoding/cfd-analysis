"""Load a KEY=value file, then let the environment and CLI flags override it."""
import argparse
import os

from .proc import die

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = PACKAGE_ROOT


def find_config_path(path):
    """Resolve a config file against the cwd, then the repository root."""
    if os.path.isabs(path):
        return path
    for base in (os.getcwd(), PACKAGE_ROOT):
        candidate = os.path.join(base, path)
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return os.path.abspath(path)

_FIELDS = {
    "PROFILE": ("profile", str),
    "AOA": ("aoa", float),
    "YAW": ("yaw", float),
    "SPEED": ("speed", float),
    "ALT_M": ("alt_m", float),
    "STL": ("stl", str),
    "SPAN_FT": ("span_ft", float),
    "UNITS": ("units", str),
    "QUALITY": ("quality", str),
    "LAYERS": ("layers", int),
    "ITERS": ("iters", int),
    "NPROCS": ("nprocs", int),
    "TURB_INT": ("turb_int", float),
    "CELLCAP": ("cellcap", float),
    "MAX_COMPUTE": ("max_compute", str),
    "COMPUTE": ("max_compute", str),
    "TARGET_YPLUS": ("target_yplus", float),
    "OUT": ("out", str),
    "REF_AREA": ("ref_area", float),
    "REF_LENGTH": ("ref_length", float),
    "REF_CHORD": ("ref_length", float),
    "REF_X": ("ref_x", float),
    "REF_XCG": ("ref_x", float),
    "REF_Y": ("ref_y", float),
    "REF_YCG": ("ref_y", float),
    "REF_Z": ("ref_z", float),
    "REF_ZCG": ("ref_z", float),
    "SOLVER": ("solver", str),
    "TARGET_SIZE_M": ("target_size_m", float),
    "WRITE_ON_EXIT": ("write_on_exit", bool),
    "REPORT_SCATTER": ("report_scatter", bool),
    "SMOKE": ("smoke", bool),
    "VOLUME": ("volume", bool),
    "RESULTS_ONLY": ("results_only", bool),
    "BODY_D": ("body_d", float),
    "BODY_L": ("body_l", float),
    "NOSE_L": ("nose_l", float),
    "NOSE": ("nose", str),
    "FIN_COUNT": ("fin_count", int),
    "FIN_ROOT": ("fin_root", float),
    "FIN_TIP": ("fin_tip", float),
    "FIN_SPAN": ("fin_span", float),
    "FIN_SWEEP": ("fin_sweep", float),
    "FIN_X": ("fin_x", float),
}


_API_OVERRIDE_ALIASES = {
    "max_iterations": "iters",
}

# Mesh cell budget and MPI ranks unless CELLCAP / NPROCS are set explicitly.
_COMPUTE_PRESETS = {
    "light": {"cellcap": 1000000.0, "nprocs": 2},
    "medium": {"cellcap": 4000000.0},
    "heavy": {"cellcap": 16000000.0},
}


class Config(object):
    """Resolved run settings. Use :func:`from_mapping` / :func:`cfd.make_config` to build one."""

    def __init__(self, values):
        self.__dict__.update(values)

    @property
    def max_iterations(self):
        """SIMPLE iteration cap (``controlDict`` ``endTime``); same as :attr:`iters`."""
        return self.iters

    @max_iterations.setter
    def max_iterations(self, value):
        self.iters = int(value)


def defaults():
    return {
        "profile": "body",
        "aoa": 4.0,
        "yaw": 0.0, 
        "speed": 20.0,
        "alt_m": 0.0,
        "stl": "",
        "span_ft": 3.0,
        "units": "",
        "quality": "",
        "layers": 0,
        "iters": 2000,
        "nprocs": None,
        "turb_int": 0.001,
        "cellcap": 4000000.0,
        "max_compute": "",
        "target_yplus": 80.0,
        "out": "",
        "ref_area": None,
        "ref_length": None,
        "ref_x": None,
        "ref_y": None,
        "ref_z": None,
        "solver": "auto",
        "target_size_m": None,
        "write_on_exit": False,
        "report_scatter": True,
        "results_only": False,
        "smoke": False,
        "volume": False,
        "remesh": False,
        "open_pv": False,
        "print_only": False,
        "aoas": None,
        "yaws": None,
        "speeds": None,
        "polar_only": False,
        "body_d": 0.1016,
        "body_l": 0.80,
        "nose_l": 0.20,
        "nose": "ogive",
        "fin_count": 4,
        "fin_root": 0.12,
        "fin_tip": 0.06,
        "fin_span": 0.10,
        "fin_sweep": 0.04,
        "fin_x": None,
        "config_path": "",
        "stl_from_config": False,
        "out_from_config": False,
    }


def _empty_override(parsed, kind):
    if kind is str:
        return parsed == ""
    if kind in (int, float):
        return parsed is None
    return False


def parse_token(raw, kind):
    raw = raw.strip().strip('"').strip("'")
    if raw == "":
        return "" if kind is str else None
    if kind is bool:
        return raw.lower() in ("1", "true", "yes", "on")
    if kind is int:
        return int(float(raw))
    if kind is float:
        return float(raw)
    return raw


def apply_pairs(values, pairs, track_explicit=False):
    explicit = values.setdefault("_explicit", set())
    for key, raw in pairs:
        spec = _FIELDS.get(key)
        if spec is None:
            die("unknown config key %s" % key)
        name, kind = spec
        parsed = parse_token(raw, kind)
        values[name] = parsed
        if track_explicit and not _empty_override(parsed, kind):
            explicit.add(name)


def read_config(path):
    pairs = []
    with open(path) as handle:
        for line in handle:
            text = line.split("#", 1)[0].strip()
            if not text or "=" not in text:
                continue
            key, raw = text.split("=", 1)
            pairs.append((key.strip(), raw.strip()))
    return pairs


def _parser():
    parser = argparse.ArgumentParser(
        prog="cfd",
        description="Steady external-flow CFD for a plane, a rocket, or any one STL.",
    )
    parser.add_argument("--config", action="append", default=None, help="KEY=value file (last one wins)")
    parser.add_argument("--print", dest="print_only", action="store_const", const=True, default=None,
                        help="print the flight condition, reference, and solver, then exit")
    parser.add_argument("-a", dest="aoa", default=None, help="angle of attack, degrees")
    parser.add_argument("-v", dest="speed", default=None, help="airspeed, m/s")
    parser.add_argument("-s", dest="stl", default=None, help="STL path")
    parser.add_argument("-b", dest="span_ft", default=None, help="built-in plane wingspan, feet")
    parser.add_argument("-u", dest="units", default=None, help="STL units: m, mm, cm, in, ft")
    parser.add_argument("-q", dest="quality", default=None, help="mesh level: coarse, medium, fine, vfine")
    parser.add_argument("-l", dest="layers", default=None, help="prism layers (0 = wall functions)")
    parser.add_argument(
        "-i", "--max-iterations", dest="iters", default=None, metavar="N",
        help="max SIMPLE iterations (controlDict endTime; same as ITERS= in config)",
    )
    parser.add_argument("-n", dest="nprocs", default=None, help="MPI processes")
    parser.add_argument(
        "--max-compute", dest="max_compute", default=None, metavar="LEVEL",
        help="compute budget: light, medium, or heavy (same as MAX_COMPUTE= in config)",
    )
    parser.add_argument("-A", dest="ref_area", default=None, help="reference area, m^2")
    parser.add_argument("-C", dest="ref_length", default=None, help="reference length, m (MAC or diameter)")
    parser.add_argument("-X", dest="ref_x", default=None, help="moment-reference x, m")
    parser.add_argument("-Z", dest="ref_z", default=None, help="moment-reference z, m")
    parser.add_argument("-m", dest="remesh", action="store_const", const=True, default=None, help="rebuild the mesh")
    parser.add_argument("-p", dest="open_pv", action="store_const", const=True, default=None, help="open ParaView")
    parser.add_argument("-w", dest="write_on_exit", action="store_const", const=True, default=None,
                        help="on Ctrl+C, write fields and post-process")
    parser.add_argument(
        "--no-scatter", dest="report_scatter", action="store_const", const=False, default=None,
        help="omit sample std dev from report.txt and results.csv (means only)",
    )
    parser.add_argument(
        "--results-only", dest="results_only", action="store_const", const=True, default=None,
        help="skip ParaView/VTK exports and delete OpenFOAM fields after the results report",
    )
    parser.add_argument(
        "--smoke", dest="smoke", action="store_const", const=True, default=None,
        help="first-success preset: coarse mesh, 80 iterations, 1 MPI rank, no layers",
    )
    parser.add_argument(
        "--volume", dest="volume", action="store_const", const=True, default=None,
        help="keep the volume VTK (internal.vtu). Default keeps the wall surface only",
    )
    parser.add_argument(
        "--aoas", default=None, metavar="LIST",
        help="comma-separated angles of attack; one mesh, one solve each, then polar.csv",
    )
    parser.add_argument("--yaw", dest="yaw", default=None, help="yaw angle, degrees (positive gives flow a +y component)")
    parser.add_argument(
        "--yaws", default=None, metavar="LIST",
        help="comma-separated yaw angles; combines with --aoas and --speeds as a grid",
    )
    parser.add_argument(
        "--speeds", default=None, metavar="LIST",
        help="comma-separated airspeeds, m/s; combines with --aoas and --yaws as a grid",
    )
    parser.add_argument(
        "--polar", dest="polar_only", action="store_const", const=True, default=None,
        help="write polar.csv and polar.svg from finished runs, then exit",
    )
    return parser


def parse_list(text, flag, what):
    """Comma-separated numbers for a sweep flag."""
    if text is None:
        die("%s needs at least one %s" % (flag, what))
    parts = [part.strip() for part in str(text).split(",")]
    if not parts or any(part == "" for part in parts):
        die("%s needs numeric values separated by commas" % flag)
    values = []
    for part in parts:
        try:
            values.append(float(part))
        except ValueError:
            die("%s has a non-numeric value: %s" % (flag, part))
    return values


def parse_aoas(text):
    """Comma-separated angles of attack, in degrees."""
    return parse_list(text, "--aoas", "angle")


def _apply_flags(values, args):
    explicit = values.setdefault("_explicit", set())
    flag_map = (
        ("aoa", float), ("yaw", float), ("speed", float), 
        ("speed", float), ("stl", str), ("span_ft", float),
        ("units", str), ("quality", str), ("layers", int), ("iters", int),
        ("nprocs", int), ("ref_area", float), ("ref_length", float),
        ("ref_x", float), ("ref_z", float), ("max_compute", str),
    )
    for name, kind in flag_map:
        raw = getattr(args, name)
        if raw is not None:
            values[name] = parse_token(raw, kind)
            explicit.add(name)
            if name == "stl":
                values["stl_from_config"] = False
    for name in (
        "remesh", "open_pv", "write_on_exit", "print_only", "report_scatter", "results_only",
        "smoke", "volume",
    ):
        raw = getattr(args, name)
        if raw is not None:
            values[name] = raw
    if getattr(args, "aoas", None) is not None:
        if args.aoa is not None:
            die("pass either -a or --aoas")
        values["aoas"] = parse_aoas(args.aoas)
    if getattr(args, "yaws", None) is not None:
        if args.yaw is not None:
            die("pass either --yaw or --yaws")
        values["yaws"] = parse_list(args.yaws, "--yaws", "angle")
    if getattr(args, "speeds", None) is not None:
        if args.speed is not None:
            die("pass either -v or --speeds")
        values["speeds"] = parse_list(args.speeds, "--speeds", "speed")
    if getattr(args, "polar_only", None) is not None:
        values["polar_only"] = True


def _normalize_compute(values):
    raw = (values.get("max_compute") or "").strip().lower()
    if raw in ("auto", ""):
        values["max_compute"] = ""
    else:
        values["max_compute"] = raw


def _apply_compute_preset(values):
    _normalize_compute(values)
    level = values["max_compute"]
    if not level:
        return
    preset = _COMPUTE_PRESETS.get(level)
    if preset is None:
        die("MAX_COMPUTE must be light, medium, heavy, or empty")
    explicit = values.get("_explicit", set())
    if "cellcap" not in explicit:
        values["cellcap"] = preset["cellcap"]
    if "nprocs" not in explicit and "nprocs" in preset:
        values["nprocs"] = preset["nprocs"]


def _validate(values):
    if values["profile"] not in ("plane", "rocket", "body"):
        die("PROFILE must be plane, rocket, or body")
    if values["solver"] not in ("auto", "simple", "rho"):
        die("SOLVER must be auto, simple, or rho")
    if values["nose"] not in ("ogive", "cone", "elliptical"):
        die("NOSE must be ogive, cone, or elliptical")
    if values["quality"] not in ("", "auto", "coarse", "medium", "fine", "vfine"):
        die("QUALITY must be coarse, medium, fine, vfine, or empty for automatic")
    if values["units"] not in ("", "auto", "m", "mm", "cm", "in", "ft"):
        die("UNITS must be m, mm, cm, in, ft, or empty for automatic")
    if values["alt_m"] < 0 or values["alt_m"] > 11000:
        die("ALT_M must be from 0 to 11000 m (ISA troposphere)")
    if values["speed"] <= 0:
        die("SPEED must be positive")
    if values["iters"] < 1 or values["layers"] < 0 or values["fin_count"] < 2:
        die("ITERS, LAYERS, and FIN_COUNT are out of range")
    if values["max_compute"] and values["max_compute"] not in _COMPUTE_PRESETS:
        die("MAX_COMPUTE must be light, medium, heavy, or empty")
    if abs(values["yaw"]) >= 90:
        die("YAW must be between -90 and 90 degrees")
    for yaw in values["yaws"] or []:
        if abs(yaw) >= 90:
            die("--yaws values must be between -90 and 90 degrees")
    for speed in values["speeds"] or []:
        if speed <= 0:
            die("--speeds values must be positive")


def _apply_smoke(values):
    """Force a short first run. Wins over MAX_COMPUTE ranks and explicit -i/-n/-q/-l."""
    if not values.get("smoke"):
        return
    values["quality"] = "coarse"
    values["iters"] = 80
    values["nprocs"] = 1
    values["layers"] = 0


def _finish_config(values):
    _apply_compute_preset(values)
    _apply_smoke(values)
    _validate(values)
    values.pop("_explicit", None)
    _finalize_paths(values)


def resolve(argv=None, environ=None):
    if environ is None:
        environ = os.environ
    args = _parser().parse_args(argv)
    values = defaults()
    paths = args.config
    if not paths:
        paths = [os.path.join(PACKAGE_ROOT, "config", "body.conf")]
    path = find_config_path(paths[-1])
    if not os.path.isfile(path):
        die("config not found: %s" % path)
    apply_pairs(values, read_config(path), track_explicit=True)
    values["config_path"] = path
    if values["stl"]:
        values["stl_from_config"] = True
    if values["out"]:
        values["out_from_config"] = True
    env_pairs = []
    for key in _FIELDS:
        if key in environ and environ[key] != "":
            env_pairs.append((key, environ[key]))
    apply_pairs(values, env_pairs, track_explicit=True)
    if environ.get("STL"):
        values["stl_from_config"] = False
    if environ.get("OUT"):
        values["out_from_config"] = False
    _apply_flags(values, args)
    _finish_config(values)
    return Config(values)


def _finalize_paths(values):
    if values["stl"]:
        if values["stl_from_config"] and not os.path.isabs(values["stl"]):
            values["stl"] = os.path.join(os.path.dirname(values["config_path"]), values["stl"])
        values["stl"] = os.path.abspath(values["stl"])
    if not values["out"]:
        folder = {"plane": "plane_cfd", "rocket": "rocket_cfd", "body": "body_cfd"}[values["profile"]]
        values["out"] = os.path.join(PACKAGE_ROOT, folder)
    else:
        out = values["out"]
        if not os.path.isabs(out):
            if values.get("out_from_config") and values.get("config_path"):
                base = os.path.dirname(values["config_path"])
            else:
                base = PACKAGE_ROOT
            out = os.path.join(base, out)
        values["out"] = os.path.abspath(out)
    if values["nprocs"] is None:
        values["nprocs"] = os.cpu_count() or 4


def _coerce_api_overrides(overrides):
    """Map public API names (e.g. ``max_iterations``) onto internal config fields."""
    out = dict(overrides)
    for alias, field in _API_OVERRIDE_ALIASES.items():
        if alias not in out:
            continue
        value = out.pop(alias)
        if field in out and out[field] != value:
            die("conflicting overrides %s and %s" % (alias, field))
        out[field] = value
    return out


def from_mapping(config_path=None, environ=None, **overrides):
    """Build a :class:`Config` from a file plus keyword overrides (no argparse).

    Override keys match :func:`defaults` (``speed``, ``aoa``, ``iters``, …).
    ``max_iterations`` is an alias for ``iters``.
    """
    if environ is None:
        environ = os.environ
    values = defaults()
    if config_path is None:
        path = os.path.join(PACKAGE_ROOT, "config", "body.conf")
    else:
        path = find_config_path(config_path)
    if not os.path.isfile(path):
        die("config not found: %s" % path)
    apply_pairs(values, read_config(path), track_explicit=True)
    values["config_path"] = path
    if values["stl"]:
        values["stl_from_config"] = True
    if values["out"]:
        values["out_from_config"] = True
    env_pairs = []
    for key in _FIELDS:
        if key in environ and environ[key] != "":
            env_pairs.append((key, environ[key]))
    apply_pairs(values, env_pairs, track_explicit=True)
    if environ.get("STL"):
        values["stl_from_config"] = False
    if environ.get("OUT"):
        values["out_from_config"] = False
    explicit = values.setdefault("_explicit", set())
    for name, raw in _coerce_api_overrides(overrides).items():
        if name not in values:
            die("unknown config field %s" % name)
        values[name] = raw
        explicit.add(name)
        if name == "stl" and raw:
            values["stl_from_config"] = False
        if name == "out" and raw:
            values["out_from_config"] = False
    _finish_config(values)
    return Config(values)
