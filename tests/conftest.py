"""Shared fixtures for the Ibex SoC integration tests.

These tests bolt our generated CLINT + PLIC onto a real RISC-V core
(lowRISC Ibex) and exercise the interrupt path end-to-end. Two external
dependencies are required:

  * `riscv64-elf-gcc` (homebrew formula) — RISC-V cross-compiler, used
    by the Phase-6.2 ISR tests. Not needed for the Phase-6.1 lint test.
  * An Ibex checkout at `$IBEX_ROOT` (default: `~/github/ibex`). Tests
    that need it `pytest.skip` when it's missing.

The `ibex_soc_filelist` fixture assembles, at session scope, a
`verilator`-ready command-file that combines:

  1. The Ibex file tree (pulled in via `fusesoc --setup`, which resolves
     the `lowrisc:ibex:ibex_top_tracing` + `lowrisc:ibex:sim_shared` dep
     trees and writes a `.vc` into a build directory). We strip the
     `--top-module`/`--exe` lines since our top is `ibex_mini_soc`.
  2. Our hand-written SoC glue (`ibex_mini_soc.sv`, `obi_to_axi_lite.sv`).
  3. Our generated CLINT + PLIC `.sv` files (`arch build` on the RDL
     fixtures in `tests/rdl/`).

Everything lands under a single temp build dir that's session-lived.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pytest

TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
SOC_DIR = REPO_ROOT / "soc"
ARCH_BUILD_DIR = REPO_ROOT / "build"


def _find_rdl2arch_riscv_root() -> Path:
    env = os.environ.get("RDL2ARCH_RISCV_ROOT")
    if env:
        return Path(env).expanduser()
    # default sibling layout: github/arch-ibex + github/rdl2arch-riscv
    return REPO_ROOT.parent / "rdl2arch-riscv"


RDL_DIR = _find_rdl2arch_riscv_root() / "tests" / "rdl"


def _find_arch_binary() -> Optional[str]:
    """Locate the `arch` compiler binary. Honors $ARCH_BIN override; otherwise
    walks the standard sibling-checkout fallbacks (any worktree under
    github/arch-com* with a built target/{debug,release}/arch). Skips
    macOS's `/usr/bin/arch` (a system tool, unrelated)."""
    env = os.environ.get("ARCH_BIN")
    if env and Path(env).is_file():
        return env
    candidates = [
        REPO_ROOT.parent / "arch-com" / "target" / "release" / "arch",
        REPO_ROOT.parent / "arch-com" / "target" / "debug" / "arch",
    ]
    # Allow any sibling worktree (e.g. arch-com-unpacked-ports) to provide
    # the binary while the feature is still local.
    for sibling in REPO_ROOT.parent.glob("arch-com*"):
        for sub in ("target/release/arch", "target/debug/arch"):
            candidates.append(sibling / sub)
    for c in candidates:
        if c.is_file():
            return str(c)
    which = shutil.which("arch")
    if which and "arch-com" not in which and which != "/usr/bin/arch":
        return which
    return None


@pytest.fixture(scope="session")
def arch_bin() -> str:
    path = _find_arch_binary()
    if path is None:
        pytest.skip("ARCH compiler not found (set ARCH_BIN=/path/to/arch)")
    return path


def _find_ibex_root() -> Optional[Path]:
    env = os.environ.get("IBEX_ROOT")
    if env:
        p = Path(env).expanduser()
        return p if p.is_dir() else None
    default = Path.home() / "github" / "ibex"
    return default if default.is_dir() else None


@pytest.fixture(scope="session")
def ibex_root() -> Path:
    p = _find_ibex_root()
    if p is None:
        pytest.skip(
            "Ibex checkout not found. Clone lowRISC/ibex to ~/github/ibex "
            "or set IBEX_ROOT=/path/to/ibex."
        )
    return p


def _require(tool: str) -> None:
    if shutil.which(tool) is None:
        pytest.skip(f"required tool `{tool}` not on PATH")


@pytest.fixture(scope="session")
def fusesoc_bin() -> str:
    _require("fusesoc")
    return "fusesoc"


@pytest.fixture(scope="session")
def verilator_bin() -> str:
    _require("verilator")
    return "verilator"


def _generate_clint_plic_sv(arch_bin: str, out_dir: Path) -> list[Path]:
    """Run the existing arch-com pipeline to produce CLINT + PLIC +
    mscratch CsrFile `.sv`.

    Uses the same RDL fixtures (`clint_basic`, `plic_multictx`,
    `mtrap_ibex`) that the unit / sim tests consume, so the SoC-
    level test exercises the exact same emitted HDL. The mtrap fixture
    is Phase-6.5a's first swap-in target: its generated CsrFile is
    instantiated inside the forked `ibex_cs_registers_hybrid.sv` to
    back Ibex's mscratch storage. Returns the list of generated .sv
    files.
    """
    from systemrdl import RDLCompiler
    from rdl2arch_riscv import RiscvClintExporter, RiscvCsrExporter, RiscvPlicExporter
    from rdl2arch_riscv.udps import ALL_UDPS

    out_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    # plic_multictx (2 M-mode contexts) is a strict superset of
    # plic_basic — single-context tests only ever touch ctx 0, whose
    # behaviour is identical. Using multictx everywhere lets the
    # Phase-6.4 multictx_isr test share the SoC build with the
    # Phase-6.2 / 6.3 ones.
    #
    # mtrap_ibex is the progressive M-trap CSR fixture that grows
    # across Phase-6.5 sub-phases (mscratch, mtvec, …). Its generated
    # CsrFile is instanced inside `ibex_cs_registers_hybrid.sv` to
    # back whichever CSRs we've migrated.
    for rdl_name, exporter_cls in (
        ("clint_basic",    RiscvClintExporter),
        ("plic_multictx",  RiscvPlicExporter),
        ("mtrap_ibex",     RiscvCsrExporter),
    ):
        stage = out_dir / rdl_name
        stage.mkdir(exist_ok=True)
        rdlc = RDLCompiler()
        for udp in ALL_UDPS:
            rdlc.register_udp(udp, soft=False)
        rdlc.compile_file(str(RDL_DIR / f"{rdl_name}.rdl"))
        exporter_cls().export(rdlc.elaborate().top, str(stage))

        archs = sorted(stage.glob("*.arch"))
        # `arch build` writes the generated .sv next to the .arch inputs;
        # no `-o` knob needed.
        result = subprocess.run(
            [arch_bin, "build", *[str(p) for p in archs]],
            capture_output=True, text=True,
            cwd=str(stage),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"arch build failed for {rdl_name}:\n{result.stderr}"
            )
        # Verilator needs the package files before any module that
        # imports them. `Pkg.sv` goes first, then everything else in
        # alphabetical order.
        all_sv = sorted(stage.glob("*.sv"))
        pkgs   = [p for p in all_sv if p.name.endswith("Pkg.sv")]
        nonpkg = [p for p in all_sv if not p.name.endswith("Pkg.sv")]
        generated.extend(pkgs + nonpkg)

    return generated


def _fusesoc_setup(ibex_root: Path, build_root: Path, fusesoc_bin: str) -> Path:
    """Run `fusesoc --setup` to resolve Ibex's dep tree and write a
    Verilator `.vc` file. Returns the path to the .vc."""
    build_root.mkdir(parents=True, exist_ok=True)

    # We resolve two roots — ibex_top_tracing (the core + tracer) and
    # sim_shared (ram_2p, simulator_ctrl, etc). sim_shared isn't a
    # top-level target so we stage it as a dependency of a tiny wrapper
    # core that we don't actually run; instead, we let fusesoc emit the
    # ibex_top_tracing lint tree and manually append the shared-SV files
    # we need.
    result = subprocess.run(
        [fusesoc_bin, f"--cores-root={ibex_root}",
         "run", "--target=lint", "--setup",
         "lowrisc:ibex:ibex_top_tracing"],
        cwd=str(build_root),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"fusesoc setup failed:\n{result.stderr}\n{result.stdout}"
        )

    # The VC file path depends on the resolved version string. Glob for it.
    vc_candidates = list(
        (build_root / "build").glob("*/lint-verilator/*.vc")
    )
    if not vc_candidates:
        raise RuntimeError(
            f"no .vc produced under {build_root}/build/*/lint-verilator/"
        )
    return vc_candidates[0]


# Source-file basenames that appear in fusesoc's .vc but must NOT be
# passed to Verilator, because we compile a patched copy of the file
# in-tree under tests/cpu/soc/ instead. Keeping both would be a
# duplicate-module-definition error.
_SV_SHADOWED_BY_FORKS = {
    # Phase 6.5 (rdl2arch-riscv): patched to route mscratch through the
    # generated CsrFile (`soc/ibex_cs_registers_hybrid.sv`).
    "ibex_cs_registers.sv",
}


def _arch_swap_sv() -> list[Path]:
    """Every `*.sv` under `build/` is an ARCH-emitted swap that replaces
    an upstream Ibex module of the same basename. Returned files are
    appended to `extra_sv`, and their basenames are added on the fly
    to `_SV_SHADOWED_BY_FORKS` so the upstream copy is filtered out of
    the fusesoc-resolved filelist (`_strip_top_and_exe` uses that set).
    """
    if not ARCH_BUILD_DIR.is_dir():
        return []
    return sorted(p for p in ARCH_BUILD_DIR.glob("*.sv"))


def _strip_top_and_exe(vc_path: Path) -> str:
    """Return the .vc contents with the fusesoc-tagged top-module /
    parameter / exe lines removed, plus any upstream SV file we're
    replacing with an in-tree fork.

    We set our own top (`ibex_mini_soc`) and its parameter surface is
    a strict subset of `ibex_top_tracing`, so the fusesoc-supplied
    `-GRV32E=0` etc. would error out with "parameters from the
    command line were not found in the design". Keep the `-D` macro
    defines — those configure ibex_pkg itself and our top needs them
    too."""
    out = []
    for line in vc_path.read_text().splitlines():
        s = line.strip()
        if (
            s.startswith("--top-module")
            or s == "--exe"
            or s.startswith("-G")      # top-level parameters, now stale
        ):
            continue
        # Drop upstream SV files we've forked in-tree.
        if Path(s).name in _SV_SHADOWED_BY_FORKS:
            continue
        out.append(line)
    return "\n".join(out) + "\n"


@pytest.fixture(scope="session")
def ibex_soc_filelist(
    arch_bin: str,
    ibex_root: Path,
    fusesoc_bin: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    """Build the full Verilator filelist for the SoC and return a dict:

        {
          "vc_path":   Path,      # fusesoc-generated .vc (stripped)
          "extra_sv":  list[Path], # our SV + generated CLINT/PLIC .sv
          "extra_v":   list[Path], # Ibex's shared/rtl files we pull in manually
          "build_dir": Path,      # where the .vc lives (Verilator cwd)
        }
    """
    build_root = tmp_path_factory.mktemp("ibex_soc_build")

    # 0. Discover ARCH-emitted swaps under `build/` and shadow their
    #    upstream Ibex counterparts so the fusesoc-resolved .vc skips them.
    arch_swaps = _arch_swap_sv()
    for p in arch_swaps:
        _SV_SHADOWED_BY_FORKS.add(p.name)

    # 1. Generate CLINT + PLIC .sv.
    generated_dir = build_root / "generated"
    gen_sv = _generate_clint_plic_sv(arch_bin, generated_dir)

    # 2. Resolve Ibex deps via fusesoc.
    vc_path = _fusesoc_setup(ibex_root, build_root, fusesoc_bin)
    stripped = _strip_top_and_exe(vc_path)
    stripped_vc = vc_path.with_suffix(".stripped.vc")
    stripped_vc.write_text(stripped)

    # 3. Our hand-written SoC glue + in-tree forks of upstream Ibex
    #    modules. `ibex_cs_registers_hybrid.sv` keeps upstream's
    #    module name (`ibex_cs_registers`) so the instance inside
    #    `ibex_core.sv` binds to it without ripple.
    soc_sv = [
        SOC_DIR / "obi_to_axi_lite.sv",
        SOC_DIR / "ibex_mini_soc.sv",
        SOC_DIR / "ibex_cs_registers_hybrid.sv",
    ]

    # 4. Shared Ibex sim helpers that sim_shared ships (ram_2p, simulator_ctrl).
    #    We avoid its `bus.sv` / `timer.sv` — we roll our own bus in the top
    #    and our generated CLINT replaces the timer.
    shared_sv = [
        ibex_root / "shared" / "rtl" / "ram_2p.sv",
        ibex_root / "shared" / "rtl" / "sim" / "simulator_ctrl.sv",
    ]
    # Sanity check — catch a move by lowRISC early.
    for p in shared_sv:
        if not p.is_file():
            pytest.skip(f"Ibex shared SV missing at {p} — repo layout changed?")

    return {
        "vc_path":   stripped_vc,
        "extra_sv":  gen_sv + soc_sv + shared_sv + arch_swaps,
        "build_dir": stripped_vc.parent,
    }
