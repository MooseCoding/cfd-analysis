"""Command line: geometry, mesh, solve, report."""
from .api import run, sweep, sweep_grid
from .config import resolve
from .env import ensure_openfoam
from .report import write_polar


def main(argv=None):
    cfg = resolve(argv)
    aoas = getattr(cfg, "aoas", None)
    yaws = getattr(cfg, "yaws", None)
    speeds = getattr(cfg, "speeds", None)
    grid = bool(yaws or speeds)
    if cfg.polar_only and not (aoas or grid):
        write_polar(cfg.out)
        return 0
    if not cfg.print_only:
        ensure_openfoam(argv)
    if grid:
        sweep_grid(cfg, aoas or [cfg.aoa], yaws or [cfg.yaw], speeds or [cfg.speed])
        return 0
    if aoas:
        sweep(cfg, aoas)
        return 0
    run(cfg)
    return 0