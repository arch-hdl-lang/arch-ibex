"""Phase 1 HARC full-verification canaries.

Each row runs the reviewed reusable HARC VIP + unit test through check,
emit-only, simulation, functional coverage assertions, and ARCH source
coverage gating.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.harc_runner import (
    REPO_ROOT,
    assert_arch_coverage_dat_100,
    harc_check,
    harc_sim_dut_coverage,
    harc_sim_emit_only,
    resolve_arch_bin,
)


@dataclass(frozen=True)
class HarcCanary:
    top: str
    dut_file: str
    harc_files: tuple[str, str]
    test: str
    require_branch_data: bool = True


PHASE1_CANARIES = (
    HarcCanary(
        top="ibex_alu",
        dut_file="src/IbexAlu.arch",
        harc_files=(
            "tests/harc/lib/ibex_alu_vip.harc",
            "tests/harc/unit/ibex_alu_harc_test.harc",
        ),
        test="IbexAluFullVerification",
    ),
    HarcCanary(
        top="ibex_counter",
        dut_file="src/IbexCounter.arch",
        harc_files=(
            "tests/harc/lib/ibex_counter_vip.harc",
            "tests/harc/unit/ibex_counter_harc_test.harc",
        ),
        test="IbexCounterCanary",
    ),
    HarcCanary(
        top="ibex_register_file_ff",
        dut_file="src/IbexRegisterFileFf.arch",
        harc_files=(
            "tests/harc/lib/ibex_register_file_ff_vip.harc",
            "tests/harc/unit/ibex_register_file_ff_harc_test.harc",
        ),
        test="IbexRegisterFileFfCanary",
    ),
    HarcCanary(
        top="ibex_wb_stage",
        dut_file="src/IbexWbStage.arch",
        harc_files=(
            "tests/harc/lib/ibex_wb_stage_vip.harc",
            "tests/harc/unit/ibex_wb_stage_harc_test.harc",
        ),
        test="IbexWbStagePhase1Canary",
        require_branch_data=False,
    ),
)


@pytest.mark.parametrize("canary", PHASE1_CANARIES, ids=lambda c: c.top)
def test_harc_phase1_canary(canary: HarcCanary, tmp_path: Path) -> None:
    dut_file = REPO_ROOT / canary.dut_file
    harc_files = [REPO_ROOT / path for path in canary.harc_files]
    extra_args = ("--arch-bin", resolve_arch_bin(), "--codegen", "v1")

    harc_check(harc_files=harc_files, cwd=REPO_ROOT)
    harc_sim_emit_only(
        harc_files=harc_files,
        dut_files=[dut_file],
        top=canary.top,
        test=canary.test,
        outdir=tmp_path / "emit",
        cwd=REPO_ROOT,
        extra_args=extra_args,
    )
    run = harc_sim_dut_coverage(
        harc_files=harc_files,
        dut_files=[dut_file],
        top=canary.top,
        test=canary.test,
        outdir=tmp_path / "sim",
        cwd=REPO_ROOT,
        extra_args=extra_args,
    )
    assert_arch_coverage_dat_100(
        run.coverage_files[0],
        source_prefixes=[dut_file],
        require_branch_data=canary.require_branch_data,
    )
