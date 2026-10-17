"""Phase 1 HARC full-verification canaries.

Each row runs the reviewed reusable HARC VIP + unit test through check,
emit-only, simulation, functional coverage assertions, and ARCH source
coverage gating.

A row may list several parameter configurations. Every configuration is
simulated and the ARCH source coverage is gated on the merge of all runs: a
branch on a parameter (e.g. `if ReadOneHotA == 1`) can only be reached in the
configuration that selects it, so a single run can never cover both arms.
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
    merge_coverage_dat,
    resolve_arch_bin,
)


@dataclass(frozen=True)
class CanaryConfig:
    """One simulation of a canary: the HARC test to run and DUT parameter
    overrides (`harc sim --param NAME=VALUE`)."""

    test: str
    parameters: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class HarcCanary:
    top: str
    dut_file: str
    harc_files: tuple[str, str]
    configs: tuple[CanaryConfig, ...]
    require_branch_data: bool = True


PHASE1_CANARIES = (
    HarcCanary(
        top="ibex_alu",
        dut_file="src/IbexAlu.arch",
        harc_files=(
            "tests/harc/lib/ibex_alu_vip.harc",
            "tests/harc/unit/ibex_alu_harc_test.harc",
        ),
        configs=(CanaryConfig("IbexAluFullVerification"),),
    ),
    HarcCanary(
        top="ibex_counter",
        dut_file="src/IbexCounter.arch",
        harc_files=(
            "tests/harc/lib/ibex_counter_vip.harc",
            "tests/harc/unit/ibex_counter_harc_test.harc",
        ),
        configs=(
            CanaryConfig("IbexCounterCanary"),
            # counter_val_upd_o's `ProvideValUpd ? ... : 0` else arm
            CanaryConfig("IbexCounterCanaryNoUpd", (("ProvideValUpd", 0),)),
        ),
    ),
    HarcCanary(
        top="ibex_register_file_ff",
        dut_file="src/IbexRegisterFileFf.arch",
        harc_files=(
            "tests/harc/lib/ibex_register_file_ff_vip.harc",
            "tests/harc/unit/ibex_register_file_ff_harc_test.harc",
        ),
        configs=(
            CanaryConfig("IbexRegisterFileFfCanary"),
            # the one-hot port-A read ibex_top instantiates (#14)
            CanaryConfig("IbexRegisterFileFfCanary", (("ReadOneHotA", 1),)),
        ),
    ),
    HarcCanary(
        top="ibex_wb_stage",
        dut_file="src/IbexWbStage.arch",
        harc_files=(
            "tests/harc/lib/ibex_wb_stage_vip.harc",
            "tests/harc/unit/ibex_wb_stage_harc_test.harc",
        ),
        configs=(CanaryConfig("IbexWbStagePhase1Canary"),),
        require_branch_data=False,
    ),
)


@pytest.mark.parametrize("canary", PHASE1_CANARIES, ids=lambda c: c.top)
def test_harc_phase1_canary(canary: HarcCanary, tmp_path: Path) -> None:
    dut_file = REPO_ROOT / canary.dut_file
    harc_files = [REPO_ROOT / path for path in canary.harc_files]
    extra_args = ("--arch-bin", resolve_arch_bin())

    harc_check(harc_files=harc_files, cwd=REPO_ROOT)
    coverage_files = []
    for i, cfg in enumerate(canary.configs):
        parameters = dict(cfg.parameters)
        harc_sim_emit_only(
            harc_files=harc_files,
            dut_files=[dut_file],
            top=canary.top,
            test=cfg.test,
            outdir=tmp_path / f"emit{i}",
            parameters=parameters,
            cwd=REPO_ROOT,
            extra_args=extra_args,
        )
        run = harc_sim_dut_coverage(
            harc_files=harc_files,
            dut_files=[dut_file],
            top=canary.top,
            test=cfg.test,
            outdir=tmp_path / f"sim{i}",
            parameters=parameters,
            cwd=REPO_ROOT,
            extra_args=extra_args,
        )
        coverage_files.append(run.coverage_files[0])
    if len(coverage_files) == 1:
        coverage = coverage_files[0]
    else:
        coverage = merge_coverage_dat(coverage_files, output=tmp_path / "merged.dat")
    assert_arch_coverage_dat_100(
        coverage,
        source_prefixes=[dut_file],
        require_branch_data=canary.require_branch_data,
    )
