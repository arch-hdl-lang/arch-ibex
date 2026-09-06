"""arch sim --pybind --test gate over the per-module cocotb suites.

For every landed swap, this runs the same `cocotb_tests/test_<m>_unit.py`
file that the verilator gate (`tests/test_<m>_unit.py`) runs, but
through `arch sim --pybind` instead of Verilator. Catches sim-level
divergences against the SV path and complements verilator's lint
coverage.

Wall-clock per (module, backend) is recorded into a JUnit-style
`property` on each test for follow-up perf tracking; pytest-xdist
parallelism still applies.

Skipped wholesale if the arch binary isn't discoverable (matches the
existing `arch_bin` fixture's behavior in the verilator-side conftest).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
SRC_DIR = REPO_ROOT / "src"


# (arch_file_stem, cocotb_test_filename). One row per landed swap;
# names match the upstream Ibex module + the existing
# `cocotb_tests/test_<snake>_unit.py` suite.
MODULES = [
    ("IbexAlu",                "test_ibex_alu_unit.py"),
    ("IbexRegisterFileFf",     "test_ibex_register_file_ff_unit.py"),
    ("IbexCounter",            "test_ibex_counter_unit.py"),
    ("IbexDecoder",            "test_ibex_decoder_unit.py"),
    ("IbexCompressedDecoder",  "test_ibex_compressed_decoder_unit.py"),
    ("IbexMultdivFast", "test_ibex_multdiv_fast_unit.py"),
]


def _camel_to_snake(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    return s.lower()


@pytest.mark.parametrize(
    "arch_stem,cocotb_test",
    MODULES,
    ids=[(m.values[0] if hasattr(m, "values") else m[0]) for m in MODULES],
)
def test_archsim_unit(
    arch_bin: str,
    arch_stem: str,
    cocotb_test: str,
    tmp_path_factory: pytest.TempPathFactory,
    record_property,
):
    arch_file = SRC_DIR / f"{arch_stem}.arch"
    test_file = COCOTB_TESTS_DIR / cocotb_test
    if not arch_file.is_file():
        pytest.skip(f"missing {arch_file}; run `make build` first")
    if not test_file.is_file():
        pytest.skip(f"missing {test_file}")

    # Each module gets its own outdir so xdist workers don't collide.
    outdir = tmp_path_factory.mktemp(f"archsim_{_camel_to_snake(arch_stem)}")

    cmd = [
        arch_bin, "sim", "--pybind",
        "--test", str(test_file),
        "-o", str(outdir),
        str(arch_file),
    ]
    env = os.environ.copy()
    # The launcher inherits PYTHONPATH; keep cwd inside outdir so the
    # generated runner's relative imports land correctly.
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd, cwd=str(outdir),
        env=env,
        capture_output=True, text=True,
        timeout=300,
    )
    elapsed = time.perf_counter() - t0
    record_property("archsim_wall_seconds", f"{elapsed:.3f}")
    record_property("archsim_module", arch_stem)

    # arch sim returns non-zero on any cocotb failure; on stderr we
    # expect a green footer: arch <= 0.71 printed "ALL PASSED"; the 0.72
    # native cocotb runtime prints "Results: N tests; N passed, 0 failed, 0 skipped".
    out = proc.stdout + proc.stderr
    summary_ok = "ALL PASSED" in out or (
        re.search(r"Results: \d+ tests; \d+ passed, 0 failed", out) is not None
    )
    if proc.returncode != 0 or not summary_ok:
        # Surface tails to make CI noise debuggable.
        tail_out = "\n".join(proc.stdout.splitlines()[-40:])
        tail_err = "\n".join(proc.stderr.splitlines()[-40:])
        pytest.fail(
            f"arch sim failed for {arch_stem} (rc={proc.returncode}, "
            f"{elapsed:.2f}s)\n"
            f"--- STDOUT (tail) ---\n{tail_out}\n"
            f"--- STDERR (tail) ---\n{tail_err}\n"
        )
