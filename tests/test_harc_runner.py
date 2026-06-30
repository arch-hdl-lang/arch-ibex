import json
import os
from pathlib import Path

import pytest

from tests.harc_runner import (
    ArchCoverageWaiver,
    FunctionalCoverageBinWaiver,
    FunctionalCoverageWaiver,
    HarcSim,
    arch_coverage_dat_totals,
    assert_merged_harc_functional_selected_cross_bin_waivers,
    assert_merged_harc_functional_selected_cross_waivers,
    assert_merged_harc_functional_coverage_100,
    assert_compressed_decoder_coverage_status_complete,
    compressed_decoder_coverage_inventory,
    compressed_decoder_coverage_status,
    crv_seed_manifest_entry,
    harc_functional_coverage_artifact,
    harc_functional_coverage_artifact_from_jsonl,
    harc_sim_coverage_command,
    HarcFunctionalCoverageCampaignInput,
    merge_harc_functional_coverage_campaigns,
    merge_harc_functional_coverage_artifacts,
    merge_coverage_dat,
    run_crv_seed_campaign,
    write_harc_functional_coverage_artifact,
    write_crv_seed_manifest,
)


def _record(source: Path, page: str, comment: str, count: int) -> str:
    payload = (
        f"\x01file\x02{source}"
        "\x01line\x021"
        f"\x01page\x02{page}"
        f"\x01comment\x02{comment}"
    )
    return f"C '{payload}' {count}"


def test_arch_coverage_ignores_generated_thread_counter_toggle(tmp_path: Path) -> None:
    dut = tmp_path / "Dut.arch"
    coverage = tmp_path / "coverage.dat"
    coverage.write_text(
        "\n".join(
            (
                "# SystemC::Coverage-3",
                _record(dut, "v_line", "comb comb", 1),
                _record(dut, "v_branch", "if ", 1),
                _record(dut, "v_toggle", "toggle toggle _t0_cnt", 0),
                _record(dut, "v_toggle", "toggle toggle _t0_loop_cnt_0", 3),
            )
        )
        + "\n"
    )

    totals = arch_coverage_dat_totals(coverage, source_prefixes=(dut,))

    assert totals.line_hit == 1
    assert totals.line_found == 1
    assert totals.branch_hit == 2
    assert totals.branch_found == 2


def test_arch_coverage_dat_waiver_excludes_exact_zero_record(tmp_path: Path) -> None:
    dut = tmp_path / "Dut.arch"
    coverage = tmp_path / "coverage.dat"
    coverage.write_text(
        "\n".join(
            (
                "# SystemC::Coverage-3",
                _record(dut, "v_line", "comb comb", 1),
                _record(dut, "v_expr", "expr-then then selector_i", 0),
                _record(dut, "v_expr", "expr-else else selector_i", 4),
            )
        )
        + "\n"
    )

    totals = arch_coverage_dat_totals(
        coverage,
        source_prefixes=(dut,),
        waivers=(
            ArchCoverageWaiver(
                source=dut,
                line=1,
                page="v_expr",
                comment="expr-then then selector_i",
                reason="producer-contract invalid selector arm",
                reviewed_by="unit test",
            ),
        ),
    )

    assert totals.line_hit == 1
    assert totals.line_found == 1
    assert totals.branch_hit == 1
    assert totals.branch_found == 1


def test_arch_coverage_dat_waiver_fails_when_stale(tmp_path: Path) -> None:
    dut = tmp_path / "Dut.arch"
    coverage = tmp_path / "coverage.dat"
    coverage.write_text(
        "\n".join(
            (
                "# SystemC::Coverage-3",
                _record(dut, "v_line", "comb comb", 1),
                _record(dut, "v_expr", "expr-then then selector_i", 2),
            )
        )
        + "\n"
    )

    with pytest.raises(AssertionError, match="did not match an uncovered item"):
        arch_coverage_dat_totals(
            coverage,
            source_prefixes=(dut,),
            waivers=(
                ArchCoverageWaiver(
                    source=dut,
                    line=1,
                    page="v_expr",
                    comment="expr-then then selector_i",
                    reason="producer-contract invalid selector arm",
                    reviewed_by="unit test",
                ),
            ),
        )


def test_merge_coverage_dat_uses_arch_coverage_merge(tmp_path: Path) -> None:
    dut = tmp_path / "Dut.arch"
    first = tmp_path / "first.dat"
    second = tmp_path / "second.dat"
    merged = tmp_path / "merged.dat"
    first.write_text(
        "\n".join(
            (
                "# SystemC::Coverage-3",
                _record(dut, "v_line", "comb comb", 1),
                _record(dut, "v_branch", "if ", 0),
            )
        )
        + "\n"
    )
    second.write_text(
        "\n".join(
            (
                "# SystemC::Coverage-3",
                _record(dut, "v_line", "comb comb", 2),
                _record(dut, "v_branch", "if ", 3),
            )
        )
        + "\n"
    )

    merge_coverage_dat((second, first), output=merged)

    text = merged.read_text()
    assert " 3\n" in text
    totals = arch_coverage_dat_totals(merged, source_prefixes=(dut,))
    assert totals.line_hit == 1
    assert totals.branch_hit == 1


def test_merge_coverage_dat_rejects_empty_input(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="no coverage.dat files"):
        merge_coverage_dat((), output=tmp_path / "merged.dat")


def test_merge_coverage_dat_reports_arch_cli_failure(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.dat"
    coverage.write_text("# SystemC::Coverage-3\n")

    with pytest.raises(AssertionError, match="HARC command failed"):
        merge_coverage_dat(
            (coverage,),
            output=tmp_path / "merged.dat",
            arch_bin=tmp_path / "missing-arch",
        )


def test_crv_seed_manifest_records_reproducible_default_tbir_command(
    tmp_path: Path,
) -> None:
    config = HarcSim(
        harc_files=("tests/harc/unit/example.harc",),
        dut_files=("src/Example.arch",),
        top="example",
        test="ExampleCrv",
        outdir=tmp_path / "seed_7",
        harc_bin="/opt/harc/bin/harc",
        extra_args=("--arch-bin", "/opt/arch/bin/arch"),
    )

    entry = crv_seed_manifest_entry(
        seed=7,
        profile="q1_addi",
        iterations=16,
        config=config,
    )
    manifest = write_crv_seed_manifest(
        (entry,),
        output=tmp_path / "campaign" / "manifest.json",
    )

    text = manifest.read_text()
    assert '"profile": "q1_addi"' in text
    assert '"seed": 7' in text
    assert '"codegen": "default-tbir"' in text
    assert "--seed 7" in text
    assert "--codegen" not in text


def test_crv_seed_manifest_rejects_codegen_escape_hatch(tmp_path: Path) -> None:
    for extra_args in (("--codegen", "v1"), ("--codegen=v1",)):
        with pytest.raises(AssertionError, match="forbids --codegen"):
            crv_seed_manifest_entry(
                seed=11,
                profile="illegal_taxonomy",
                iterations=4,
                config=HarcSim(
                    harc_files=("tests/harc/unit/example.harc",),
                    dut_files=("src/Example.arch",),
                    top="example",
                    test="ExampleCrv",
                    outdir=tmp_path / "seed_11",
                    harc_bin="/opt/harc/bin/harc",
                    extra_args=extra_args,
                ),
            )


def test_harc_sim_coverage_command_rejects_codegen_escape_hatch(
    tmp_path: Path,
) -> None:
    for extra_args in (("--codegen", "v1"), ("--codegen=v1",)):
        with pytest.raises(AssertionError, match="forbids --codegen"):
            harc_sim_coverage_command(
                HarcSim(
                    harc_files=("tests/harc/unit/example.harc",),
                    dut_files=("src/Example.arch",),
                    top="example",
                    test="ExampleCrv",
                    outdir=tmp_path / "seed_13",
                    harc_bin="/opt/harc/bin/harc",
                    extra_args=extra_args,
                )
            )


def test_harc_sim_coverage_command_records_seed(tmp_path: Path) -> None:
    cmd = harc_sim_coverage_command(
        HarcSim(
            harc_files=("tests/harc/unit/example.harc",),
            dut_files=("src/Example.arch",),
            top="example",
            test="ExampleCrv",
            outdir=tmp_path / "seed_23",
            harc_bin="/opt/harc/bin/harc",
            seed=23,
        )
    )

    assert "--seed" in cmd
    assert cmd[cmd.index("--seed") + 1] == "23"


def test_harc_sim_coverage_command_rejects_seed_extra_arg(
    tmp_path: Path,
) -> None:
    for extra_args in (("--seed", "23"), ("--seed=23",)):
        with pytest.raises(AssertionError, match="requires seed="):
            harc_sim_coverage_command(
                HarcSim(
                    harc_files=("tests/harc/unit/example.harc",),
                    dut_files=("src/Example.arch",),
                    top="example",
                    test="ExampleCrv",
                    outdir=tmp_path / "seed_extra_arg",
                    harc_bin="/opt/harc/bin/harc",
                    extra_args=extra_args,
                )
            )


def test_harc_sim_coverage_command_rejects_negative_seed(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="seed must be non-negative"):
        harc_sim_coverage_command(
            HarcSim(
                harc_files=("tests/harc/unit/example.harc",),
                dut_files=("src/Example.arch",),
                top="example",
                test="ExampleCrv",
                outdir=tmp_path / "seed_negative",
                harc_bin="/opt/harc/bin/harc",
                seed=-1,
            )
        )


def test_crv_seed_manifest_sorts_entries_for_parallel_determinism(
    tmp_path: Path,
) -> None:
    base = dict(
        harc_files=("tests/harc/unit/example.harc",),
        dut_files=("src/Example.arch",),
        top="example",
        test="ExampleCrv",
        harc_bin="/opt/harc/bin/harc",
    )
    later = crv_seed_manifest_entry(
        seed=9,
        profile="zcmp_matrix",
        iterations=8,
        config=HarcSim(
            **base,
            outdir=tmp_path / "zcmp_seed_9",
        ),
    )
    earlier = crv_seed_manifest_entry(
        seed=3,
        profile="illegal_taxonomy",
        iterations=8,
        config=HarcSim(
            **base,
            outdir=tmp_path / "illegal_seed_3",
        ),
    )
    manifest = write_crv_seed_manifest(
        (later, earlier),
        output=tmp_path / "campaign" / "manifest.json",
    )

    payload = json.loads(manifest.read_text())
    assert [(row["profile"], row["seed"]) for row in payload] == [
        ("illegal_taxonomy", 3),
        ("zcmp_matrix", 9),
    ]


def test_crv_seed_manifest_rejects_duplicate_profile_seed(tmp_path: Path) -> None:
    config = HarcSim(
        harc_files=("tests/harc/unit/example.harc",),
        dut_files=("src/Example.arch",),
        top="example",
        test="ExampleCrv",
        outdir=tmp_path / "seed_11",
        harc_bin="/opt/harc/bin/harc",
    )
    entry = crv_seed_manifest_entry(
        seed=11,
        profile="illegal_taxonomy",
        iterations=4,
        config=config,
    )

    with pytest.raises(AssertionError, match="duplicate CRV seed"):
        write_crv_seed_manifest(
            (entry, entry),
            output=tmp_path / "campaign" / "manifest.json",
        )


def test_run_crv_seed_campaign_runs_seeds_and_merges_coverage(tmp_path: Path) -> None:
    dut = tmp_path / "Example.arch"
    fake_harc = tmp_path / "fake_harc.py"
    fake_harc.write_text(
        "\n".join(
            (
                "#!/usr/bin/env python3",
                "from pathlib import Path",
                "import sys",
                "outdir = Path(sys.argv[sys.argv.index('--outdir') + 1])",
                "seed = int(sys.argv[sys.argv.index('--seed') + 1])",
                "dut = sys.argv[sys.argv.index('--dut') + 1]",
                "outdir.mkdir(parents=True, exist_ok=True)",
                "payload = '\\x01file\\x02' + dut + '\\x01line\\x021\\x01page\\x02v_line\\x01comment\\x02comb comb'",
                "(outdir / 'coverage.dat').write_text(\"# SystemC::Coverage-3\\nC '\" + payload + \"' \" + str(seed) + \"\\n\")",
            )
        )
        + "\n"
    )
    os.chmod(fake_harc, 0o755)

    campaign = run_crv_seed_campaign(
        config=HarcSim(
            harc_files=(tmp_path / "test.harc",),
            dut_files=(dut,),
            top="example",
            test="ExampleCrv",
            harc_bin=fake_harc,
            cwd=tmp_path,
        ),
        seeds=(3, 1, 2),
        profile="smoke",
        iterations=5,
        campaign_dir=tmp_path / "campaign",
        max_workers=2,
    )

    assert campaign.manifest.is_file()
    assert campaign.merged_coverage.is_file()
    assert [entry.seed for entry in campaign.entries] == [1, 2, 3]
    assert len(campaign.coverage_files) == 3
    assert arch_coverage_dat_totals(
        campaign.merged_coverage,
        source_prefixes=(dut,),
    ).line_hit == 1


def _functional_report(*, a0: int, a1: int, b0: int, b1: int, missing: tuple[str, ...]) -> str:
    hit_bins = 4 - len(missing)
    cp_hit = sum(1 for hits in (a0, a1, b0, b1) if hits > 0)
    return (
        "\n".join(
            (
                f"[Cov] coverage: {cp_hit}/4 hit (0.0%)",
                f"  cp_a (bin) [a0]: {a0} hits" + ("" if a0 else " *NOT HIT*"),
                f"  cp_a (bin) [a1]: {a1} hits" + ("" if a1 else " *NOT HIT*"),
                f"  cp_b (bin) [b0]: {b0} hits" + ("" if b0 else " *NOT HIT*"),
                f"  cp_b (bin) [b1]: {b1} hits" + ("" if b1 else " *NOT HIT*"),
                f"[Cov] cross cp_a x cp_b: {hit_bins}/4 hit (0.0%)",
                *(f"  {label}: *NOT HIT*" for label in missing),
            )
        )
        + "\n"
    )


def _functional_jsonl(path: Path, *, seed: int) -> Path:
    rows = [
        {"type": "covergroup", "group": "Cov", "hit": 1, "total": 2},
        {
            "type": "coverpoint_bin",
            "group": "Cov",
            "point": "cp_seed",
            "bin": "one",
            "hits": 1 if seed == 1 else 0,
        },
        {
            "type": "coverpoint_bin",
            "group": "Cov",
            "point": "cp_seed",
            "bin": "two",
            "hits": 1 if seed == 2 else 0,
        },
        {
            "type": "cross",
            "group": "Cov",
            "kind": "cross",
            "label": "cp_seed",
            "hit": 1,
            "total": 2,
        },
        {
            "type": "cross_bin",
            "group": "Cov",
            "kind": "cross",
            "label": "cp_seed",
            "bin": "cp_seed.one",
            "hits": 1 if seed == 1 else 0,
        },
        {
            "type": "cross_bin",
            "group": "Cov",
            "kind": "cross",
            "label": "cp_seed",
            "bin": "cp_seed.two",
            "hits": 1 if seed == 2 else 0,
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def _crv_manifest_row(*, seed: int, profile: str) -> dict[str, object]:
    return {
        "seed": seed,
        "profile": profile,
        "iterations": 1,
        "command": [
            "/opt/harc/bin/harc",
            "sim",
            "--coverage",
            "--seed",
            str(seed),
            "--coverage-json",
            f"seed_{seed}/functional_coverage.jsonl",
            "tests/harc/unit/example.harc",
        ],
        "command_string": (
            "/opt/harc/bin/harc sim --coverage --seed "
            f"{seed} --coverage-json seed_{seed}/functional_coverage.jsonl "
            "tests/harc/unit/example.harc"
        ),
        "backend": "dut",
        "codegen": "default-tbir",
        "outdir": f"seed_{seed}",
        "coverage_db": f"seed_{seed}/coverage.dat",
        "trace": f"seed_{seed}/harc_sim.log",
        "status": "passed",
    }


def test_harc_functional_coverage_artifact_rejects_truncated_cross_detail() -> None:
    report = _functional_report(
        a0=1,
        a1=0,
        b0=1,
        b1=0,
        missing=(
            "cp_a.a0 x cp_b.b1",
            "cp_a.a1 x cp_b.b0",
            "cp_a.a1 x cp_b.b1",
        ),
    )
    report += "  ... 2 more missing cross bins\n"

    with pytest.raises(AssertionError, match="report is truncated"):
        harc_functional_coverage_artifact(report, covergroups=("Cov",))


def test_harc_functional_coverage_artifact_rejects_duplicate_records() -> None:
    report = _functional_report(
        a0=1,
        a1=1,
        b0=1,
        b1=1,
        missing=(),
    )
    report = report.replace(
        "[Cov] cross cp_a x cp_b: 4/4 hit (0.0%)",
        "  cp_a (bin) [a0]: 1 hits\n[Cov] cross cp_a x cp_b: 4/4 hit (0.0%)",
    )

    with pytest.raises(AssertionError, match="duplicate coverage bin"):
        harc_functional_coverage_artifact(report, covergroups=("Cov",))


def test_harc_functional_coverage_artifact_ignores_non_cross_not_hit_lines() -> None:
    report = (
        "  SolverGoal [unused]: *NOT HIT*\n"
        "  ... 3 more missing auto-cross bins\n"
        + _functional_report(
            a0=1,
            a1=1,
            b0=1,
            b1=1,
            missing=(),
        )
    )

    artifact = harc_functional_coverage_artifact(report, covergroups=("Cov",))

    assert artifact["groups"]["Cov"]["declared_crosses"]["cp_a x cp_b"][
        "hit"
    ] == 4


def test_harc_functional_coverage_artifact_from_jsonl_preserves_cross_bins(
    tmp_path: Path,
) -> None:
    jsonl = _functional_jsonl(tmp_path / "coverage.jsonl", seed=1)

    artifact = harc_functional_coverage_artifact_from_jsonl(
        jsonl,
        covergroups=("Cov",),
        seed=1,
        profile="unit",
    )

    cross = artifact["groups"]["Cov"]["declared_crosses"]["cp_seed"]
    assert cross["hit_bins"] == ["cp_seed.one"]
    assert cross["missing_bins"] == ["cp_seed.two"]
    assert cross["bin_hits"] == {"cp_seed.one": 1, "cp_seed.two": 0}


def test_harc_functional_coverage_artifact_from_jsonl_rejects_bad_summary(
    tmp_path: Path,
) -> None:
    jsonl = _functional_jsonl(tmp_path / "coverage.jsonl", seed=1)
    text = jsonl.read_text().replace('"hit": 1, "total": 2', '"hit": 2, "total": 2')
    jsonl.write_text(text)

    with pytest.raises(AssertionError, match="hit summary"):
        harc_functional_coverage_artifact_from_jsonl(jsonl, covergroups=("Cov",))


def test_harc_functional_coverage_artifact_from_jsonl_rejects_bad_count(
    tmp_path: Path,
) -> None:
    jsonl = _functional_jsonl(tmp_path / "coverage.jsonl", seed=1)
    text = jsonl.read_text().replace('"hits": 1', '"hits": true', 1)
    jsonl.write_text(text)

    with pytest.raises(AssertionError, match="invalid 'hits'"):
        harc_functional_coverage_artifact_from_jsonl(jsonl, covergroups=("Cov",))


def test_merge_harc_functional_coverage_artifacts_reports_holes(
    tmp_path: Path,
) -> None:
    first = write_harc_functional_coverage_artifact(
        _functional_report(
            a0=1,
            a1=0,
            b0=1,
            b1=0,
            missing=(
                "cp_a.a0 x cp_b.b1",
                "cp_a.a1 x cp_b.b0",
                "cp_a.a1 x cp_b.b1",
            ),
        ),
        covergroups=("Cov",),
        path=tmp_path / "seed_1.json",
        seed=1,
        profile="unit",
    )
    second = write_harc_functional_coverage_artifact(
        _functional_report(
            a0=1,
            a1=1,
            b0=1,
            b1=1,
            missing=(
                "cp_a.a1 x cp_b.b0",
                "cp_a.a1 x cp_b.b1",
            ),
        ),
        covergroups=("Cov",),
        path=tmp_path / "seed_2.json",
        seed=2,
        profile="unit",
    )

    merged = merge_harc_functional_coverage_artifacts(
        (second, first),
        output=tmp_path / "merged.json",
        hole_report_output=tmp_path / "holes.json",
    )

    holes = json.loads(merged.hole_report.read_text())
    assert holes["groups"]["Cov"]["coverpoint_holes"] == []
    assert holes["groups"]["Cov"]["declared_cross_holes"] == [
        {"bin": "cp_a.a1 x cp_b.b0", "cross": "cp_a x cp_b"},
        {"bin": "cp_a.a1 x cp_b.b1", "cross": "cp_a x cp_b"},
    ]
    with pytest.raises(AssertionError, match="declared crosses hit\\+waived 2\\+0/4"):
        assert_merged_harc_functional_coverage_100(
            merged.merged,
            covergroups=("Cov",),
        )
    assert_merged_harc_functional_coverage_100(
        merged.merged,
        covergroups=("Cov",),
        waivers=(
            FunctionalCoverageWaiver(
                group="Cov",
                kind="cross",
                label="cp_a x cp_b",
                missing=2,
                reason="unit-test unreachable bins",
                reason_class="unit_test",
                reviewed_by="unit test",
                review_date="2026-06-29",
            ),
        ),
    )


def test_selected_cross_waiver_accounting_is_not_full_closure(
    tmp_path: Path,
) -> None:
    artifact = write_harc_functional_coverage_artifact(
        _functional_report(
            a0=1,
            a1=0,
            b0=1,
            b1=1,
            missing=(
                "cp_a.a0 x cp_b.b1",
                "cp_a.a1 x cp_b.b0",
            ),
        ),
        covergroups=("Cov",),
        path=tmp_path / "coverage.json",
    )
    merged = merge_harc_functional_coverage_artifacts(
        (artifact,),
        output=tmp_path / "merged.json",
        hole_report_output=tmp_path / "holes.json",
    )

    totals = assert_merged_harc_functional_selected_cross_waivers(
        merged.merged,
        covergroup="Cov",
        waivers=(
            FunctionalCoverageWaiver(
                group="Cov",
                kind="cross",
                label="cp_a x cp_b",
                missing=2,
                reason="unit-test selected structural rows",
                reason_class="unit_test",
                reviewed_by="unit test",
                review_date="2026-06-29",
            ),
        ),
    )

    assert totals.coverpoint_hit == 3
    assert totals.coverpoint_total == 4
    assert totals.declared_cross_hit == 2
    assert totals.declared_cross_waived == 2
    assert totals.declared_cross_total == 4
    assert totals.declared_crosses == 1
    with pytest.raises(AssertionError, match="coverpoints 3/4"):
        assert_merged_harc_functional_coverage_100(
            merged.merged,
            covergroups=("Cov",),
            waivers=(
                FunctionalCoverageWaiver(
                    group="Cov",
                    kind="cross",
                    label="cp_a x cp_b",
                    missing=2,
                    reason="unit-test selected structural rows",
                    reason_class="unit_test",
                    reviewed_by="unit test",
                    review_date="2026-06-29",
                ),
            ),
        )


def test_selected_cross_waiver_accounting_rejects_stale_count(
    tmp_path: Path,
) -> None:
    artifact = write_harc_functional_coverage_artifact(
        _functional_report(
            a0=1,
            a1=1,
            b0=1,
            b1=1,
            missing=("cp_a.a1 x cp_b.b1",),
        ),
        covergroups=("Cov",),
        path=tmp_path / "coverage.json",
    )
    merged = merge_harc_functional_coverage_artifacts(
        (artifact,),
        output=tmp_path / "merged.json",
        hole_report_output=tmp_path / "holes.json",
    )

    with pytest.raises(AssertionError, match="accounts for 2 missing bins, observed 1"):
        assert_merged_harc_functional_selected_cross_waivers(
            merged.merged,
            covergroup="Cov",
            waivers=(
                FunctionalCoverageWaiver(
                    group="Cov",
                    kind="cross",
                    label="cp_a x cp_b",
                    missing=2,
                    reason="unit-test selected structural rows",
                    reason_class="unit_test",
                    reviewed_by="unit test",
                    review_date="2026-06-29",
                ),
            ),
        )


def test_selected_cross_bin_waiver_accounting_counts_cross_once(
    tmp_path: Path,
) -> None:
    artifact = write_harc_functional_coverage_artifact(
        _functional_report(
            a0=1,
            a1=0,
            b0=1,
            b1=1,
            missing=(
                "cp_a.a0 x cp_b.b1",
                "cp_a.a1 x cp_b.b0",
                "cp_a.a1 x cp_b.b1",
            ),
        ),
        covergroups=("Cov",),
        path=tmp_path / "coverage.json",
    )
    merged = merge_harc_functional_coverage_artifacts(
        (artifact,),
        output=tmp_path / "merged.json",
        hole_report_output=tmp_path / "holes.json",
    )

    totals = assert_merged_harc_functional_selected_cross_bin_waivers(
        merged.merged,
        covergroup="Cov",
        waivers=(
            FunctionalCoverageBinWaiver(
                group="Cov",
                kind="cross_bin",
                label="cp_a x cp_b",
                bin="cp_a.a1 x cp_b.b0",
                reason="unit-test selected structural row",
                reason_class="unit_test",
                reviewed_by="unit test",
                review_date="2026-06-29",
            ),
            FunctionalCoverageBinWaiver(
                group="Cov",
                kind="cross_bin",
                label="cp_a x cp_b",
                bin="cp_a.a1 x cp_b.b1",
                reason="unit-test selected structural row",
                reason_class="unit_test",
                reviewed_by="unit test",
                review_date="2026-06-29",
            ),
        ),
    )

    assert totals.coverpoint_hit == 3
    assert totals.coverpoint_total == 4
    assert totals.declared_cross_hit == 1
    assert totals.declared_cross_waived == 2
    assert totals.declared_cross_total == 4
    assert totals.declared_crosses == 1
    with pytest.raises(AssertionError, match="coverpoints 3/4"):
        assert_merged_harc_functional_coverage_100(
            merged.merged,
            covergroups=("Cov",),
        )


def test_selected_cross_bin_waiver_accounting_rejects_stale_hit_bin(
    tmp_path: Path,
) -> None:
    artifact = write_harc_functional_coverage_artifact(
        _functional_report(
            a0=1,
            a1=1,
            b0=1,
            b1=1,
            missing=("cp_a.a1 x cp_b.b1",),
        ),
        covergroups=("Cov",),
        path=tmp_path / "coverage.json",
    )
    merged = merge_harc_functional_coverage_artifacts(
        (artifact,),
        output=tmp_path / "merged.json",
        hole_report_output=tmp_path / "holes.json",
    )

    with pytest.raises(AssertionError, match="is not currently missing"):
        assert_merged_harc_functional_selected_cross_bin_waivers(
            merged.merged,
            covergroup="Cov",
            waivers=(
                FunctionalCoverageBinWaiver(
                    group="Cov",
                    kind="cross_bin",
                    label="cp_a x cp_b",
                    bin="cp_a.a0 x cp_b.b0",
                    reason="unit-test selected structural row",
                    reason_class="unit_test",
                    reviewed_by="unit test",
                    review_date="2026-06-29",
                ),
            ),
        )


def test_selected_cross_bin_waiver_accounting_rejects_unknown_bin(
    tmp_path: Path,
) -> None:
    artifact = write_harc_functional_coverage_artifact(
        _functional_report(
            a0=1,
            a1=1,
            b0=1,
            b1=1,
            missing=("cp_a.a1 x cp_b.b1",),
        ),
        covergroups=("Cov",),
        path=tmp_path / "coverage.json",
    )
    merged = merge_harc_functional_coverage_artifacts(
        (artifact,),
        output=tmp_path / "merged.json",
        hole_report_output=tmp_path / "holes.json",
    )

    with pytest.raises(AssertionError, match="names unknown bin"):
        assert_merged_harc_functional_selected_cross_bin_waivers(
            merged.merged,
            covergroup="Cov",
            waivers=(
                FunctionalCoverageBinWaiver(
                    group="Cov",
                    kind="cross_bin",
                    label="cp_a x cp_b",
                    bin="cp_a.ax x cp_b.by",
                    reason="unit-test selected structural row",
                    reason_class="unit_test",
                    reviewed_by="unit test",
                    review_date="2026-06-29",
                ),
            ),
        )


def test_selected_cross_bin_waiver_accounting_rejects_duplicate_bin(
    tmp_path: Path,
) -> None:
    artifact = write_harc_functional_coverage_artifact(
        _functional_report(
            a0=1,
            a1=1,
            b0=1,
            b1=1,
            missing=("cp_a.a1 x cp_b.b1",),
        ),
        covergroups=("Cov",),
        path=tmp_path / "coverage.json",
    )
    merged = merge_harc_functional_coverage_artifacts(
        (artifact,),
        output=tmp_path / "merged.json",
        hole_report_output=tmp_path / "holes.json",
    )
    waiver = FunctionalCoverageBinWaiver(
        group="Cov",
        kind="cross_bin",
        label="cp_a x cp_b",
        bin="cp_a.a1 x cp_b.b1",
        reason="unit-test selected structural row",
        reason_class="unit_test",
        reviewed_by="unit test",
        review_date="2026-06-29",
    )

    with pytest.raises(AssertionError, match="duplicate functional coverage bin waiver"):
        assert_merged_harc_functional_selected_cross_bin_waivers(
            merged.merged,
            covergroup="Cov",
            waivers=(waiver, waiver),
        )


def test_merge_harc_functional_coverage_rejects_missing_cross_schema(
    tmp_path: Path,
) -> None:
    first = write_harc_functional_coverage_artifact(
        _functional_report(
            a0=1,
            a1=1,
            b0=1,
            b1=1,
            missing=(),
        ),
        covergroups=("Cov",),
        path=tmp_path / "seed_1.json",
    )
    second_payload = json.loads(Path(first).read_text())
    del second_payload["groups"]["Cov"]["declared_crosses"]["cp_a x cp_b"]
    second = tmp_path / "seed_2.json"
    second.write_text(json.dumps(second_payload, indent=2, sort_keys=True) + "\n")

    with pytest.raises(AssertionError, match="schema mismatch"):
        merge_harc_functional_coverage_artifacts(
            (first, second),
            output=tmp_path / "merged.json",
            hole_report_output=tmp_path / "holes.json",
        )


def test_merge_harc_functional_coverage_rejects_unknown_hit_bin(
    tmp_path: Path,
) -> None:
    first = write_harc_functional_coverage_artifact(
        _functional_report(
            a0=1,
            a1=1,
            b0=1,
            b1=1,
            missing=(),
        ),
        covergroups=("Cov",),
        path=tmp_path / "seed_1.json",
    )
    bad_payload = json.loads(Path(first).read_text())
    bad_payload["groups"]["Cov"]["declared_crosses"]["cp_a x cp_b"][
        "hit_bins"
    ].append("cp_a.bad x cp_b.bad")
    bad = tmp_path / "seed_bad.json"
    bad.write_text(json.dumps(bad_payload, indent=2, sort_keys=True) + "\n")

    with pytest.raises(AssertionError, match="outside the derived universe"):
        merge_harc_functional_coverage_artifacts(
            (first, bad),
            output=tmp_path / "merged.json",
            hole_report_output=tmp_path / "holes.json",
        )


def test_merge_harc_functional_coverage_campaigns_records_provenance(
    tmp_path: Path,
) -> None:
    c13_dir = tmp_path / "c13"
    c14_dir = tmp_path / "c14"
    c13_seed = write_harc_functional_coverage_artifact(
        _functional_report(
            a0=1,
            a1=0,
            b0=1,
            b1=0,
            missing=(
                "cp_a.a0 x cp_b.b1",
                "cp_a.a1 x cp_b.b0",
                "cp_a.a1 x cp_b.b1",
            ),
        ),
        covergroups=("Cov",),
        path=c13_dir / "seed_13" / "functional_coverage.json",
        seed=13,
        profile="c13_crv",
    )
    c14_seed = write_harc_functional_coverage_artifact(
        _functional_report(
            a0=0,
            a1=1,
            b0=0,
            b1=1,
            missing=(
                "cp_a.a0 x cp_b.b0",
                "cp_a.a0 x cp_b.b1",
                "cp_a.a1 x cp_b.b0",
            ),
        ),
        covergroups=("Cov",),
        path=c14_dir / "seed_14" / "functional_coverage.json",
        seed=14,
        profile="c14_directed",
    )
    c13 = merge_harc_functional_coverage_artifacts(
        (c13_seed,),
        output=c13_dir / "merged_functional_coverage.json",
        hole_report_output=c13_dir / "functional_hole_report.json",
    ).merged
    c14 = merge_harc_functional_coverage_artifacts(
        (c14_seed,),
        output=c14_dir / "merged_functional_coverage.json",
        hole_report_output=c14_dir / "functional_hole_report.json",
    ).merged
    c13_manifest = c13_dir / "seed_manifest.json"
    c14_manifest = c14_dir / "seed_manifest.json"
    c13_manifest.write_text(
        json.dumps([_crv_manifest_row(seed=13, profile="c13_crv")]) + "\n"
    )
    c14_manifest.write_text(
        json.dumps([_crv_manifest_row(seed=14, profile="c14_directed")]) + "\n"
    )

    merged = merge_harc_functional_coverage_campaigns(
        (
            HarcFunctionalCoverageCampaignInput(
                name="c13_crv",
                functional_coverage=c13,
                seed_manifest=c13_manifest,
            ),
            HarcFunctionalCoverageCampaignInput(
                name="c14_directed",
                functional_coverage=c14,
                seed_manifest=c14_manifest,
            ),
        ),
        output=tmp_path / "cumulative" / "merged_functional_coverage.json",
        hole_report_output=tmp_path / "cumulative" / "functional_hole_report.json",
        manifest_output=tmp_path / "cumulative" / "cumulative_manifest.json",
    )

    manifest = json.loads(merged.manifest.read_text())
    assert manifest["format"] == "harc-functional-coverage-cumulative-manifest-v1"
    assert manifest["campaigns"] == [
        {
            "name": "c13_crv",
            "functional_coverage": str(c13),
            "seed_manifest": str(c13_manifest),
            "source_artifacts": [str(c13_seed)],
        },
        {
            "name": "c14_directed",
            "functional_coverage": str(c14),
            "seed_manifest": str(c14_manifest),
            "source_artifacts": [str(c14_seed)],
        },
    ]
    assert manifest["merged_functional_coverage"] == str(merged.merged)
    assert manifest["functional_hole_report"] == str(merged.hole_report)

    payload = json.loads(merged.merged.read_text())
    group = payload["groups"]["Cov"]
    assert group["coverpoint_hit"] == 4
    assert group["coverpoint_total"] == 4
    assert group["declared_cross_hit"] == 2
    assert group["declared_cross_total"] == 4
    assert group["declared_crosses"]["cp_a x cp_b"]["hit_bins"] == [
        "cp_a.a0 x cp_b.b0",
        "cp_a.a1 x cp_b.b1",
    ]

    holes = json.loads(merged.hole_report.read_text())
    assert holes["groups"]["Cov"]["coverpoint_holes"] == []
    assert holes["groups"]["Cov"]["declared_cross_holes"] == [
        {"bin": "cp_a.a0 x cp_b.b1", "cross": "cp_a x cp_b"},
        {"bin": "cp_a.a1 x cp_b.b0", "cross": "cp_a x cp_b"},
    ]
    provenance = manifest["provenance"]["Cov"]
    assert provenance["coverpoints"]["cp_a"]["a0"][0]["source_artifact"] == str(
        c13_seed
    )
    assert provenance["coverpoints"]["cp_a"]["a1"][0]["source_artifact"] == str(
        c14_seed
    )
    assert provenance["declared_crosses"]["cp_a x cp_b"]["cp_a.a0 x cp_b.b0"][0][
        "seed_manifest_entry"
    ]["codegen"] == "default-tbir"
    assert provenance["declared_crosses"]["cp_a x cp_b"]["cp_a.a1 x cp_b.b1"][0][
        "campaign"
    ] == "c14_directed"


def test_merge_harc_functional_coverage_campaigns_rejects_duplicate_names(
    tmp_path: Path,
) -> None:
    functional = write_harc_functional_coverage_artifact(
        _functional_report(a0=1, a1=1, b0=1, b1=1, missing=()),
        covergroups=("Cov",),
        path=tmp_path / "functional.json",
        seed=1,
        profile="c13",
    )
    manifest = tmp_path / "seed_manifest.json"
    manifest.write_text(
        json.dumps([_crv_manifest_row(seed=1, profile="c13")]) + "\n"
    )
    campaign = HarcFunctionalCoverageCampaignInput(
        name="c13",
        functional_coverage=functional,
        seed_manifest=manifest,
    )

    with pytest.raises(AssertionError, match="duplicate"):
        merge_harc_functional_coverage_campaigns(
            (campaign, campaign),
            output=tmp_path / "merged.json",
            hole_report_output=tmp_path / "holes.json",
            manifest_output=tmp_path / "manifest.json",
        )


def test_merge_harc_functional_coverage_campaigns_rejects_bad_seed_manifest(
    tmp_path: Path,
) -> None:
    functional = write_harc_functional_coverage_artifact(
        _functional_report(a0=1, a1=1, b0=1, b1=1, missing=()),
        covergroups=("Cov",),
        path=tmp_path / "functional.json",
    )
    manifest = tmp_path / "seed_manifest.json"
    manifest.write_text('{"seed": 1}\n')

    with pytest.raises(
        AssertionError,
        match="seed manifest is not a non-empty list",
    ):
        merge_harc_functional_coverage_campaigns(
            (
                HarcFunctionalCoverageCampaignInput(
                    name="c13",
                    functional_coverage=functional,
                    seed_manifest=manifest,
                ),
            ),
            output=tmp_path / "merged.json",
            hole_report_output=tmp_path / "holes.json",
            manifest_output=tmp_path / "manifest.json",
        )


def test_merge_harc_functional_coverage_campaigns_rejects_non_default_tbir(
    tmp_path: Path,
) -> None:
    functional = write_harc_functional_coverage_artifact(
        _functional_report(a0=1, a1=1, b0=1, b1=1, missing=()),
        covergroups=("Cov",),
        path=tmp_path / "functional.json",
        seed=1,
        profile="c13",
    )
    manifest = tmp_path / "seed_manifest.json"
    row = _crv_manifest_row(seed=1, profile="c13")
    row["codegen"] = "v1"
    manifest.write_text(json.dumps([row]) + "\n")

    with pytest.raises(AssertionError, match="not default-TBIR"):
        merge_harc_functional_coverage_campaigns(
            (
                HarcFunctionalCoverageCampaignInput(
                    name="c13",
                    functional_coverage=functional,
                    seed_manifest=manifest,
                ),
            ),
            output=tmp_path / "merged.json",
            hole_report_output=tmp_path / "holes.json",
            manifest_output=tmp_path / "manifest.json",
        )


def test_merge_harc_functional_coverage_campaigns_rejects_unseeded_command(
    tmp_path: Path,
) -> None:
    functional = write_harc_functional_coverage_artifact(
        _functional_report(a0=1, a1=1, b0=1, b1=1, missing=()),
        covergroups=("Cov",),
        path=tmp_path / "functional.json",
        seed=1,
        profile="c13",
    )
    manifest = tmp_path / "seed_manifest.json"
    row = _crv_manifest_row(seed=1, profile="c13")
    row["command"] = [
        "/opt/harc/bin/harc",
        "sim",
        "--coverage",
        "--coverage-json",
        "seed_1/functional_coverage.jsonl",
        "test.harc",
    ]
    manifest.write_text(json.dumps([row]) + "\n")

    with pytest.raises(AssertionError, match="command seed mismatch"):
        merge_harc_functional_coverage_campaigns(
            (
                HarcFunctionalCoverageCampaignInput(
                    name="c13",
                    functional_coverage=functional,
                    seed_manifest=manifest,
                ),
            ),
            output=tmp_path / "merged.json",
            hole_report_output=tmp_path / "holes.json",
            manifest_output=tmp_path / "manifest.json",
        )


def test_run_crv_seed_campaign_exports_functional_coverage(tmp_path: Path) -> None:
    dut = tmp_path / "Example.arch"
    fake_harc = tmp_path / "fake_harc.py"
    fake_harc.write_text(
        "\n".join(
            (
                "#!/usr/bin/env python3",
                "from pathlib import Path",
                "import json",
                "import sys",
                "outdir = Path(sys.argv[sys.argv.index('--outdir') + 1])",
                "seed = int(sys.argv[sys.argv.index('--seed') + 1])",
                "dut = sys.argv[sys.argv.index('--dut') + 1]",
                "coverage_json = Path(sys.argv[sys.argv.index('--coverage-json') + 1])",
                "outdir.mkdir(parents=True, exist_ok=True)",
                "payload = '\\x01file\\x02' + dut + '\\x01line\\x021\\x01page\\x02v_line\\x01comment\\x02comb comb'",
                "(outdir / 'coverage.dat').write_text(\"# SystemC::Coverage-3\\nC '\" + payload + \"' \" + str(seed) + \"\\n\")",
                "rows = [",
                "  {'type': 'covergroup', 'group': 'Cov', 'hit': 1, 'total': 2},",
                "  {'type': 'coverpoint_bin', 'group': 'Cov', 'point': 'cp_seed', 'bin': 'one', 'hits': 1 if seed == 1 else 0},",
                "  {'type': 'coverpoint_bin', 'group': 'Cov', 'point': 'cp_seed', 'bin': 'two', 'hits': 1 if seed == 2 else 0},",
                "  {'type': 'cross', 'group': 'Cov', 'kind': 'cross', 'label': 'cp_seed', 'hit': 1, 'total': 2},",
                "  {'type': 'cross_bin', 'group': 'Cov', 'kind': 'cross', 'label': 'cp_seed', 'bin': 'cp_seed.one', 'hits': 1 if seed == 1 else 0},",
                "  {'type': 'cross_bin', 'group': 'Cov', 'kind': 'cross', 'label': 'cp_seed', 'bin': 'cp_seed.two', 'hits': 1 if seed == 2 else 0},",
                "]",
                "coverage_json.parent.mkdir(parents=True, exist_ok=True)",
                "coverage_json.write_text('\\n'.join(json.dumps(row) for row in rows) + '\\n')",
                "print('[Cov] coverage: 1/2 hit (50.0%)')",
                "print('  cp_seed (bin) [one]: ' + ('1' if seed == 1 else '0') + ' hits' + ('' if seed == 1 else ' *NOT HIT*'))",
                "print('  cp_seed (bin) [two]: ' + ('1' if seed == 2 else '0') + ' hits' + ('' if seed == 2 else ' *NOT HIT*'))",
                "print('[Cov] cross cp_seed: 1/2 hit (50.0%)')",
                "print('  cp_seed.' + ('two' if seed == 1 else 'one') + ': *NOT HIT*')",
            )
        )
        + "\n"
    )
    os.chmod(fake_harc, 0o755)

    campaign = run_crv_seed_campaign(
        config=HarcSim(
            harc_files=(tmp_path / "test.harc",),
            dut_files=(dut,),
            top="example",
            test="ExampleCrv",
            harc_bin=fake_harc,
            cwd=tmp_path,
        ),
        seeds=(1, 2),
        profile="functional",
        iterations=2,
        campaign_dir=tmp_path / "campaign",
        functional_covergroups=("Cov",),
        max_workers=2,
    )

    assert len(campaign.functional_coverage_files) == 2
    assert campaign.merged_functional_coverage is not None
    assert campaign.functional_hole_report is not None
    assert_merged_harc_functional_coverage_100(
        campaign.merged_functional_coverage,
        covergroups=("Cov",),
    )


def test_compressed_decoder_coverage_status_matches_inventory(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.md"
    status = tmp_path / "status.md"
    inventory.write_text(
        "\n".join(
            (
                "## Coverpoints and Bins",
                "",
                "### `cp_a`",
                "",
                "- `a0`",
                "- `a1`",
                "",
                "### `cp_b`",
                "",
                "- `b0`",
                "",
                "## Required Crosses",
                "",
                "- `cp_a x cp_b`",
            )
        )
        + "\n"
    )
    status.write_text(
        "\n".join(
            (
                "## Coverpoint Bin Status",
                "",
                "| Coverpoint | Bin | Status | Evidence / next action |",
                "| --- | --- | --- | --- |",
                "| `cp_a` | `a0`, `a1` | `implemented_hit` | measured |",
                "| `cp_b` | `b0` | `pending_stimulus` | add row |",
                "",
                "## Required Cross Status",
                "",
                "| Cross | Status | Evidence / next action |",
                "| --- | --- | --- |",
                "| `cp_a x cp_b` | `pending_stimulus` | add matrix |",
            )
        )
        + "\n"
    )

    parsed_inventory = compressed_decoder_coverage_inventory(inventory)
    parsed_status = compressed_decoder_coverage_status(status)

    assert parsed_inventory.coverpoint_bins["cp_a"] == ("a0", "a1")
    assert parsed_status.coverpoint_bins[("cp_b", "b0")] == "pending_stimulus"
    assert_compressed_decoder_coverage_status_complete(
        inventory_path=inventory,
        status_path=status,
    )


def test_checked_in_compressed_decoder_coverage_status_is_complete() -> None:
    root = Path(__file__).resolve().parents[1]

    assert_compressed_decoder_coverage_status_complete(
        inventory_path=root / "tests/harc/plans/ibex_compressed_decoder_full_bins.md",
        status_path=root
        / "tests/harc/plans/ibex_compressed_decoder_full_coverage_status.md",
    )


def test_compressed_decoder_coverage_status_fails_on_missing_bin(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.md"
    status = tmp_path / "status.md"
    inventory.write_text(
        "\n".join(
            (
                "## Coverpoints and Bins",
                "",
                "### `cp_a`",
                "",
                "- `a0`",
                "- `a1`",
                "",
                "## Required Crosses",
                "",
                "- `cp_a x cp_a`",
            )
        )
        + "\n"
    )
    status.write_text(
        "\n".join(
            (
                "## Coverpoint Bin Status",
                "",
                "| Coverpoint | Bin | Status | Evidence / next action |",
                "| --- | --- | --- | --- |",
                "| `cp_a` | `a0` | `implemented_hit` | measured |",
                "",
                "## Required Cross Status",
                "",
                "| Cross | Status | Evidence / next action |",
                "| --- | --- | --- |",
                "| `cp_a x cp_a` | `pending_stimulus` | add matrix |",
            )
        )
        + "\n"
    )

    with pytest.raises(AssertionError, match="missing coverage bin statuses"):
        assert_compressed_decoder_coverage_status_complete(
            inventory_path=inventory,
            status_path=status,
        )


def test_compressed_decoder_coverage_status_rejects_shorthand(tmp_path: Path) -> None:
    status = tmp_path / "status.md"
    status.write_text(
        "\n".join(
            (
                "## Coverpoint Bin Status",
                "",
                "| Coverpoint | Bin | Status | Evidence / next action |",
                "| --- | --- | --- | --- |",
                "| `cp_a` | all bins | `pending_stimulus` | add rows |",
                "",
                "## Required Cross Status",
                "",
                "| Cross | Status | Evidence / next action |",
                "| --- | --- | --- |",
                "| `cp_a x cp_a` | `pending_stimulus` | add matrix |",
            )
        )
        + "\n"
    )

    with pytest.raises(AssertionError, match="must name bins explicitly"):
        compressed_decoder_coverage_status(status)
