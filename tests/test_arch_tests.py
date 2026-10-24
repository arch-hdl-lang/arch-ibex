"""Phase-C end-gate: RISC-V Architectural Tests on the arch-ibex SoC.

Runs every `.S` test under
  ~/github/ibex/vendor/riscv-arch-tests/riscv-test-suite/rv32i_m/{I,M,C}/src/
end-to-end on `ibex_mini_soc` with our IbexCore+IbexTop swap built-in,
and compares the test signature against a reference signature
committed under `tests/arch_tests/references/<isa>/<name>.signature`.

Reference generation
--------------------
References are produced by running the same test on UPSTREAM Ibex
(no swap — `build/*.sv` temporarily hidden from the filelist) inside
the same SoC. This is bit-for-bit equivalence: a passing arch test
means our swap and upstream Ibex compute the same architectural state
for that program.

Generate references with:
    ARCH_TESTS_GENERATE_REF=1 pytest tests/test_arch_tests.py

That builds a SECOND Verilator binary (upstream Ibex), runs every
test through it, writes `tests/arch_tests/references/<isa>/<name>.signature`,
and skips the comparison. Subsequent normal runs read those files.

If you change `model_test.h` / link.ld / the macro layout, regenerate.
Every generated or run signature must pass the vacuity guard (below), and
`test_arch_test_reference_nonvacuous` checks the committed references
without simulating, so an empty-body build cannot pass again.
The references are content-addressed by the test source + env, so a
.gitignored cache wouldn't be reproducible across machines — we
commit them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import pytest


TESTS_DIR = Path(__file__).parent
ARCH_TESTS_DIR = TESTS_DIR / "arch_tests"
REFERENCES_DIR = ARCH_TESTS_DIR / "references"
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"

# Where the upstream test sources live. Resolved against IBEX_ROOT,
# falling back to ~/github/ibex (matches conftest.py:_find_ibex_root).
DEFAULT_IBEX = Path(os.environ.get("IBEX_ROOT", str(Path.home() / "github" / "ibex")))
ARCH_TEST_SUITE = DEFAULT_IBEX / "vendor" / "riscv-arch-tests" / "riscv-test-suite"

GENERATE_REF = os.environ.get("ARCH_TESTS_GENERATE_REF", "") == "1"


pytest.importorskip("cocotb_tools.runner")


# ── test discovery ──────────────────────────────────────────────────
@dataclass(frozen=True)
class ArchTest:
    isa: str          # "I" / "M" / "C"
    name: str         # filename stem, e.g. "add-01"

    @property
    def src_path(self) -> Path:
        return ARCH_TEST_SUITE / "rv32i_m" / self.isa / "src" / f"{self.name}.S"

    @property
    def ref_path(self) -> Path:
        return REFERENCES_DIR / self.isa / f"{self.name}.signature"

    def __str__(self) -> str:
        return f"{self.isa}/{self.name}"


def _discover_tests() -> list[ArchTest]:
    tests: list[ArchTest] = []
    for isa in ("I", "M", "C"):
        src_dir = ARCH_TEST_SUITE / "rv32i_m" / isa / "src"
        if not src_dir.is_dir():
            continue
        for s in sorted(src_dir.glob("*.S")):
            tests.append(ArchTest(isa=isa, name=s.stem))
    return tests


ALL_TESTS: list[ArchTest] = _discover_tests()


# Tests we deliberately skip with a documented reason. Populated as
# we encounter unsupported features. See tests/arch_tests/skipped.txt
# for the human-readable list.
SKIP_REASONS: dict[str, str] = {
    # populated from tests/arch_tests/skipped.txt at session start
}

def _load_skip_reasons() -> None:
    sk = ARCH_TESTS_DIR / "skipped.txt"
    if not sk.is_file():
        return
    for raw in sk.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # format: <isa>/<name>: <reason>
        if ":" not in line:
            continue
        key, _, reason = line.partition(":")
        SKIP_REASONS[key.strip()] = reason.strip()

_load_skip_reasons()


# Known failures, tracked as strict xfails (an unexpected pass fails the
# run, so a fixed test cannot stay silently marked). Same format as
# skipped.txt, in tests/arch_tests/xfail.txt; each reason points at a repro.
XFAIL_REASONS: dict[str, str] = {}

def _load_xfail_reasons() -> None:
    xf = ARCH_TESTS_DIR / "xfail.txt"
    if not xf.is_file():
        return
    for raw in xf.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, reason = line.partition(":")
        XFAIL_REASONS[key.strip()] = reason.strip()

_load_xfail_reasons()


# ── vacuity guard ────────────────────────────────────────────────────
# Until 2026-10 every test here assembled to its init/halt stub (the
# bodies sit under `#ifdef TEST_CASE_1`, which nothing defined), so each
# signature was its initial fill and the references were ~99% 0xdeadbeef;
# all 74 "passed" against references generated the same way. The guard
# checks the property that failure broke: a test must overwrite its
# signature. The framework lays the region out as
#   canary, <main signature: one 0xdeadbeef slot per stored result>,
#   [canary, trap signature, canary], canary, zero padding
# and the main signature has exactly as many slots as the body stores, so
# a test whose body ran leaves almost none of them at the fill value (the
# worst real case is sb-align-01, 1 of 70: a byte store into a fill word).
SIG_CANARY = "6f5ca309"
SIG_FILL = "deadbeef"
MAX_UNTOUCHED_FRACTION = 0.10


def _main_signature(words: list[str]) -> list[str]:
    """The words between the leading canary and the next one."""
    if not words or words[0] != SIG_CANARY or SIG_CANARY not in words[1:]:
        raise AssertionError(
            f"signature does not start with the framework canary "
            f"{SIG_CANARY} followed by a closing canary: head {words[:4]!r}"
        )
    return words[1:words.index(SIG_CANARY, 1)]


def _assert_signature_nonvacuous(words: list[str], what: str) -> None:
    body = _main_signature(words)
    untouched = sum(w == SIG_FILL for w in body)
    assert body and untouched <= MAX_UNTOUCHED_FRACTION * len(body), (
        f"{what}: {untouched} of {len(body)} signature slots still hold the "
        f"fill pattern {SIG_FILL} -- the test body most likely did not run "
        f"(was it assembled? see the RVTEST_CASE defines in "
        f"tests/arch_tests/Makefile)"
    )


# ── fixtures ─────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def riscv_gcc() -> str:
    tool = shutil.which("riscv64-elf-gcc")
    if tool is None:
        pytest.skip(
            "riscv64-elf-gcc not on PATH; install via "
            "`brew install riscv64-elf-gcc`"
        )
    return tool


@pytest.fixture(scope="session")
def arch_tests_build_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("arch_tests_build")


@pytest.fixture(scope="session")
def built_arch_tests(
    riscv_gcc: str,
    arch_tests_build_dir: Path,
) -> dict[str, dict[str, Path]]:
    """Run `make all` once for every discovered test.

    Returns a nested dict: `{ "<isa>/<name>": {"vmem": Path, "syms": Path} }`."""
    if not ARCH_TEST_SUITE.is_dir():
        pytest.skip(f"arch test suite not found at {ARCH_TEST_SUITE}")

    result = subprocess.run(
        ["make", "-C", str(ARCH_TESTS_DIR),
         f"BUILD={arch_tests_build_dir}",
         f"ARCH_TEST_SRC={ARCH_TEST_SUITE}",
         "all"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"arch_tests make failed:\nSTDERR:\n{result.stderr[-2000:]}\n"
            f"STDOUT:\n{result.stdout[-2000:]}"
        )

    out: dict[str, dict[str, Path]] = {}
    for t in ALL_TESTS:
        vmem = arch_tests_build_dir / t.isa / f"{t.name}.vmem"
        syms = arch_tests_build_dir / t.isa / f"{t.name}.syms"
        if not vmem.is_file() or not syms.is_file():
            raise RuntimeError(
                f"missing build artifacts for {t}: {vmem} / {syms}"
            )
        out[str(t)] = {"vmem": vmem, "syms": syms}
    return out


# .vc parsing — duplicated from test_cpu_programs.py to keep this
# collector self-contained.
def _parse_vc(vc_path: Path) -> Tuple[List[str], List[str], List[str], List[str]]:
    incdirs: List[str] = []
    sv_files: List[str] = []
    vlt_files: List[str] = []
    defines: List[str] = []
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


def _build_runner(
    ibex_soc_filelist: dict,
    sim_build: Path,
):
    """Compile `ibex_mini_soc` under Verilator+cocotb. Returns the runner."""
    from cocotb_tools.runner import VerilatorControlFile, get_runner

    vc_path: Path = ibex_soc_filelist["vc_path"]
    build_dir: Path = ibex_soc_filelist["build_dir"]
    extra_sv: list[Path] = ibex_soc_filelist["extra_sv"]

    incdirs, sv_files, vlt_files, defines = _parse_vc(vc_path)

    def _abs(p: str) -> str:
        pp = Path(p)
        if not pp.is_absolute():
            pp = build_dir / pp
        return str(pp.resolve())

    abs_incdirs   = [_abs(p) for p in incdirs]
    abs_sv_files  = [_abs(p) for p in sv_files]
    abs_vlt_files = [_abs(p) for p in vlt_files]

    sources = (
        [VerilatorControlFile(p) for p in abs_vlt_files]
        + abs_sv_files
        + [str(p) for p in extra_sv]
    )

    runner = get_runner("verilator")
    runner.build(
        sources=sources,
        hdl_toplevel="ibex_mini_soc",
        build_dir=str(sim_build),
        always=True,
        includes=abs_incdirs,
        build_args=[
            *defines,
            "--unroll-count", "72",
            "--public-flat-rw",
            "-Wno-IMPORTSTAR",
            "-Wno-UNUSEDSIGNAL",
            "-Wno-UNUSEDPARAM",
            "-Wno-PINMISSING",
            "-Wno-WIDTHEXPAND",
            "-Wno-fatal",
        ],
    )
    return runner


@pytest.fixture(scope="session")
def arch_tests_dut_runner(
    ibex_soc_filelist: dict,
    tmp_path_factory: pytest.TempPathFactory,
):
    """Verilator+cocotb sim with our IbexCore+IbexTop swap."""
    sim_build = tmp_path_factory.mktemp("arch_tests_dut_sim")
    runner = _build_runner(ibex_soc_filelist, sim_build)
    return runner, sim_build


# ── reference-build path (only constructed when ARCH_TESTS_GENERATE_REF=1) ─
def _ref_filelist(
    arch_bin: str,
    ibex_root: Path,
    fusesoc_bin: str,
    tmp_path: Path,
) -> dict:
    """Build a filelist that uses UPSTREAM Ibex (no swap).

    Reuses the same fusesoc-resolved Ibex tree + generated CLINT/PLIC
    that the normal flow uses, but skips the `build/*.sv` swap. This
    runs each test on the reference RTL so we can capture its
    signature output."""
    # Imported lazily so non-ref runs don't pay for fusesoc setup twice.
    from tests.conftest import (  # type: ignore
        _generate_clint_plic_sv, _fusesoc_setup, _strip_top_and_exe,
        SOC_DIR,
    )

    # 1. CLINT/PLIC/mtrap generated SVs.
    generated_dir = tmp_path / "generated"
    gen_sv = _generate_clint_plic_sv(arch_bin, generated_dir)

    # 2. fusesoc → .vc, BUT we don't shadow any upstream files. Pass an
    #    empty shadow set rather than the global one (which the DUT path
    #    has already mutated).
    vc_path = _fusesoc_setup(ibex_root, tmp_path, fusesoc_bin)
    # Strip top-module/exe/-G but keep all upstream sources. We can't
    # call _strip_top_and_exe directly because it consults the
    # _SV_SHADOWED_BY_FORKS module-level set; reimplement the strip
    # inline so the swap shadowing doesn't apply.
    out = []
    for line in vc_path.read_text().splitlines():
        s = line.strip()
        if (
            s.startswith("--top-module")
            or s == "--exe"
            or s.startswith("-G")
            or Path(s).name == "ibex_cs_registers.sv"  # we always replace this with hybrid
        ):
            continue
        out.append(line)
    stripped = "\n".join(out) + "\n"
    stripped_vc = vc_path.with_suffix(".ref.vc")
    stripped_vc.write_text(stripped)

    # 3. Hand-written SoC glue + ibex_cs_registers_hybrid (still needed —
    #    it's where the generated mscratch CsrFile gets instantiated).
    soc_sv = [
        SOC_DIR / "obi_to_axi_lite.sv",
        SOC_DIR / "ibex_mini_soc.sv",
        SOC_DIR / "ibex_cs_registers_hybrid.sv",
    ]
    shared_sv = [
        ibex_root / "shared" / "rtl" / "ram_2p.sv",
        ibex_root / "shared" / "rtl" / "sim" / "simulator_ctrl.sv",
    ]
    for p in shared_sv:
        if not p.is_file():
            pytest.skip(f"Ibex shared SV missing at {p}")

    return {
        "vc_path":   stripped_vc,
        "extra_sv":  gen_sv + soc_sv + shared_sv,  # NO arch swaps
        "build_dir": stripped_vc.parent,
    }


@pytest.fixture(scope="session")
def arch_tests_ref_runner(
    arch_bin: str,
    ibex_root: Path,
    fusesoc_bin: str,
    tmp_path_factory: pytest.TempPathFactory,
):
    """Verilator+cocotb sim with UPSTREAM Ibex (no swap). Only built
    when generating references."""
    if not GENERATE_REF:
        pytest.skip("not generating references this session")
    ref_root = tmp_path_factory.mktemp("arch_tests_ref")
    fl = _ref_filelist(arch_bin, ibex_root, fusesoc_bin, ref_root)
    sim_build = tmp_path_factory.mktemp("arch_tests_ref_sim")
    runner = _build_runner(fl, sim_build)
    return runner, sim_build


# ── one-line signature comparison helper ────────────────────────────
def _read_signature(p: Path) -> list[str]:
    return [l.strip().lower() for l in p.read_text().splitlines() if l.strip()]


def _run_one(
    test: ArchTest,
    runner_fixture,
    built: dict[str, dict[str, Path]],
    out_signature: Path,
    tmp_path: Path,
) -> None:
    runner, sim_build = runner_fixture
    arts = built[str(test)]
    out_signature.parent.mkdir(parents=True, exist_ok=True)
    results_xml = runner.test(
        test_module="test_arch_tests",
        hdl_toplevel="ibex_mini_soc",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / f"results_{test.isa}_{test.name}.xml"),
        extra_env={
            "VMEM_PATH":      str(arts["vmem"]),
            "SYMS_PATH":      str(arts["syms"]),
            "SIGNATURE_OUT":  str(out_signature),
        },
    )
    tree = ET.parse(results_xml)
    root = tree.getroot()
    failures = (
        int(root.attrib.get("failures", "0"))
        + int(root.attrib.get("errors", "0"))
    )
    assert failures == 0, (
        f"cocotb failed for {test}; see {results_xml}"
    )
    _assert_signature_nonvacuous(_read_signature(out_signature), f"{test} run")


# ── reference-generation pass ───────────────────────────────────────
@pytest.mark.skipif(not GENERATE_REF, reason="set ARCH_TESTS_GENERATE_REF=1")
@pytest.mark.parametrize("test", ALL_TESTS, ids=str)
def test_arch_test_generate_reference(
    test: ArchTest,
    arch_tests_ref_runner,
    built_arch_tests: dict[str, dict[str, Path]],
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    """Run on UPSTREAM Ibex; write the reference signature into the repo."""
    if str(test) in XFAIL_REASONS:
        request.node.add_marker(pytest.mark.xfail(reason=XFAIL_REASONS[str(test)], strict=True))
    sig_out = tmp_path / f"{test.isa}_{test.name}.signature"
    # _run_one applies the vacuity guard before anything reaches the repo.
    _run_one(test, arch_tests_ref_runner, built_arch_tests, sig_out, tmp_path)
    test.ref_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sig_out, test.ref_path)


# ── DUT pass: run on swap, compare to reference ─────────────────────
@pytest.mark.skipif(GENERATE_REF, reason="generating refs this session")
@pytest.mark.parametrize("test", ALL_TESTS, ids=str)
def test_arch_test_on_swap(
    test: ArchTest,
    arch_tests_dut_runner,
    built_arch_tests: dict[str, dict[str, Path]],
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    """Run on our IbexCore/IbexTop swap; signature must match the reference."""
    skip_key = str(test)
    if skip_key in SKIP_REASONS:
        pytest.skip(SKIP_REASONS[skip_key])
    xfail = skip_key in XFAIL_REASONS
    if xfail:
        request.node.add_marker(pytest.mark.xfail(reason=XFAIL_REASONS[skip_key], strict=True))

    if not test.ref_path.is_file() and not xfail:
        pytest.fail(
            f"no reference at {test.ref_path}; run with "
            f"ARCH_TESTS_GENERATE_REF=1 to generate it on upstream Ibex"
        )

    sig_out = tmp_path / f"{test.isa}_{test.name}.signature"
    _run_one(test, arch_tests_dut_runner, built_arch_tests, sig_out, tmp_path)
    if not test.ref_path.is_file():
        # A known failure with no reference (it cannot run on upstream Ibex
        # either) that now completes with a real signature: XPASS, which the
        # strict xfail turns into a failure asking for a reference.
        return

    # Strict word-for-word comparison.
    actual   = _read_signature(sig_out)
    expected = _read_signature(test.ref_path)
    assert actual == expected, (
        f"signature mismatch for {test}: "
        f"len(actual)={len(actual)} len(expected)={len(expected)}; "
        f"first diff at index "
        f"{next((i for i, (a, e) in enumerate(zip(actual, expected)) if a != e), '?')}; "
        f"actual head: {actual[:4]!r}; expected head: {expected[:4]!r}"
    )


# ── static guard on the committed references (no simulation) ───────
@pytest.mark.parametrize("test", ALL_TESTS, ids=str)
def test_arch_test_reference_nonvacuous(test: ArchTest) -> None:
    """Every test has a committed reference whose signature was actually
    written (see the vacuity guard above), unless it is a tracked xfail
    or skip."""
    key = str(test)
    if not test.ref_path.is_file():
        assert key in XFAIL_REASONS or key in SKIP_REASONS, (
            f"no reference at {test.ref_path}; generate it with "
            f"ARCH_TESTS_GENERATE_REF=1, or list the test in "
            f"tests/arch_tests/xfail.txt with a reason"
        )
        pytest.skip(f"no reference: {XFAIL_REASONS.get(key) or SKIP_REASONS.get(key)}")
    _assert_signature_nonvacuous(_read_signature(test.ref_path), f"reference {test.ref_path.name}")
