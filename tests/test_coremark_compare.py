"""CoreMark comparison: ARCH-swap Ibex versus upstream-reference Ibex.

This is intentionally not part of ``test_cpu_programs.py``. CoreMark is
larger and slower than the bring-up programs, and it needs two simulator
builds so the same binary can be measured against both implementations.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
BIN2VMEM = TESTS_DIR / "sw" / "bin2vmem.py"
COREMARK_TB = TESTS_DIR / "cpp" / "ibex_mini_soc_coremark_tb.cpp"

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_COREMARK_COMPARE") != "1",
    reason="CoreMark comparison is an opt-in long-running benchmark",
)


@dataclass(frozen=True)
class CoremarkMetrics:
    total_ticks: int
    iterations: int
    coremark_per_mhz: float
    validated: bool
    log: str


def _parse_vc(vc_path: Path) -> tuple[list[str], list[str], list[str], list[str]]:
    incdirs: list[str] = []
    sv_files: list[str] = []
    vlt_files: list[str] = []
    defines: list[str] = []
    for raw in vc_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        if line.startswith("+incdir+"):
            incdirs.append(line[len("+incdir+"):])
            continue
        if line.startswith("-D"):
            body = line[2:]
            name = body.split("=", 1)[0]
            if name == "SYNTHESIS":
                continue
            defines.append(line)
            continue
        if line.startswith("-"):
            continue
        if line.endswith(".vlt"):
            vlt_files.append(line)
        elif line.endswith((".sv", ".svh", ".v")):
            sv_files.append(line)
    return incdirs, sv_files, vlt_files, defines


def _build_model(filelist: dict, sim_build: Path) -> Path:
    vc_path: Path = filelist["vc_path"]
    build_dir: Path = filelist["build_dir"]
    extra_sv: list[Path] = filelist["extra_sv"]

    incdirs, sv_files, vlt_files, defines = _parse_vc(vc_path)

    def _abs(p: str) -> str:
        pp = Path(p)
        if not pp.is_absolute():
            pp = build_dir / pp
        return str(pp.resolve())

    sources = (
        [_abs(p) for p in vlt_files]
        + [_abs(p) for p in sv_files]
        + [str(p) for p in extra_sv]
    )
    sim_build.mkdir(parents=True, exist_ok=True)
    cmd = [
        "verilator",
        "--cc",
        "--exe",
        "--build",
        "--top-module",
        "ibex_mini_soc",
        "-Mdir",
        str(sim_build),
        *[f"+incdir+{_abs(p)}" for p in incdirs],
        *sources,
        str(COREMARK_TB),
        "--unroll-count", "72",
        "--public-flat-rw",
        "--trace",
        "-CFLAGS", "-O3",
        "-LDFLAGS", "-O3",
        "-Wno-IMPORTSTAR",
        "-Wno-UNUSEDSIGNAL",
        "-Wno-UNUSEDPARAM",
        "-Wno-PINMISSING",
        "-Wno-WIDTHEXPAND",
        "-Wno-fatal",
        *defines,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "Verilator CoreMark model build failed:\n"
            f"STDERR:\n{result.stderr[-8000:]}\nSTDOUT:\n{result.stdout[-8000:]}"
        )
    exe = sim_build / "Vibex_mini_soc"
    if not exe.is_file():
        raise RuntimeError(f"expected Verilator executable at {exe}")
    return exe


def _dut_filelist(arch_bin: str, ibex_root: Path, fusesoc_bin: str, tmp_path: Path) -> dict:
    from tests import conftest as shared

    env = os.environ.copy()
    env["ARCH_BIN"] = arch_bin
    result = subprocess.run(
        ["make", "build"],
        cwd=shared.REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"make build failed before CoreMark DUT filelist:\n"
            f"STDERR:\n{result.stderr[-4000:]}\nSTDOUT:\n{result.stdout[-4000:]}"
        )

    build_root = tmp_path / "dut_filelist"
    build_root.mkdir(parents=True, exist_ok=True)

    arch_swaps = shared._arch_swap_sv()
    for p in arch_swaps:
        shared._SV_SHADOWED_BY_FORKS.add(p.name)

    generated_dir = build_root / "generated"
    gen_sv = shared._generate_clint_plic_sv(arch_bin, generated_dir)
    vc_path = shared._fusesoc_setup(ibex_root, build_root, fusesoc_bin)
    stripped_vc = vc_path.with_suffix(".stripped.vc")
    stripped_vc.write_text(shared._strip_top_and_exe(vc_path))

    soc_sv = [
        shared.SOC_DIR / "obi_to_axi_lite.sv",
        shared.SOC_DIR / "ibex_mini_soc.sv",
        shared.SOC_DIR / "ibex_cs_registers_hybrid.sv",
    ]
    shared_sv = [
        ibex_root / "shared" / "rtl" / "ram_2p.sv",
        ibex_root / "shared" / "rtl" / "sim" / "simulator_ctrl.sv",
    ]
    for p in shared_sv:
        if not p.is_file():
            pytest.skip(f"Ibex shared SV missing at {p}")

    return {
        "vc_path": stripped_vc,
        "extra_sv": gen_sv + soc_sv + shared_sv + arch_swaps,
        "build_dir": stripped_vc.parent,
    }


def _ref_filelist(arch_bin: str, ibex_root: Path, fusesoc_bin: str, tmp_path: Path) -> dict:
    from tests import conftest as shared

    build_root = tmp_path / "ref_filelist"
    build_root.mkdir(parents=True, exist_ok=True)

    generated_dir = build_root / "generated"
    gen_sv = shared._generate_clint_plic_sv(arch_bin, generated_dir)
    vc_path = shared._fusesoc_setup(ibex_root, build_root, fusesoc_bin)

    out = []
    for line in vc_path.read_text().splitlines():
        s = line.strip()
        if (
            s.startswith("--top-module")
            or s == "--exe"
            or s.startswith("-G")
            or Path(s).name == "ibex_cs_registers.sv"
        ):
            continue
        out.append(line)
    stripped_vc = vc_path.with_suffix(".ref.vc")
    stripped_vc.write_text("\n".join(out) + "\n")

    soc_sv = [
        shared.SOC_DIR / "obi_to_axi_lite.sv",
        shared.SOC_DIR / "ibex_mini_soc.sv",
        shared.SOC_DIR / "ibex_cs_registers_hybrid.sv",
    ]
    shared_sv = [
        ibex_root / "shared" / "rtl" / "ram_2p.sv",
        ibex_root / "shared" / "rtl" / "sim" / "simulator_ctrl.sv",
    ]
    for p in shared_sv:
        if not p.is_file():
            pytest.skip(f"Ibex shared SV missing at {p}")

    return {
        "vc_path": stripped_vc,
        "extra_sv": gen_sv + soc_sv + shared_sv,
        "build_dir": stripped_vc.parent,
    }


@pytest.fixture(scope="session")
def built_coremark(ibex_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    gcc = shutil.which("riscv64-elf-gcc")
    objcopy = shutil.which("riscv64-elf-objcopy")
    objdump = shutil.which("riscv64-elf-objdump")
    if gcc is None or objcopy is None or objdump is None:
        pytest.skip("riscv64-elf toolchain is required for CoreMark")

    coremark_dir = ibex_root / "vendor" / "eembc_coremark"
    port_dir = ibex_root / "examples" / "sw" / "benchmarks" / "coremark" / "ibex"
    simple_dir = ibex_root / "examples" / "sw" / "simple_system" / "common"
    if not coremark_dir.is_dir():
        pytest.skip(f"CoreMark source not found at {coremark_dir}")

    build = tmp_path_factory.mktemp("coremark_build")
    elf = build / "coremark.elf"
    bin_path = build / "coremark.bin"
    vmem = build / "coremark.vmem"
    iterations = int(os.environ.get("COREMARK_ITERATIONS", "1"))
    total_data_size = int(os.environ.get("COREMARK_TOTAL_DATA_SIZE", "1200"))
    exec_mask = int(os.environ.get("COREMARK_EXEC_MASK", "7"), 0)
    default_run = "PROFILE_RUN" if total_data_size == 1200 else "VALIDATION_RUN"
    run_macro = os.environ.get("COREMARK_RUN", default_run)
    compat_inc = build / "compat"
    (compat_inc / "sys").mkdir(parents=True, exist_ok=True)
    # The Homebrew riscv64-elf toolchain used by the existing cpu tests is
    # freestanding and does not ship newlib's sys/types.h. Ibex's CoreMark
    # port only needs size_t from that header.
    (compat_inc / "sys" / "types.h").write_text(
        "#ifndef ARCH_IBEX_COREMARK_SYS_TYPES_H\n"
        "#define ARCH_IBEX_COREMARK_SYS_TYPES_H\n"
        "typedef unsigned int size_t;\n"
        "#endif\n"
    )
    patched_portme = build / "core_portme.c"
    patched_portme.write_text(
        (port_dir / "core_portme.c").read_text().replace(
            "volatile ee_s32 seed5_volatile = 0;",
            "volatile ee_s32 seed5_volatile = COREMARK_EXEC_MASK;",
        )
    )
    patched_main = build / "core_main.c"
    patched_main.write_text(
        (coremark_dir / "core_main.c").read_text().replace(
            "results[0].execs=get_seed_32(5);",
            "results[0].execs=COREMARK_EXEC_MASK;",
        )
    )

    sources = [
        patched_main,
        coremark_dir / "core_list_join.c",
        coremark_dir / "core_matrix.c",
        coremark_dir / "core_state.c",
        coremark_dir / "core_util.c",
        patched_portme,
        port_dir / "ee_printf.c",
        simple_dir / "simple_system_common.c",
        simple_dir / "crt0.S",
    ]

    cflags = [
        "-march=rv32im_zicsr",
        "-mabi=ilp32",
        "-static",
        "-mcmodel=medlow",
        "-mtune=sifive-3-series",
        "-O3",
        "-falign-functions=16",
        "-funroll-all-loops",
        "-finline-functions",
        "-falign-jumps=4",
        "-nostdlib",
        "-nostartfiles",
        "-ffreestanding",
        "-mstrict-align",
        f"-DTOTAL_DATA_SIZE={total_data_size}",
        "-DMAIN_HAS_NOARGC=1",
        f"-D{run_macro}=1",
        f"-DITERATIONS={iterations}",
        f"-DCOREMARK_EXEC_MASK={exec_mask}",
        "-DHAS_FLOAT=0",
        "-DSUPPRESS_PCOUNT_DUMP=1",
        "-DCOMPILER_FLAGS=\"arch-ibex coremark compare\"",
        f"-I{compat_inc}",
        f"-I{simple_dir}",
        f"-I{port_dir}",
        f"-I{coremark_dir}",
    ]

    link_flags = [
        f"-Wl,-T,{simple_dir / 'link.ld'}",
        "-Wl,--no-relax",
        f"-Wl,-Map={build / 'coremark.map'}",
        "-lgcc",
    ]

    result = subprocess.run(
        [gcc, *cflags, "-o", str(elf), *[str(p) for p in sources], *link_flags],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"CoreMark compile failed:\nSTDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout}"
        )

    with (build / "coremark.dis").open("w") as disasm:
        subprocess.run([objdump, "-SD", str(elf)], check=True, stdout=disasm)
    subprocess.run([objcopy, "-O", "binary", str(elf), str(bin_path)], check=True)
    subprocess.run(
        [shutil.which("python3") or "python3", str(BIN2VMEM), str(bin_path), str(vmem)],
        check=True,
    )
    return vmem


@pytest.fixture(scope="session")
def coremark_dut_exe(
    arch_bin: str,
    ibex_root: Path,
    fusesoc_bin: str,
    tmp_path_factory: pytest.TempPathFactory,
):
    root = tmp_path_factory.mktemp("coremark_dut")
    return _build_model(
        _dut_filelist(arch_bin, ibex_root, fusesoc_bin, root),
        tmp_path_factory.mktemp("coremark_dut_sim"),
    )


@pytest.fixture(scope="session")
def coremark_ref_exe(
    arch_bin: str,
    ibex_root: Path,
    fusesoc_bin: str,
    tmp_path_factory: pytest.TempPathFactory,
):
    root = tmp_path_factory.mktemp("coremark_ref")
    return _build_model(
        _ref_filelist(arch_bin, ibex_root, fusesoc_bin, root),
        tmp_path_factory.mktemp("coremark_ref_sim"),
    )


def _parse_metrics(log: str) -> CoremarkMetrics:
    ticks = re.search(r"^Total ticks\s*:\s*(\d+)", log, re.MULTILINE)
    iterations = re.search(r"^Iterations\s*:\s*(\d+)", log, re.MULTILINE)
    if ticks is None or iterations is None:
        raise AssertionError(
            f"failed to parse CoreMark metrics from log:\n{log[-4000:]}"
        )
    if "Errors detected" in log:
        raise AssertionError(f"CoreMark reported errors:\n{log[-4000:]}")
    validated = "Correct operation validated" in log
    require_validation = os.environ.get("COREMARK_REQUIRE_VALIDATION", "0") == "1"
    if require_validation and not validated:
        raise AssertionError(f"CoreMark did not validate:\n{log[-4000:]}")
    total_ticks = int(ticks.group(1))
    iteration_count = int(iterations.group(1))
    return CoremarkMetrics(
        total_ticks=total_ticks,
        iterations=iteration_count,
        coremark_per_mhz=(1_000_000.0 * iteration_count) / total_ticks,
        validated=validated,
        log=log,
    )


def _run_coremark(exe: Path, vmem: Path, tmp_path: Path, label: str) -> CoremarkMetrics:
    run_dir = tmp_path / f"run_{label}"
    run_dir.mkdir()
    log_path = run_dir / "ibex_mini_soc.log"
    env = os.environ.copy()
    env.setdefault("COREMARK_MAX_CYCLES", "20000000")
    env["VMEM_PATH"] = str(vmem)
    result = subprocess.run(
        [str(exe)],
        cwd=run_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    (tmp_path / f"coremark_{label}.stdout").write_text(result.stdout)
    (tmp_path / f"coremark_{label}.stderr").write_text(result.stderr)
    try:
        log = log_path.read_text(errors="replace")
    except FileNotFoundError:
        log = ""
    (tmp_path / f"coremark_{label}.log").write_text(log)
    assert result.returncode == 0, (
        f"CoreMark {label} simulation failed with {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\n"
        f"stderr:\n{result.stderr[-4000:]}\n"
        f"log:\n{log[-4000:]}"
    )
    return _parse_metrics(log)


def test_coremark_swap_matches_upstream(
    built_coremark: Path,
    coremark_dut_exe: Path,
    coremark_ref_exe: Path,
    tmp_path: Path,
) -> None:
    dut = _run_coremark(coremark_dut_exe, built_coremark, tmp_path, "dut")
    ref = _run_coremark(coremark_ref_exe, built_coremark, tmp_path, "upstream")

    expected_iterations = int(os.environ.get("COREMARK_ITERATIONS", "1"))
    assert dut.iterations == ref.iterations == expected_iterations
    ratio = dut.total_ticks / ref.total_ticks
    print(
        f"CoreMark compare: dut_ticks={dut.total_ticks} "
        f"upstream_ticks={ref.total_ticks} ratio={ratio:.4f} "
        f"dut_cm_mhz={dut.coremark_per_mhz:.6f} "
        f"upstream_cm_mhz={ref.coremark_per_mhz:.6f} "
        f"validated={dut.validated and ref.validated}"
    )

    max_ratio = float(os.environ.get("COREMARK_MAX_RATIO", "1.10"))
    assert ratio <= max_ratio, (
        f"CoreMark regression: ARCH-swap ticks={dut.total_ticks}, "
        f"upstream ticks={ref.total_ticks}, ratio={ratio:.4f} > {max_ratio:.4f}"
    )
