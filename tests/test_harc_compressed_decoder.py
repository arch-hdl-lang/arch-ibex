"""Executable closure gate: regenerate independent expectations on every run."""
from pathlib import Path
import subprocess
import json
import hashlib
import pytest
from tests.compressed_decoder_oracle import build_corpus, REFERENCE
from tests.harc_runner import (
    REPO_ROOT, harc_check, harc_sim_dut_coverage, resolve_arch_bin,
    assert_harc_functional_coverage_100, assert_arch_coverage_dat_100,
    merge_coverage_dat, resolve_harc_bin, compressed_decoder_coverage_inventory,
    harc_functional_coverage_report,
)


def test_compressed_decoder_coverage(tmp_path: Path, monkeypatch) -> None:
    arch_version = subprocess.check_output([resolve_arch_bin(), "--version"], text=True).strip()
    harc_version = subprocess.check_output([resolve_harc_bin(), "--version"], text=True).strip()
    pinned = (REPO_ROOT / ".arch-version").read_text().strip()
    assert arch_version.split()[1] == pinned, (arch_version, pinned)
    (tmp_path / "toolchain.json").write_text(json.dumps({"arch": arch_version, "harc": harc_version,
        "arch_sha256": hashlib.sha256(Path(resolve_arch_bin()).read_bytes()).hexdigest(),
        "harc_sha256": hashlib.sha256(Path(resolve_harc_bin()).read_bytes()).hexdigest()}, indent=2))
    vectors = build_corpus(tmp_path / "oracle")
    monkeypatch.setenv("IBEX_DECODER_VECTORS", str(vectors))
    files = [REPO_ROOT / f"tests/harc/{part}/ibex_compressed_decoder_{suffix}.harc"
             for part, suffix in [("lib", "vip"), ("unit", "harc_test")]]
    dut = REPO_ROOT / "src/IbexCompressedDecoder.arch"
    harc_check(harc_files=files)
    runs = []
    for test, params in [("DecoderCoverage", {}), ("DecoderZcmpDisabled", {"RV32ZC": 1})]:
        run = harc_sim_dut_coverage(
            dut_files=[dut], harc_files=files, top="ibex_compressed_decoder", test=test,
            outdir=tmp_path / test, ref_src=[REFERENCE / "compressed_decoder_reader.cpp"],
            parameters=params, seed=1, extra_args=("--arch-bin", resolve_arch_bin()),
        )
        (tmp_path / f"{test}.log").write_text(run.proc.stdout + run.proc.stderr)
        runs.extend(run.coverage_files)
        if not params:
            assert_harc_functional_coverage_100(run.proc.stdout, covergroups=["DecoderScenarios"], require_declared_crosses=False)
            assert_harc_functional_coverage_100(run.proc.stdout, covergroups=["DecoderProtocol", "DecoderStack"])
            inventory = compressed_decoder_coverage_inventory(REPO_ROOT / "tests/harc/plans/ibex_compressed_decoder_full_bins.md")
            report = harc_functional_coverage_report(run.proc.stdout)
            required = {(cp, name) for cp, names in inventory.coverpoint_bins.items() for name in names}
            # Reviewed two-state scope exclusion; spec explicitly permits no X propagation.
            required.remove(("cp_pure_pass_through_when_instr_i_1_0_is_unknown_any", "specified_behavior"))
            measured = {key: hits for bins in report.bins.values() for key, hits in bins.items()}
            assert set(measured) == required
            assert all(hits > 0 for hits in measured.values())
            crosses = {key: value for items in report.declared_crosses.values() for key, value in items.items()}
            assert set(crosses) == set(inventory.crosses)
            assert all(hit == total and total > 0 for hit, total in crosses.values())
    merged = merge_coverage_dat(runs, output=tmp_path / "merged_coverage.dat")
    assert_arch_coverage_dat_100(merged, source_prefixes=[dut])


@pytest.fixture(scope="module")
def corpus_reader(tmp_path_factory):
    out = tmp_path_factory.mktemp("decoder_reader")
    harness = out / "main.cpp"
    harness.write_text('''#include <cstdint>
extern "C" uint64_t cd_count();
extern "C" uint64_t cd_field(uint64_t,uint64_t);
extern "C" uint64_t cd_accept(uint64_t);
extern "C" uint64_t cd_finish();
int main(int argc,char**) {
  auto n=cd_count();
  if(argc>1) return cd_finish()==n ? 0:1;
  for(uint64_t i=0;i<n;++i) { for(int j=0;j<9;++j) cd_field(i,j); cd_accept(i); }
  return cd_finish()==n ? 0:1;
}
''')
    binary = out / "reader"
    subprocess.run(["c++", "-std=c++17", str(harness), str(REFERENCE / "compressed_decoder_reader.cpp"), "-o", str(binary)], check=True)
    return binary


@pytest.mark.parametrize("data", ["", "0\n", "1\n", "1\n1 1 0 1 19 1 0 0 0\nextra", "1\n1 2 0 1 19 1 0 0 0\n"])
def test_reader_rejects_bad_corpus(corpus_reader, tmp_path, monkeypatch, data):
    path = tmp_path / "bad.txt"
    path.write_text(data)
    monkeypatch.setenv("IBEX_DECODER_VECTORS", str(path))
    assert subprocess.run([str(corpus_reader)], capture_output=True).returncode != 0


def test_reader_requires_complete_consumption(corpus_reader, tmp_path, monkeypatch):
    path = tmp_path / "one.txt"
    path.write_text("1\n1 1 0 1 19 1 0 0 0\n")
    monkeypatch.setenv("IBEX_DECODER_VECTORS", str(path))
    assert subprocess.run([str(corpus_reader), "unfinished"], capture_output=True).returncode != 0
    assert subprocess.run([str(corpus_reader)], capture_output=True).returncode == 0
