"""Small pytest-oriented helpers for running HARC commands."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from itertools import product
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from typing import Iterable, Mapping, NamedTuple, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HARC_BIN = REPO_ROOT.parent / "harc-com" / "target" / "release" / "harc"
DEFAULT_ARCH_BIN = REPO_ROOT.parent / "arch-com" / "target" / "release" / "arch"

PathLike = str | os.PathLike[str]


def _as_path_args(paths: Sequence[PathLike] | None) -> list[str]:
    return [str(Path(p)) for p in (paths or ())]


def _trim(text: str, *, limit: int = 3000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    return f"{text[:head]}\n... <truncated> ...\n{text[-tail:]}"


def _format_failure(cmd: Sequence[str], proc: subprocess.CompletedProcess[str]) -> str:
    parts = [
        f"HARC command failed with exit code {proc.returncode}:",
        " ".join(cmd),
    ]
    if proc.stdout:
        parts.extend(("", "stdout:", _trim(proc.stdout)))
    if proc.stderr:
        parts.extend(("", "stderr:", _trim(proc.stderr)))
    return "\n".join(parts)


def _resolve_path(path: PathLike, *, base: PathLike = REPO_ROOT) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(base) / candidate
    return candidate.resolve(strict=False)


def _source_matches_prefixes(source: str, prefixes: tuple[Path, ...] | None) -> bool:
    if prefixes is None:
        return True

    source_path = _resolve_path(source)
    for prefix in prefixes:
        try:
            source_path.relative_to(prefix)
            return True
        except ValueError:
            pass
        if str(source).startswith(str(prefix)):
            return True
    return False


def _waiver_key(
    *,
    kind: str,
    source: str,
    line: int,
    block: int | None = None,
    branch: int | None = None,
) -> tuple[str, str, int, int | None, int | None]:
    return (kind, str(_resolve_path(source)), line, block, branch)


def _arch_waiver_key(
    *,
    source: str,
    line: int,
    page: str,
    comment: str,
) -> tuple[str, int, str, str]:
    return (str(_resolve_path(source)), line, page, comment)


def _reviewed_waivers(
    waivers: Sequence[CoverageWaiver] | None,
) -> dict[tuple[str, str, int, int | None, int | None], CoverageWaiver]:
    reviewed: dict[tuple[str, str, int, int | None, int | None], CoverageWaiver] = {}
    for waiver in waivers or ():
        if waiver.kind not in {"line", "branch"}:
            raise AssertionError(f"invalid coverage waiver kind: {waiver.kind!r}")
        if waiver.line <= 0:
            raise AssertionError(f"coverage waiver line must be positive: {waiver}")
        if not waiver.reason.strip():
            raise AssertionError(f"coverage waiver missing design reason: {waiver}")
        if not waiver.reviewed_by.strip():
            raise AssertionError(f"coverage waiver missing reviewer: {waiver}")
        if waiver.kind == "branch" and (
            waiver.block is None or waiver.branch is None
        ):
            raise AssertionError(f"branch waiver must include block and branch: {waiver}")
        if waiver.kind == "line" and (
            waiver.block is not None or waiver.branch is not None
        ):
            raise AssertionError(f"line waiver cannot include branch fields: {waiver}")
        key = _waiver_key(
            kind=waiver.kind,
            source=str(waiver.source),
            line=waiver.line,
            block=waiver.block,
            branch=waiver.branch,
        )
        if key in reviewed:
            raise AssertionError(f"duplicate coverage waiver: {waiver}")
        reviewed[key] = waiver
    return reviewed


def _reviewed_arch_waivers(
    waivers: Sequence[ArchCoverageWaiver] | None,
) -> dict[tuple[str, int, str, str], ArchCoverageWaiver]:
    reviewed: dict[tuple[str, int, str, str], ArchCoverageWaiver] = {}
    for waiver in waivers or ():
        if waiver.line <= 0:
            raise AssertionError(f"ARCH coverage waiver line must be positive: {waiver}")
        if not waiver.page.strip():
            raise AssertionError(f"ARCH coverage waiver missing page: {waiver}")
        if not waiver.comment.strip():
            raise AssertionError(f"ARCH coverage waiver missing comment: {waiver}")
        if not waiver.reason.strip():
            raise AssertionError(f"ARCH coverage waiver missing design reason: {waiver}")
        if not waiver.reviewed_by.strip():
            raise AssertionError(f"ARCH coverage waiver missing reviewer: {waiver}")
        key = _arch_waiver_key(
            source=str(waiver.source),
            line=waiver.line,
            page=waiver.page,
            comment=waiver.comment,
        )
        if key in reviewed:
            raise AssertionError(f"duplicate ARCH coverage waiver: {waiver}")
        reviewed[key] = waiver
    return reviewed


class CoverageTotals(NamedTuple):
    """LCOV coverage totals used by the HARC pytest gate."""

    line_hit: int
    line_found: int
    branch_hit: int
    branch_found: int
    source_records: int
    matched_sources: tuple[str, ...]

    @property
    def line_percent(self) -> float:
        return 100.0 if self.line_found == 0 else 100.0 * self.line_hit / self.line_found

    @property
    def branch_percent(self) -> float:
        return 100.0 if self.branch_found == 0 else 100.0 * self.branch_hit / self.branch_found


class HarcCoverageRun(NamedTuple):
    """Result of a HARC coverage simulation and the data files it produced."""

    proc: subprocess.CompletedProcess[str]
    coverage_files: tuple[Path, ...]


class CrvSeedCampaignRun(NamedTuple):
    """Artifacts from a parallel constrained-random seed campaign."""

    manifest: Path
    merged_coverage: Path
    entries: tuple[CrvSeedManifestEntry, ...]
    coverage_files: tuple[Path, ...]
    functional_coverage_files: tuple[Path, ...]
    merged_functional_coverage: Path | None
    functional_hole_report: Path | None


@dataclass(frozen=True)
class CrvSeedManifestEntry:
    """Reproducible metadata for one constrained-random HARC seed run."""

    seed: int
    profile: str
    iterations: int
    command: tuple[str, ...]
    backend: str
    codegen: str
    outdir: PathLike
    coverage_db: PathLike
    trace: PathLike | None = None
    status: str = "planned"

    def as_json_obj(self) -> dict[str, object]:
        """Return a stable JSON representation for review and reruns."""

        if self.seed < 0:
            raise AssertionError(f"CRV seed must be non-negative: {self.seed}")
        if self.iterations <= 0:
            raise AssertionError(
                f"CRV iterations must be positive: {self.iterations}"
            )
        if not self.profile.strip():
            raise AssertionError("CRV profile must be non-empty")
        if self.status not in {"planned", "passed", "failed", "excluded"}:
            raise AssertionError(f"invalid CRV seed status: {self.status!r}")
        if self.backend not in {"dut", "sv"}:
            raise AssertionError(f"invalid CRV backend: {self.backend!r}")
        if self.codegen != "default-tbir":
            raise AssertionError(
                f"CRV manifest forbids non-default codegen: {self.codegen!r}"
            )
        command = tuple(str(arg) for arg in self.command)
        if not command:
            raise AssertionError("CRV manifest command must be non-empty")
        if any(arg == "--codegen" or arg.startswith("--codegen=") for arg in command):
            raise AssertionError("CRV manifest command must not use --codegen")
        return {
            "seed": self.seed,
            "profile": self.profile,
            "iterations": self.iterations,
            "command": list(command),
            "command_string": shlex.join(command),
            "backend": self.backend,
            "codegen": self.codegen,
            "outdir": str(Path(self.outdir)),
            "coverage_db": str(Path(self.coverage_db)),
            "trace": None if self.trace is None else str(Path(self.trace)),
            "status": self.status,
        }


class HarcFunctionalCoverageTotals(NamedTuple):
    """Functional coverage totals printed by HARC covergroup reports."""

    group: str
    coverpoint_hit: int
    coverpoint_total: int
    declared_cross_hit: int
    declared_cross_waived: int
    declared_cross_total: int
    declared_crosses: int


class HarcFunctionalCoverageReport(NamedTuple):
    """Parsed HARC `covergroup.report()` bins and summaries."""

    groups: dict[str, tuple[int, int]]
    bins: dict[str, dict[tuple[str, str], int]]
    declared_crosses: dict[str, dict[str, tuple[int, int]]]


class HarcFunctionalCoverageArtifacts(NamedTuple):
    """Machine-readable merged functional coverage artifacts."""

    merged: Path
    hole_report: Path


class HarcCumulativeFunctionalCoverageArtifacts(NamedTuple):
    """Cumulative functional coverage artifacts across reviewed campaigns."""

    merged: Path
    hole_report: Path
    manifest: Path


class HarcFunctionalCoverageCampaignInput(NamedTuple):
    """Reviewed functional coverage campaign input for cumulative merge."""

    name: str
    functional_coverage: PathLike
    seed_manifest: PathLike


class CoverageInventory(NamedTuple):
    """Required functional coverage bins and crosses from a plan inventory."""

    coverpoint_bins: dict[str, tuple[str, ...]]
    crosses: tuple[str, ...]


class CoverageStatusMap(NamedTuple):
    """Implementation status for required coverage bins and crosses."""

    coverpoint_bins: dict[tuple[str, str], str]
    crosses: dict[str, str]


@dataclass(frozen=True)
class FunctionalCoverageWaiver:
    """Reviewed exclusion for unreachable HARC functional coverage bins."""

    group: str
    kind: str
    label: str
    missing: int
    reason: str
    reason_class: str
    reviewed_by: str
    review_date: str


@dataclass(frozen=True)
class FunctionalCoverageBinWaiver:
    """Reviewed exclusion for one unreachable HARC functional cross bin."""

    group: str
    kind: str
    label: str
    bin: str
    reason: str
    reason_class: str
    reviewed_by: str
    review_date: str


@dataclass(frozen=True)
class CoverageWaiver:
    """Reviewed LCOV exclusion for an unreachable line or branch."""

    kind: str
    source: PathLike
    line: int
    reason: str
    reviewed_by: str
    block: int | None = None
    branch: int | None = None


@dataclass(frozen=True)
class ArchCoverageWaiver:
    """Reviewed ARCH coverage.dat exclusion keyed by exact source record."""

    source: PathLike
    line: int
    page: str
    comment: str
    reason: str
    reviewed_by: str


_COVERAGE_STATUS_VALUES = {
    "implemented_hit",
    "implemented_unhit",
    "pending_stimulus",
    "pending_waiver_review",
    "diagnostic_only",
}


def resolve_harc_bin() -> str:
    """Resolve the HARC executable from HARC_BIN, sibling checkout, or PATH."""

    env = os.environ.get("HARC_BIN")
    if env:
        path = Path(env).expanduser()
        if path.is_file():
            return str(path)
        raise AssertionError(f"HARC_BIN points to a missing file: {path}")

    if DEFAULT_HARC_BIN.is_file():
        return str(DEFAULT_HARC_BIN)

    which = shutil.which("harc")
    if which:
        return which

    raise AssertionError(
        "HARC binary not found; set HARC_BIN or build "
        f"{DEFAULT_HARC_BIN}"
    )


def resolve_arch_bin() -> str:
    """Resolve the ARCH executable from ARCH_BIN, sibling checkout, or PATH."""

    env = os.environ.get("ARCH_BIN")
    if env:
        path = Path(env).expanduser()
        if path.is_file():
            return str(path)
        raise AssertionError(f"ARCH_BIN points to a missing file: {path}")

    if DEFAULT_ARCH_BIN.is_file():
        return str(DEFAULT_ARCH_BIN)

    which = shutil.which("arch")
    if which:
        return which

    raise AssertionError(
        "ARCH binary not found; set ARCH_BIN or build "
        f"{DEFAULT_ARCH_BIN}"
    )


def resolve_verilator_coverage_bin() -> str:
    """Resolve the `verilator_coverage` executable used for code coverage."""

    which = shutil.which("verilator_coverage")
    if which:
        return which
    raise AssertionError("verilator_coverage not found on PATH")


@dataclass(frozen=True)
class HarcCheck:
    """Inputs for `harc check <files...>`."""

    harc_files: Sequence[PathLike]
    cwd: PathLike = REPO_ROOT
    harc_bin: PathLike | None = None


@dataclass(frozen=True)
class HarcSim:
    """Inputs for `harc sim` using exactly one DUT backend.

    `parameters={"W": 8}` lowers to HARC-native `--param W=8`.
    HARC then maps that to Verilator `-GW=8` for `--sv` and to
    `arch sim --param W=8` for `--dut`.
    """

    harc_files: Sequence[PathLike]
    sv_files: Sequence[PathLike] = field(default_factory=tuple)
    dut_files: Sequence[PathLike] = field(default_factory=tuple)
    top: str | None = None
    test: str | None = None
    outdir: PathLike | None = None
    ref_src: Sequence[PathLike] = field(default_factory=tuple)
    verilator_args: Sequence[str] = field(default_factory=tuple)
    parameters: Mapping[str, object] = field(default_factory=dict)
    seed: int | None = None
    cwd: PathLike = REPO_ROOT
    harc_bin: PathLike | None = None
    extra_args: Sequence[str] = field(default_factory=tuple)


def run_harc(
    args: Sequence[str],
    *,
    cwd: PathLike = REPO_ROOT,
    harc_bin: PathLike | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `harc` with captured output, failing pytest-style on nonzero exit."""

    binary = str(harc_bin) if harc_bin is not None else resolve_harc_bin()
    cmd = [binary, *args]
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=merged_env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(_format_failure(cmd, proc))
    return proc


def run_verilator_coverage(
    args: Sequence[str],
    *,
    cwd: PathLike = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    """Run `verilator_coverage` and fail pytest-style on nonzero exit."""

    binary = resolve_verilator_coverage_bin()
    cmd = [binary, *args]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(_format_failure(cmd, proc))
    return proc


def merge_coverage_dat(
    coverage_files: Sequence[PathLike],
    *,
    output: PathLike,
    cwd: PathLike = REPO_ROOT,
    arch_bin: PathLike | None = None,
) -> Path:
    """Merge ARCH/Verilator-compatible `coverage.dat` files."""

    inputs = _as_path_args(coverage_files)
    if not inputs:
        raise AssertionError("no coverage.dat files provided for merge")
    out = Path(output)
    binary = str(arch_bin) if arch_bin is not None else resolve_arch_bin()
    cmd = [binary, "coverage", "merge", "--out", str(out), *inputs]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise AssertionError(
            "\n".join(
                (
                    "HARC command failed before execution:",
                    " ".join(cmd),
                    "",
                    str(exc),
                )
            )
        ) from exc
    if proc.returncode != 0:
        raise AssertionError(_format_failure(cmd, proc))
    return out


def write_lcov_info(
    coverage_files: Sequence[PathLike],
    *,
    output: PathLike,
    cwd: PathLike = REPO_ROOT,
) -> Path:
    """Write LCOV `.info` from one or more Verilator coverage data files."""

    inputs = _as_path_args(coverage_files)
    if not inputs:
        raise AssertionError("no coverage.dat files provided for LCOV export")
    out = Path(output)
    run_verilator_coverage(["--write-info", str(out), *inputs], cwd=cwd)
    return out


def coverage_files_from_outdir(outdir: PathLike) -> tuple[Path, ...]:
    """Find coverage data emitted by `harc sim --coverage` under `outdir`."""

    root = Path(outdir)
    files = tuple(sorted(root.rglob("coverage.dat")))
    if not files:
        raise AssertionError(f"no coverage.dat produced under {root}")
    return files


def lcov_totals(
    info_file: PathLike,
    *,
    source_prefixes: Iterable[PathLike] | None = None,
    waivers: Sequence[CoverageWaiver] | None = None,
) -> CoverageTotals:
    """Parse LCOV line/branch totals, optionally restricted to source paths."""

    prefixes = None
    if source_prefixes is not None:
        prefixes = tuple(_resolve_path(p) for p in source_prefixes)

    reviewed_waivers = _reviewed_waivers(waivers)
    used_waivers: set[tuple[str, str, int, int | None, int | None]] = set()

    line_hit = line_found = branch_hit = branch_found = 0
    source_records = 0
    matched_sources: set[str] = set()
    current_source = ""
    active = False

    for raw in Path(info_file).read_text().splitlines():
        if raw.startswith("SF:"):
            source_records += 1
            current_source = raw[3:]
            active = _source_matches_prefixes(current_source, prefixes)
            if active:
                matched_sources.add(current_source)
            continue
        if not active:
            continue
        if raw.startswith("DA:"):
            _, rest = raw.split(":", 1)
            fields = rest.split(",")
            if len(fields) >= 2:
                line = int(fields[0])
                count = int(fields[1])
                key = _waiver_key(kind="line", source=current_source, line=line)
                if count == 0 and key in reviewed_waivers:
                    used_waivers.add(key)
                    continue
                line_found += 1
                if count > 0:
                    line_hit += 1
        elif raw.startswith("BRDA:"):
            _, rest = raw.split(":", 1)
            fields = rest.split(",")
            if len(fields) >= 4:
                line = int(fields[0])
                block = int(fields[1])
                branch = int(fields[2])
                taken = fields[3]
                hit = taken != "-" and int(taken) > 0
                key = _waiver_key(
                    kind="branch",
                    source=current_source,
                    line=line,
                    block=block,
                    branch=branch,
                )
                if not hit and key in reviewed_waivers:
                    used_waivers.add(key)
                    continue
                branch_found += 1
                if hit:
                    branch_hit += 1

    unused_waivers = sorted(set(reviewed_waivers) - used_waivers)
    if unused_waivers:
        formatted = ", ".join(str(key) for key in unused_waivers)
        raise AssertionError(f"coverage waiver did not match an uncovered item: {formatted}")

    return CoverageTotals(
        line_hit,
        line_found,
        branch_hit,
        branch_found,
        source_records,
        tuple(sorted(matched_sources)),
    )


def assert_lcov_coverage_100(
    info_file: PathLike,
    *,
    source_prefixes: Iterable[PathLike],
    waivers: Sequence[CoverageWaiver] | None = None,
    require_branch_data: bool = True,
) -> CoverageTotals:
    """Require 100% LCOV line and branch coverage after any exclusions."""

    source_prefixes = tuple(source_prefixes)
    if not source_prefixes:
        raise AssertionError("coverage gate requires at least one DUT source prefix")
    totals = lcov_totals(
        info_file,
        source_prefixes=source_prefixes,
        waivers=waivers,
    )
    missing = []
    if totals.source_records == 0:
        missing.append("LCOV file has no source records")
    if not totals.matched_sources:
        missing.append("LCOV source filter matched no files")
    if totals.line_found == 0:
        missing.append("LCOV gate found no line coverage records")
    if require_branch_data and totals.branch_found == 0:
        missing.append("LCOV gate found no branch coverage records")
    if totals.line_hit != totals.line_found:
        missing.append(
            f"line coverage {totals.line_hit}/{totals.line_found} "
            f"({totals.line_percent:.2f}%)"
        )
    if totals.branch_hit != totals.branch_found:
        missing.append(
            f"branch coverage {totals.branch_hit}/{totals.branch_found} "
            f"({totals.branch_percent:.2f}%)"
        )
    if missing:
        raise AssertionError("coverage gate failed: " + ", ".join(missing))
    return totals


def _parse_systemc_coverage_record(raw: str) -> tuple[str, int] | None:
    """Parse one SystemC::Coverage `C 'key/value...' count` record."""

    if not raw.startswith("C '"):
        return None
    try:
        payload, count_text = raw[3:].rsplit("' ", 1)
    except ValueError:
        return None
    try:
        count = int(count_text)
    except ValueError:
        return None
    return payload, count


def _systemc_coverage_fields(payload: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in payload.split("\x01"):
        if not part:
            continue
        if "\x02" not in part:
            continue
        key, value = part.split("\x02", 1)
        fields[key] = value
    return fields


_ARCH_GENERATED_THREAD_COUNTER_TOGGLE_RE = re.compile(
    r"^toggle toggle _t\d+_cnt$"
)


def _is_arch_generated_untoggleable_record(page: str, comment: str) -> bool:
    """Identify generated ARCH helper toggles with no source stimulus path."""

    return page == "v_toggle" and bool(
        _ARCH_GENERATED_THREAD_COUNTER_TOGGLE_RE.fullmatch(comment)
    )


def arch_coverage_dat_totals(
    coverage_file: PathLike,
    *,
    source_prefixes: Iterable[PathLike],
    waivers: Sequence[ArchCoverageWaiver] | None = None,
) -> CoverageTotals:
    """Parse ARCH simulator SystemC coverage records from `coverage.dat`.

    ARCH's native simulator writes Verilator-style `SystemC::Coverage-3`
    records, but `verilator_coverage --write-info` currently drops them for
    ARCH source files. This parser gates the raw records directly so ARCH DUTs
    still fail closed on missing or unhit source coverage.
    """

    prefixes = tuple(_resolve_path(p) for p in source_prefixes)
    if not prefixes:
        raise AssertionError("coverage gate requires at least one DUT source prefix")

    reviewed_waivers = _reviewed_arch_waivers(waivers)
    used_waivers: set[tuple[str, int, str, str]] = set()

    line_hit = line_found = branch_hit = branch_found = 0
    source_records = 0
    matched_sources: set[str] = set()

    for raw in Path(coverage_file).read_text(errors="replace").splitlines():
        parsed = _parse_systemc_coverage_record(raw)
        if parsed is None:
            continue
        payload, count = parsed
        fields = _systemc_coverage_fields(payload)
        source = fields.get("file") or fields.get("f", "")
        page = fields.get("page") or fields.get("p", "")
        comment = fields.get("comment") or fields.get("c", "")
        if not source:
            continue
        source_records += 1
        if not _source_matches_prefixes(source, prefixes):
            continue
        if _is_arch_generated_untoggleable_record(page, comment):
            continue
        line = int(fields.get("line") or fields.get("l") or "0")
        key = _arch_waiver_key(
            source=source,
            line=line,
            page=page,
            comment=comment,
        )
        if count == 0 and key in reviewed_waivers:
            used_waivers.add(key)
            continue
        matched_sources.add(source)

        if page == "v_line":
            line_found += 1
            if count > 0:
                line_hit += 1
        elif page in {"v_branch", "v_user", "v_expr", "v_toggle"}:
            branch_found += 1
            if count > 0:
                branch_hit += 1

    unused_waivers = sorted(set(reviewed_waivers) - used_waivers)
    if unused_waivers:
        formatted = ", ".join(str(key) for key in unused_waivers)
        raise AssertionError(
            f"ARCH coverage waiver did not match an uncovered item: {formatted}"
        )

    return CoverageTotals(
        line_hit,
        line_found,
        branch_hit,
        branch_found,
        source_records,
        tuple(sorted(matched_sources)),
    )


def assert_arch_coverage_dat_100(
    coverage_file: PathLike,
    *,
    source_prefixes: Iterable[PathLike],
    require_branch_data: bool = True,
    waivers: Sequence[ArchCoverageWaiver] | None = None,
) -> CoverageTotals:
    """Require 100% ARCH native simulator source/control/code coverage."""

    totals = arch_coverage_dat_totals(
        coverage_file,
        source_prefixes=source_prefixes,
        waivers=waivers,
    )
    missing = []
    if totals.source_records == 0:
        missing.append("coverage.dat has no source records")
    if not totals.matched_sources:
        missing.append("coverage source filter matched no files")
    if totals.line_found == 0:
        missing.append("coverage gate found no line/block records")
    if require_branch_data and totals.branch_found == 0:
        missing.append("coverage gate found no branch/control records")
    if totals.line_hit != totals.line_found:
        missing.append(
            f"line coverage {totals.line_hit}/{totals.line_found} "
            f"({totals.line_percent:.2f}%)"
        )
    if totals.branch_hit != totals.branch_found:
        missing.append(
            f"branch/control coverage {totals.branch_hit}/{totals.branch_found} "
            f"({totals.branch_percent:.2f}%)"
        )
    if missing:
        raise AssertionError("coverage gate failed: " + ", ".join(missing))
    return totals


def assert_arch_coverage_dat_at_least(
    coverage_file: PathLike,
    *,
    source_prefixes: Iterable[PathLike],
    min_line_percent: float,
    min_branch_percent: float,
    require_branch_data: bool = True,
    waivers: Sequence[ArchCoverageWaiver] | None = None,
) -> CoverageTotals:
    """Require minimum ARCH native simulator source/control/code coverage."""

    totals = arch_coverage_dat_totals(
        coverage_file,
        source_prefixes=source_prefixes,
        waivers=waivers,
    )
    missing = []
    if totals.source_records == 0:
        missing.append("coverage.dat has no source records")
    if not totals.matched_sources:
        missing.append("coverage source filter matched no files")
    if totals.line_found == 0:
        missing.append("coverage gate found no line/block records")
    if require_branch_data and totals.branch_found == 0:
        missing.append("coverage gate found no branch/control records")
    if totals.line_percent < min_line_percent:
        missing.append(
            f"line coverage {totals.line_hit}/{totals.line_found} "
            f"({totals.line_percent:.2f}%) < {min_line_percent:.2f}%"
        )
    if totals.branch_percent < min_branch_percent:
        missing.append(
            f"branch/control coverage {totals.branch_hit}/{totals.branch_found} "
            f"({totals.branch_percent:.2f}%) < {min_branch_percent:.2f}%"
        )
    if missing:
        raise AssertionError("coverage gate failed: " + ", ".join(missing))
    return totals


_HARC_COVERGROUP_RE = re.compile(
    r"^\[(?P<group>[^\]]+)\] coverage: "
    r"(?P<hit>\d+)/(?P<total>\d+) hit "
)
_HARC_CROSS_RE = re.compile(
    r"^\[(?P<group>[^\]]+)\] (?P<kind>cross|auto_cross) "
    r"(?P<label>.*): (?P<hit>\d+)/(?P<total>\d+) hit "
)
_HARC_BIN_RE = re.compile(
    r"^  (?P<point>[^ ]+) \(bin\) \[(?P<bin>[^\]]+)\]: "
    r"(?P<hits>\d+) hits"
)
_HARC_MISSING_CROSS_BIN_RE = re.compile(r"^  (?P<label>.+): \*NOT HIT\*$")
_HARC_MORE_MISSING_RE = re.compile(
    r"^  \.\.\. (?P<count>\d+) more missing (?P<kind>cross|auto-cross) bins$"
)
_BACKTICK_RE = re.compile(r"`([^`]+)`")


def _markdown_table_cells(raw: str) -> list[str] | None:
    line = raw.strip()
    if not line.startswith("|") or not line.endswith("|"):
        return None
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    if not cells or all(set(cell) <= {"-", " "} for cell in cells):
        return None
    return cells


def compressed_decoder_coverage_inventory(path: PathLike) -> CoverageInventory:
    """Parse the compressed-decoder full-bin inventory Markdown file."""

    coverpoint_bins: dict[str, list[str]] = {}
    crosses: list[str] = []
    current_coverpoint: str | None = None
    in_coverpoints = False
    in_crosses = False

    for raw in Path(path).read_text().splitlines():
        if raw.startswith("## "):
            in_coverpoints = raw == "## Coverpoints and Bins"
            in_crosses = raw == "## Required Crosses"
            current_coverpoint = None
            continue
        if in_coverpoints and raw.startswith("### "):
            names = _BACKTICK_RE.findall(raw)
            if len(names) != 1:
                raise AssertionError(f"malformed coverpoint heading: {raw}")
            current_coverpoint = names[0]
            coverpoint_bins.setdefault(current_coverpoint, [])
            continue
        if in_coverpoints and raw.startswith("- ") and current_coverpoint:
            names = _BACKTICK_RE.findall(raw)
            if len(names) != 1:
                raise AssertionError(f"malformed coverage bin row: {raw}")
            coverpoint_bins[current_coverpoint].append(names[0])
            continue
        if in_crosses and raw.startswith("- "):
            names = _BACKTICK_RE.findall(raw)
            if len(names) != 1:
                raise AssertionError(f"malformed required cross row: {raw}")
            crosses.append(names[0])

    if not coverpoint_bins:
        raise AssertionError(f"no coverpoint bins found in {path}")
    if not crosses:
        raise AssertionError(f"no required crosses found in {path}")

    return CoverageInventory(
        {point: tuple(bins) for point, bins in sorted(coverpoint_bins.items())},
        tuple(crosses),
    )


def compressed_decoder_coverage_status(path: PathLike) -> CoverageStatusMap:
    """Parse the compressed-decoder C3 status-map Markdown table."""

    coverpoint_bins: dict[tuple[str, str], str] = {}
    crosses: dict[str, str] = {}
    section: str | None = None

    for raw in Path(path).read_text().splitlines():
        if raw.startswith("## "):
            if raw == "## Coverpoint Bin Status":
                section = "coverpoints"
            elif raw == "## Required Cross Status":
                section = "crosses"
            else:
                section = None
            continue
        cells = _markdown_table_cells(raw)
        if cells is None or len(cells) < 3:
            continue
        first = cells[0]
        second = cells[1]
        status = cells[1].strip("`") if section == "crosses" else cells[2].strip("`")
        if first in {"Coverpoint", "Cross", "Source"}:
            continue
        if status not in _COVERAGE_STATUS_VALUES:
            continue

        names = _BACKTICK_RE.findall(first)
        if len(names) != 1:
            continue
        name = names[0]
        if section == "crosses":
            if name in crosses:
                raise AssertionError(f"duplicate coverage cross status: {name}")
            crosses[name] = status
            continue
        if section != "coverpoints":
            continue

        bins = _BACKTICK_RE.findall(second)
        if not bins:
            raise AssertionError(
                f"coverage status row must name bins explicitly: {raw}"
            )
        for bin_name in bins:
            key = (name, bin_name)
            if key in coverpoint_bins:
                raise AssertionError(
                    f"duplicate coverage bin status: {name}.{bin_name}"
                )
            coverpoint_bins[key] = status

    if not coverpoint_bins:
        raise AssertionError(f"no coverpoint bin statuses found in {path}")
    if not crosses:
        raise AssertionError(f"no required cross statuses found in {path}")

    return CoverageStatusMap(coverpoint_bins, crosses)


def assert_compressed_decoder_coverage_status_complete(
    *,
    inventory_path: PathLike,
    status_path: PathLike,
) -> None:
    """Require the C3 status map to mention every full-bin inventory item."""

    inventory = compressed_decoder_coverage_inventory(inventory_path)
    status = compressed_decoder_coverage_status(status_path)

    required_bins = {
        (point, bin_name)
        for point, bins in inventory.coverpoint_bins.items()
        for bin_name in bins
    }
    status_bins = set(status.coverpoint_bins)
    required_crosses = set(inventory.crosses)
    status_crosses = set(status.crosses)

    missing_bins = sorted(required_bins - status_bins)
    missing_crosses = sorted(required_crosses - status_crosses)
    unknown_bins = sorted(status_bins - required_bins)
    unknown_crosses = sorted(status_crosses - required_crosses)

    messages = []
    if missing_bins:
        messages.append(f"missing coverage bin statuses: {missing_bins}")
    if missing_crosses:
        messages.append(f"missing coverage cross statuses: {missing_crosses}")
    if unknown_bins:
        messages.append(f"unknown coverage bin statuses: {unknown_bins}")
    if unknown_crosses:
        messages.append(f"unknown coverage cross statuses: {unknown_crosses}")
    if messages:
        raise AssertionError("; ".join(messages))


def harc_functional_coverage_report(output: str) -> HarcFunctionalCoverageReport:
    """Parse HARC `cov.report()` covergroup summaries, bins, and crosses."""

    groups: dict[str, tuple[int, int]] = {}
    bins: dict[str, dict[tuple[str, str], int]] = {}
    declared_crosses: dict[str, dict[str, tuple[int, int]]] = {}
    current_group: str | None = None

    for raw in output.splitlines():
        if match := _HARC_COVERGROUP_RE.match(raw):
            current_group = match.group("group")
            groups[current_group] = (
                int(match.group("hit")),
                int(match.group("total")),
            )
            bins.setdefault(current_group, {})
            declared_crosses.setdefault(current_group, {})
            continue

        if match := _HARC_BIN_RE.match(raw):
            if current_group is None:
                continue
            bins.setdefault(current_group, {})[
                (match.group("point"), match.group("bin"))
            ] = int(match.group("hits"))
            continue

        if match := _HARC_CROSS_RE.match(raw):
            current_group = match.group("group")
            if match.group("kind") != "cross":
                continue
            declared_crosses.setdefault(current_group, {})[match.group("label")] = (
                int(match.group("hit")),
                int(match.group("total")),
            )

    return HarcFunctionalCoverageReport(groups, bins, declared_crosses)


def _cross_universe(
    *,
    group: str,
    label: str,
    coverpoints: Mapping[str, Mapping[str, int]],
) -> tuple[str, ...]:
    points = tuple(part.strip() for part in label.split(" x "))
    if not points or any(not point for point in points):
        raise AssertionError(f"{group}: malformed coverage cross label {label!r}")
    missing_points = [point for point in points if point not in coverpoints]
    if missing_points:
        raise AssertionError(
            f"{group}: coverage cross {label!r} references unknown "
            f"coverpoints {missing_points}"
        )
    return tuple(
        " x ".join(f"{point}.{bin_name}" for point, bin_name in zip(points, bins))
        for bins in product(*(tuple(coverpoints[point]) for point in points))
    )


def harc_functional_coverage_artifact(
    output: str,
    *,
    covergroups: Iterable[str],
    seed: int | None = None,
    profile: str | None = None,
) -> dict[str, object]:
    """Return a non-lossy functional coverage artifact from HARC stdout.

    The current shipped HARC report prints coverpoint bin counts and declared
    cross summaries plus missing cross-bin labels. This helper converts that
    report to data only when it can prove the missing-bin list is complete.
    """

    requested = tuple(covergroups)
    if not requested:
        raise AssertionError("functional coverage export requires covergroups")
    requested_set = set(requested)

    groups: dict[str, dict[str, object]] = {}
    current_group: str | None = None
    current_cross: tuple[str, str] | None = None

    for raw in output.splitlines():
        if match := _HARC_COVERGROUP_RE.match(raw):
            current_group = match.group("group")
            current_cross = None
            if current_group not in requested_set:
                continue
            if current_group in groups:
                raise AssertionError(
                    f"duplicate coverage group report: {current_group}"
                )
            groups[current_group] = {
                "coverpoint_hit": int(match.group("hit")),
                "coverpoint_total": int(match.group("total")),
                "coverpoints": {},
                "declared_crosses": {},
            }
            continue

        if match := _HARC_BIN_RE.match(raw):
            current_cross = None
            if current_group not in requested_set or current_group is None:
                continue
            group_data = groups[current_group]
            coverpoints = group_data["coverpoints"]
            assert isinstance(coverpoints, dict)
            point = match.group("point")
            bin_name = match.group("bin")
            point_bins = coverpoints.setdefault(point, {})
            assert isinstance(point_bins, dict)
            if bin_name in point_bins:
                raise AssertionError(
                    f"{current_group}: duplicate coverage bin "
                    f"{point}.{bin_name}"
                )
            point_bins[bin_name] = int(match.group("hits"))
            continue

        if match := _HARC_CROSS_RE.match(raw):
            group = match.group("group")
            current_group = group
            current_cross = None
            if group not in requested_set:
                continue
            if group not in groups:
                raise AssertionError(f"{group}: cross appeared before group summary")
            if match.group("kind") != "cross":
                continue
            label = match.group("label")
            group_data = groups[group]
            declared_crosses = group_data["declared_crosses"]
            assert isinstance(declared_crosses, dict)
            if label in declared_crosses:
                raise AssertionError(f"{group}: duplicate coverage cross {label!r}")
            declared_crosses[label] = {
                "hit": int(match.group("hit")),
                "total": int(match.group("total")),
                "missing_bins": [],
                "truncated_missing": 0,
            }
            current_cross = (group, label)
            continue

        if match := _HARC_MISSING_CROSS_BIN_RE.match(raw):
            if current_cross is None:
                continue
            group, label = current_cross
            if group not in requested_set:
                continue
            cross = groups[group]["declared_crosses"][label]  # type: ignore[index]
            missing_bins = cross["missing_bins"]
            assert isinstance(missing_bins, list)
            missing = match.group("label")
            if missing in missing_bins:
                raise AssertionError(
                    f"{group}: duplicate missing cross bin {label!r}: {missing!r}"
                )
            missing_bins.append(missing)
            continue

        if match := _HARC_MORE_MISSING_RE.match(raw):
            if current_cross is None:
                continue
            group, label = current_cross
            if group not in requested_set:
                continue
            cross = groups[group]["declared_crosses"][label]  # type: ignore[index]
            cross["truncated_missing"] = int(match.group("count"))

    missing_groups = [group for group in requested if group not in groups]
    if missing_groups:
        raise AssertionError(f"missing functional coverage groups: {missing_groups}")

    for group, group_data in groups.items():
        coverpoints = group_data["coverpoints"]
        declared_crosses = group_data["declared_crosses"]
        assert isinstance(coverpoints, dict)
        assert isinstance(declared_crosses, dict)
        coverpoint_hit = sum(
            1
            for point_bins in coverpoints.values()
            for hits in point_bins.values()
            if hits > 0
        )
        coverpoint_total = sum(len(point_bins) for point_bins in coverpoints.values())
        if group_data["coverpoint_hit"] != coverpoint_hit:
            raise AssertionError(
                f"{group}: coverpoint hit summary "
                f"{group_data['coverpoint_hit']} does not match bins "
                f"{coverpoint_hit}"
            )
        if group_data["coverpoint_total"] != coverpoint_total:
            raise AssertionError(
                f"{group}: coverpoint total summary "
                f"{group_data['coverpoint_total']} does not match bins "
                f"{coverpoint_total}"
            )

        for label, cross in declared_crosses.items():
            assert isinstance(cross, dict)
            if cross["truncated_missing"]:
                raise AssertionError(
                    f"{group}: cross {label!r} report is truncated by "
                    f"{cross['truncated_missing']} missing bins"
                )
            universe = _cross_universe(
                group=group,
                label=label,
                coverpoints=coverpoints,  # type: ignore[arg-type]
            )
            missing_bins = tuple(cross["missing_bins"])
            unknown_missing = sorted(set(missing_bins) - set(universe))
            if unknown_missing:
                raise AssertionError(
                    f"{group}: cross {label!r} has unknown missing bins "
                    f"{unknown_missing}"
                )
            if cross["total"] != len(universe):
                raise AssertionError(
                    f"{group}: cross {label!r} total {cross['total']} does not "
                    f"match derived universe {len(universe)}"
                )
            if len(missing_bins) != cross["total"] - cross["hit"]:
                raise AssertionError(
                    f"{group}: cross {label!r} missing-bin detail is lossy: "
                    f"{len(missing_bins)} labels for {cross['total'] - cross['hit']} "
                    "unhit bins"
                )
            cross["universe"] = list(universe)
            cross["hit_bins"] = sorted(set(universe) - set(missing_bins))
            cross["missing_bins"] = sorted(missing_bins)
            del cross["truncated_missing"]

    return {
        "format": "harc-functional-coverage-v1",
        "seed": seed,
        "profile": profile,
        "groups": groups,
    }


def _jsonl_nonnegative_int(
    row: Mapping[str, object],
    field: str,
    *,
    jsonl: Path,
    lineno: int,
) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AssertionError(
            f"{jsonl}: coverage JSONL line {lineno} has invalid {field!r}: "
            f"{value!r}"
        )
    return value


def harc_functional_coverage_artifact_from_jsonl(
    path: PathLike,
    *,
    covergroups: Iterable[str],
    seed: int | None = None,
    profile: str | None = None,
) -> dict[str, object]:
    """Return a non-lossy functional coverage artifact from HARC JSONL export."""

    requested = tuple(covergroups)
    if not requested:
        raise AssertionError("functional coverage export requires covergroups")
    requested_set = set(requested)

    groups: dict[str, dict[str, object]] = {}
    jsonl = Path(path)
    for lineno, raw in enumerate(jsonl.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"{jsonl}: invalid HARC functional coverage JSONL line {lineno}"
            ) from exc
        if not isinstance(row, dict):
            raise AssertionError(
                f"{jsonl}: coverage JSONL line {lineno} is not an object"
            )

        group = row.get("group")
        if not isinstance(group, str) or group not in requested_set:
            continue
        row_type = row.get("type")

        if row_type == "covergroup":
            if group in groups:
                raise AssertionError(f"duplicate coverage group report: {group}")
            groups[group] = {
                "coverpoint_hit": _jsonl_nonnegative_int(
                    row,
                    "hit",
                    jsonl=jsonl,
                    lineno=lineno,
                ),
                "coverpoint_total": _jsonl_nonnegative_int(
                    row,
                    "total",
                    jsonl=jsonl,
                    lineno=lineno,
                ),
                "coverpoints": {},
                "declared_crosses": {},
            }
            continue

        if group not in groups:
            raise AssertionError(
                f"{group}: coverage JSONL row appeared before group summary"
            )
        group_data = groups[group]

        if row_type == "coverpoint_bin":
            point = row.get("point")
            bin_name = row.get("bin")
            if not isinstance(point, str) or not isinstance(bin_name, str):
                raise AssertionError(
                    f"{group}: malformed coverpoint bin JSONL line {lineno}"
                )
            coverpoints = group_data["coverpoints"]
            assert isinstance(coverpoints, dict)
            point_bins = coverpoints.setdefault(point, {})
            assert isinstance(point_bins, dict)
            if bin_name in point_bins:
                raise AssertionError(
                    f"{group}: duplicate coverage bin {point}.{bin_name}"
                )
            point_bins[bin_name] = _jsonl_nonnegative_int(
                row,
                "hits",
                jsonl=jsonl,
                lineno=lineno,
            )
            continue

        if row_type == "cross":
            if row.get("kind") != "cross":
                continue
            label = row.get("label")
            if not isinstance(label, str):
                raise AssertionError(f"{group}: malformed cross JSONL line {lineno}")
            declared_crosses = group_data["declared_crosses"]
            assert isinstance(declared_crosses, dict)
            if label in declared_crosses:
                raise AssertionError(f"{group}: duplicate coverage cross {label!r}")
            declared_crosses[label] = {
                "hit": _jsonl_nonnegative_int(
                    row,
                    "hit",
                    jsonl=jsonl,
                    lineno=lineno,
                ),
                "total": _jsonl_nonnegative_int(
                    row,
                    "total",
                    jsonl=jsonl,
                    lineno=lineno,
                ),
                "universe": [],
                "hit_bins": [],
                "missing_bins": [],
                "bin_hits": {},
            }
            continue

        if row_type == "cross_bin":
            if row.get("kind") != "cross":
                continue
            label = row.get("label")
            bin_label = row.get("bin")
            if not isinstance(label, str) or not isinstance(bin_label, str):
                raise AssertionError(
                    f"{group}: malformed cross-bin JSONL line {lineno}"
                )
            declared_crosses = group_data["declared_crosses"]
            assert isinstance(declared_crosses, dict)
            if label not in declared_crosses:
                raise AssertionError(
                    f"{group}: cross-bin appeared before cross {label!r}"
                )
            cross = declared_crosses[label]
            assert isinstance(cross, dict)
            universe = cross["universe"]
            bin_hits = cross["bin_hits"]
            assert isinstance(universe, list)
            assert isinstance(bin_hits, dict)
            if bin_label in bin_hits:
                raise AssertionError(
                    f"{group}: duplicate cross bin {label!r}: {bin_label!r}"
                )
            hits = _jsonl_nonnegative_int(
                row,
                "hits",
                jsonl=jsonl,
                lineno=lineno,
            )
            universe.append(bin_label)
            bin_hits[bin_label] = hits
            continue

    missing_groups = [group for group in requested if group not in groups]
    if missing_groups:
        raise AssertionError(f"missing functional coverage groups: {missing_groups}")

    for group, group_data in groups.items():
        coverpoints = group_data["coverpoints"]
        declared_crosses = group_data["declared_crosses"]
        assert isinstance(coverpoints, dict)
        assert isinstance(declared_crosses, dict)
        coverpoint_hit = sum(
            1
            for point_bins in coverpoints.values()
            for hits in point_bins.values()
            if int(hits) > 0
        )
        coverpoint_total = sum(len(point_bins) for point_bins in coverpoints.values())
        if group_data["coverpoint_hit"] != coverpoint_hit:
            raise AssertionError(
                f"{group}: coverpoint hit summary "
                f"{group_data['coverpoint_hit']} does not match bins "
                f"{coverpoint_hit}"
            )
        if group_data["coverpoint_total"] != coverpoint_total:
            raise AssertionError(
                f"{group}: coverpoint total summary "
                f"{group_data['coverpoint_total']} does not match bins "
                f"{coverpoint_total}"
            )

        for label, cross in declared_crosses.items():
            assert isinstance(cross, dict)
            universe = cross["universe"]
            bin_hits = cross["bin_hits"]
            assert isinstance(universe, list)
            assert isinstance(bin_hits, dict)
            if len(universe) != len(set(universe)):
                raise AssertionError(f"{group}: duplicate bins in cross {label!r}")
            hit_bins = sorted(bin_label for bin_label, hits in bin_hits.items() if hits > 0)
            missing_bins = sorted(
                bin_label for bin_label, hits in bin_hits.items() if hits == 0
            )
            if int(cross["total"]) != len(universe):
                raise AssertionError(
                    f"{group}: cross {label!r} total {cross['total']} does not "
                    f"match JSONL bins {len(universe)}"
                )
            if int(cross["hit"]) != len(hit_bins):
                raise AssertionError(
                    f"{group}: cross {label!r} hit summary {cross['hit']} "
                    f"does not match JSONL bins {len(hit_bins)}"
                )
            cross["hit_bins"] = hit_bins
            cross["missing_bins"] = missing_bins

    return {
        "format": "harc-functional-coverage-v1",
        "seed": seed,
        "profile": profile,
        "groups": groups,
    }


def write_harc_functional_coverage_artifact(
    output: str,
    *,
    covergroups: Iterable[str],
    path: PathLike,
    seed: int | None = None,
    profile: str | None = None,
) -> Path:
    """Write one per-seed HARC functional coverage JSON artifact."""

    artifact = harc_functional_coverage_artifact(
        output,
        covergroups=covergroups,
        seed=seed,
        profile=profile,
    )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    return out


def write_harc_functional_coverage_artifact_from_jsonl(
    jsonl_path: PathLike,
    *,
    covergroups: Iterable[str],
    path: PathLike,
    seed: int | None = None,
    profile: str | None = None,
) -> Path:
    """Write one per-seed HARC functional coverage JSON artifact from JSONL."""

    artifact = harc_functional_coverage_artifact_from_jsonl(
        jsonl_path,
        covergroups=covergroups,
        seed=seed,
        profile=profile,
    )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    return out


def _load_harc_functional_artifact(path: PathLike) -> dict[str, object]:
    artifact = json.loads(Path(path).read_text())
    if artifact.get("format") not in {
        "harc-functional-coverage-v1",
        "harc-functional-coverage-merged-v1",
    }:
        raise AssertionError(f"unknown HARC functional coverage artifact: {path}")
    if not isinstance(artifact.get("groups"), dict):
        raise AssertionError(f"HARC functional coverage artifact has no groups: {path}")
    return artifact


def merge_harc_functional_coverage_artifacts(
    inputs: Sequence[PathLike],
    *,
    output: PathLike,
    hole_report_output: PathLike,
) -> HarcFunctionalCoverageArtifacts:
    """Merge non-lossy HARC functional coverage JSON artifacts."""

    paths = tuple(Path(path) for path in inputs)
    if not paths:
        raise AssertionError("no HARC functional coverage artifacts provided")

    merged_groups: dict[str, dict[str, object]] = {}
    expected_groups: tuple[str, ...] | None = None
    expected_group_schema: dict[
        str, tuple[tuple[tuple[str, tuple[str, ...]], ...], tuple[str, ...]]
    ] = {}
    for path in paths:
        artifact = _load_harc_functional_artifact(path)
        groups = artifact["groups"]
        assert isinstance(groups, dict)
        group_names = tuple(sorted(groups))
        if expected_groups is None:
            expected_groups = group_names
        elif expected_groups != group_names:
            raise AssertionError(
                f"functional coverage group schema mismatch in {path}"
            )
        for group, group_data in groups.items():
            assert isinstance(group_data, dict)
            coverpoints = group_data["coverpoints"]
            declared_crosses = group_data["declared_crosses"]
            assert isinstance(coverpoints, dict)
            assert isinstance(declared_crosses, dict)
            group_schema = (
                tuple(
                    sorted(
                        (point, tuple(sorted(point_bins)))
                        for point, point_bins in coverpoints.items()
                        if isinstance(point_bins, dict)
                    )
                ),
                tuple(sorted(declared_crosses)),
            )
            expected = expected_group_schema.setdefault(group, group_schema)
            if expected != group_schema:
                raise AssertionError(
                    f"{group}: functional coverage schema mismatch in {path}"
                )
            merged = merged_groups.setdefault(
                group,
                {
                    "coverpoints": {},
                    "declared_crosses": {},
                },
            )
            merged_coverpoints = merged["coverpoints"]
            merged_crosses = merged["declared_crosses"]
            assert isinstance(merged_coverpoints, dict)
            assert isinstance(merged_crosses, dict)

            for point, point_bins in coverpoints.items():
                assert isinstance(point_bins, dict)
                merged_bins = merged_coverpoints.setdefault(point, {})
                assert isinstance(merged_bins, dict)
                if set(merged_bins) and set(merged_bins) != set(point_bins):
                    raise AssertionError(
                        f"{group}: coverpoint {point} bin schema mismatch in {path}"
                    )
                for bin_name, hits in point_bins.items():
                    merged_bins[bin_name] = int(merged_bins.get(bin_name, 0)) + int(hits)

            for label, cross in declared_crosses.items():
                assert isinstance(cross, dict)
                universe = tuple(cross["universe"])
                hit_bins = set(cross["hit_bins"])
                unknown_hit_bins = sorted(hit_bins - set(universe))
                if unknown_hit_bins:
                    raise AssertionError(
                        f"{group}: cross {label!r} has hit bins outside the "
                        f"derived universe in {path}: {unknown_hit_bins}"
                    )
                merged_cross = merged_crosses.setdefault(
                    label,
                    {
                        "total": int(cross["total"]),
                        "universe": list(universe),
                        "hit_bins": set(),
                    },
                )
                assert isinstance(merged_cross, dict)
                if tuple(merged_cross["universe"]) != universe:
                    raise AssertionError(
                        f"{group}: cross {label!r} bin schema mismatch in {path}"
                    )
                merged_cross["hit_bins"].update(hit_bins)  # type: ignore[union-attr]

    hole_groups: dict[str, dict[str, object]] = {}
    for group, group_data in merged_groups.items():
        coverpoints = group_data["coverpoints"]
        declared_crosses = group_data["declared_crosses"]
        assert isinstance(coverpoints, dict)
        assert isinstance(declared_crosses, dict)
        coverpoint_total = 0
        coverpoint_hit = 0
        coverpoint_holes = []
        for point, point_bins in coverpoints.items():
            assert isinstance(point_bins, dict)
            for bin_name, hits in point_bins.items():
                coverpoint_total += 1
                if int(hits) > 0:
                    coverpoint_hit += 1
                else:
                    coverpoint_holes.append({"point": point, "bin": bin_name})

        cross_total = 0
        cross_hit = 0
        cross_holes = []
        for label, cross in declared_crosses.items():
            assert isinstance(cross, dict)
            hit_bins = sorted(cross["hit_bins"])
            universe = tuple(cross["universe"])
            missing_bins = sorted(set(universe) - set(hit_bins))
            cross["hit_bins"] = hit_bins
            cross["missing_bins"] = missing_bins
            cross["hit"] = len(hit_bins)
            cross["total"] = len(universe)
            cross_total += len(universe)
            cross_hit += len(hit_bins)
            for bin_label in missing_bins:
                cross_holes.append({"cross": label, "bin": bin_label})

        group_data["coverpoint_hit"] = coverpoint_hit
        group_data["coverpoint_total"] = coverpoint_total
        group_data["declared_cross_hit"] = cross_hit
        group_data["declared_cross_total"] = cross_total
        hole_groups[group] = {
            "coverpoint_holes": coverpoint_holes,
            "declared_cross_holes": cross_holes,
        }

    merged_payload = {
        "format": "harc-functional-coverage-merged-v1",
        "inputs": [str(path) for path in paths],
        "groups": merged_groups,
    }
    holes_payload = {
        "format": "harc-functional-coverage-hole-report-v1",
        "merged": str(Path(output)),
        "groups": hole_groups,
    }
    merged_out = Path(output)
    holes_out = Path(hole_report_output)
    merged_out.parent.mkdir(parents=True, exist_ok=True)
    holes_out.parent.mkdir(parents=True, exist_ok=True)
    merged_out.write_text(json.dumps(merged_payload, indent=2, sort_keys=True) + "\n")
    holes_out.write_text(json.dumps(holes_payload, indent=2, sort_keys=True) + "\n")
    return HarcFunctionalCoverageArtifacts(merged=merged_out, hole_report=holes_out)


def _load_harc_functional_json(path: PathLike) -> dict[str, object]:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise AssertionError(f"HARC functional coverage JSON is not an object: {path}")
    return payload


def _campaign_functional_source_artifacts(path: PathLike) -> tuple[Path, ...]:
    artifact_path = Path(path)
    payload = _load_harc_functional_json(artifact_path)
    artifact_format = payload.get("format")
    if artifact_format == "harc-functional-coverage-v1":
        return (artifact_path,)
    if artifact_format != "harc-functional-coverage-merged-v1":
        raise AssertionError(f"unknown HARC functional coverage artifact: {path}")

    inputs = payload.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise AssertionError(f"merged HARC functional coverage has no inputs: {path}")

    source_paths: list[Path] = []
    for raw in inputs:
        if not isinstance(raw, str) or not raw.strip():
            raise AssertionError(
                f"merged HARC functional coverage input is invalid: {path}"
            )
        source = Path(raw)
        if not source.is_file() and not source.is_absolute():
            candidate = artifact_path.parent / source
            if candidate.is_file():
                source = candidate
        if not source.is_file():
            raise AssertionError(f"HARC functional coverage input missing: {source}")
        source_paths.append(source)
    return tuple(source_paths)


def _validate_crv_seed_manifest(
    path: PathLike,
) -> dict[tuple[str, int], dict[str, object]]:
    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text())
    if not isinstance(payload, list) or not payload:
        raise AssertionError(f"HARC seed manifest is not a non-empty list: {path}")

    rows: dict[tuple[str, int], dict[str, object]] = {}
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise AssertionError(
                f"HARC seed manifest row {index} is not an object: {path}"
            )

        profile = row.get("profile")
        seed = row.get("seed")
        if not isinstance(profile, str) or not profile.strip():
            raise AssertionError(
                f"HARC seed manifest row {index} has invalid profile: {path}"
            )
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise AssertionError(
                f"HARC seed manifest row {index} has invalid seed: {path}"
            )
        if row.get("codegen") != "default-tbir":
            raise AssertionError(
                f"HARC seed manifest row {index} is not default-TBIR: {path}"
            )
        if row.get("status") != "passed":
            raise AssertionError(
                f"HARC seed manifest row {index} did not pass: {path}"
            )
        if row.get("backend") not in {"dut", "sv"}:
            raise AssertionError(
                f"HARC seed manifest row {index} has invalid backend: {path}"
            )
        iterations = row.get("iterations")
        if (
            isinstance(iterations, bool)
            or not isinstance(iterations, int)
            or iterations <= 0
        ):
            raise AssertionError(
                f"HARC seed manifest row {index} has invalid iterations: {path}"
            )

        command = row.get("command")
        if not isinstance(command, list) or not command:
            raise AssertionError(
                f"HARC seed manifest row {index} has invalid command: {path}"
            )
        if any(not isinstance(arg, str) or not arg for arg in command):
            raise AssertionError(
                f"HARC seed manifest row {index} has non-string command arg: {path}"
            )
        if "sim" not in command:
            raise AssertionError(
                f"HARC seed manifest row {index} is not a HARC sim command: {path}"
            )
        if "--coverage" not in command:
            raise AssertionError(
                f"HARC seed manifest row {index} is not a coverage run: {path}"
            )
        if "--coverage-json" not in command and not any(
            arg.startswith("--coverage-json=") for arg in command
        ):
            raise AssertionError(
                f"HARC seed manifest row {index} has no coverage JSON export: {path}"
            )
        if "--emit-only" in command:
            raise AssertionError(
                f"HARC seed manifest row {index} is emit-only, not a run: {path}"
            )
        seed_arg = str(seed)
        seed_matches = any(arg == f"--seed={seed_arg}" for arg in command)
        for arg_index, arg in enumerate(command[:-1]):
            if arg == "--seed" and command[arg_index + 1] == seed_arg:
                seed_matches = True
        if not seed_matches:
            raise AssertionError(
                f"HARC seed manifest row {index} command seed mismatch: {path}"
            )
        if any(
            arg == "--codegen" or arg.startswith("--codegen=")
            for arg in command
        ):
            raise AssertionError(
                f"HARC seed manifest row {index} uses forbidden --codegen: {path}"
            )

        key = (profile, seed)
        if key in rows:
            raise AssertionError(f"duplicate HARC seed manifest row {key}: {path}")
        rows[key] = row
    return rows


def _functional_artifact_identity(
    artifact: Mapping[str, object],
    *,
    path: PathLike,
) -> tuple[str, int]:
    profile = artifact.get("profile")
    seed = artifact.get("seed")
    if not isinstance(profile, str) or not profile.strip():
        raise AssertionError(
            f"HARC functional coverage artifact has invalid profile: {path}"
        )
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise AssertionError(
            f"HARC functional coverage artifact has invalid seed: {path}"
        )
    return profile, seed


def merge_harc_functional_coverage_campaigns(
    campaigns: Sequence[HarcFunctionalCoverageCampaignInput],
    *,
    output: PathLike,
    hole_report_output: PathLike,
    manifest_output: PathLike,
) -> HarcCumulativeFunctionalCoverageArtifacts:
    """Merge reviewed HARC functional coverage campaigns with provenance."""

    campaign_inputs = tuple(campaigns)
    if not campaign_inputs:
        raise AssertionError("no HARC functional coverage campaigns provided")

    seen_names: set[str] = set()
    seen_functional: set[Path] = set()
    seen_manifests: set[Path] = set()
    seen_source_artifacts: set[Path] = set()
    manifest_rows: list[dict[str, object]] = []
    coverage_paths: list[Path] = []
    provenance_groups: dict[str, dict[str, object]] = {}
    for campaign in campaign_inputs:
        name = campaign.name.strip()
        if not name:
            raise AssertionError("HARC functional coverage campaign name is empty")
        if name in seen_names:
            raise AssertionError(f"duplicate HARC functional coverage campaign: {name}")
        seen_names.add(name)

        functional_coverage = Path(campaign.functional_coverage)
        seed_manifest = Path(campaign.seed_manifest)
        if not functional_coverage.is_file():
            raise AssertionError(
                f"HARC functional coverage artifact missing: {functional_coverage}"
            )
        if not seed_manifest.is_file():
            raise AssertionError(f"HARC seed manifest missing: {seed_manifest}")
        functional_key = functional_coverage.resolve()
        manifest_key = seed_manifest.resolve()
        if functional_key in seen_functional:
            raise AssertionError(
                f"duplicate HARC functional coverage artifact: {functional_coverage}"
            )
        if manifest_key in seen_manifests:
            raise AssertionError(f"duplicate HARC seed manifest: {seed_manifest}")
        seen_functional.add(functional_key)
        seen_manifests.add(manifest_key)

        seed_rows = _validate_crv_seed_manifest(seed_manifest)
        source_paths = _campaign_functional_source_artifacts(functional_coverage)

        for source_path in source_paths:
            source_key = source_path.resolve()
            if source_key in seen_source_artifacts:
                raise AssertionError(
                    f"duplicate HARC functional coverage source artifact: {source_path}"
                )
            seen_source_artifacts.add(source_key)
            artifact = _load_harc_functional_artifact(source_path)
            if artifact.get("format") != "harc-functional-coverage-v1":
                raise AssertionError(
                    "HARC campaign provenance requires raw per-seed functional "
                    f"coverage artifacts: {source_path}"
                )
            profile, seed = _functional_artifact_identity(
                artifact,
                path=source_path,
            )
            manifest_row = seed_rows.get((profile, seed))
            if manifest_row is None:
                raise AssertionError(
                    f"{source_path}: no matching seed manifest row for "
                    f"{profile}/{seed}"
                )
            coverage_paths.append(source_path)
            source_ref = {
                "campaign": name,
                "campaign_functional_coverage": str(functional_coverage),
                "seed_manifest": str(seed_manifest),
                "source_artifact": str(source_path),
                "profile": profile,
                "seed": seed,
                "seed_manifest_entry": manifest_row,
            }
            groups = artifact["groups"]
            assert isinstance(groups, dict)
            for group, group_data in groups.items():
                assert isinstance(group_data, dict)
                group_provenance = provenance_groups.setdefault(
                    group,
                    {
                        "coverpoints": {},
                        "declared_crosses": {},
                    },
                )
                coverpoints = group_data["coverpoints"]
                declared_crosses = group_data["declared_crosses"]
                assert isinstance(coverpoints, dict)
                assert isinstance(declared_crosses, dict)
                prov_coverpoints = group_provenance["coverpoints"]
                prov_crosses = group_provenance["declared_crosses"]
                assert isinstance(prov_coverpoints, dict)
                assert isinstance(prov_crosses, dict)

                for point, point_bins in coverpoints.items():
                    assert isinstance(point_bins, dict)
                    point_provenance = prov_coverpoints.setdefault(point, {})
                    assert isinstance(point_provenance, dict)
                    for bin_name, hits in point_bins.items():
                        if int(hits) <= 0:
                            continue
                        bin_provenance = point_provenance.setdefault(bin_name, [])
                        assert isinstance(bin_provenance, list)
                        bin_provenance.append(source_ref)

                for label, cross in declared_crosses.items():
                    assert isinstance(cross, dict)
                    cross_provenance = prov_crosses.setdefault(label, {})
                    assert isinstance(cross_provenance, dict)
                    hit_bins = cross["hit_bins"]
                    assert isinstance(hit_bins, list)
                    for bin_label in hit_bins:
                        bin_provenance = cross_provenance.setdefault(bin_label, [])
                        assert isinstance(bin_provenance, list)
                        bin_provenance.append(source_ref)
        manifest_rows.append(
            {
                "name": name,
                "functional_coverage": str(functional_coverage),
                "seed_manifest": str(seed_manifest),
                "source_artifacts": [
                    str(source_path) for source_path in source_paths
                ],
            }
        )

    merged = merge_harc_functional_coverage_artifacts(
        coverage_paths,
        output=output,
        hole_report_output=hole_report_output,
    )
    manifest_payload = {
        "format": "harc-functional-coverage-cumulative-manifest-v1",
        "campaigns": manifest_rows,
        "merged_functional_coverage": str(merged.merged),
        "functional_hole_report": str(merged.hole_report),
        "provenance": provenance_groups,
    }
    manifest_out = Path(manifest_output)
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n"
    )
    return HarcCumulativeFunctionalCoverageArtifacts(
        merged=merged.merged,
        hole_report=merged.hole_report,
        manifest=manifest_out,
    )


def assert_merged_harc_functional_coverage_100(
    artifact_path: PathLike,
    *,
    covergroups: Iterable[str],
    waivers: Sequence[FunctionalCoverageWaiver] | None = None,
) -> tuple[HarcFunctionalCoverageTotals, ...]:
    """Require 100% merged HARC functional coverpoint and declared-cross coverage."""

    artifact = json.loads(Path(artifact_path).read_text())
    if artifact.get("format") != "harc-functional-coverage-merged-v1":
        raise AssertionError(f"unknown merged functional coverage artifact: {artifact_path}")
    groups = artifact.get("groups")
    if not isinstance(groups, dict):
        raise AssertionError(f"merged functional coverage artifact has no groups: {artifact_path}")

    requested = tuple(covergroups)
    if not requested:
        raise AssertionError("merged functional coverage gate requires covergroups")
    requested_set = set(requested)
    reviewed_waivers: dict[tuple[str, str, str], FunctionalCoverageWaiver] = {}
    for waiver in waivers or ():
        if waiver.group not in requested_set:
            raise AssertionError(
                f"functional coverage waiver names unknown group: {waiver}"
            )
        if waiver.kind != "cross":
            raise AssertionError(
                f"unsupported functional coverage waiver kind: {waiver.kind!r}"
            )
        if waiver.missing <= 0 or not waiver.reason.strip():
            raise AssertionError(f"incomplete functional coverage waiver: {waiver}")
        if not waiver.reason_class.strip() or not waiver.reviewed_by.strip():
            raise AssertionError(f"incomplete functional coverage waiver: {waiver}")
        if not waiver.review_date.strip():
            raise AssertionError(f"incomplete functional coverage waiver: {waiver}")
        key = (waiver.group, waiver.kind, waiver.label)
        if key in reviewed_waivers:
            raise AssertionError(f"duplicate functional coverage waiver: {waiver}")
        reviewed_waivers[key] = waiver

    missing = []
    used_waivers: set[tuple[str, str, str]] = set()
    totals: list[HarcFunctionalCoverageTotals] = []
    for group in requested:
        group_data = groups.get(group)
        if not isinstance(group_data, dict):
            missing.append(f"{group}: no merged covergroup data")
            continue
        cp_hit = int(group_data.get("coverpoint_hit", 0))
        cp_total = int(group_data.get("coverpoint_total", 0))
        cross_hit = int(group_data.get("declared_cross_hit", 0))
        cross_total = int(group_data.get("declared_cross_total", 0))
        cross_waived = 0
        declared_crosses = group_data.get("declared_crosses", {})
        if not isinstance(declared_crosses, dict):
            missing.append(f"{group}: no declared cross data")
            declared_crosses = {}
        for label, cross in declared_crosses.items():
            if not isinstance(cross, dict):
                continue
            miss_count = len(cross.get("missing_bins", ()))
            waiver = reviewed_waivers.get((group, "cross", label))
            if waiver is not None:
                used_waivers.add((group, "cross", label))
                if waiver.missing != miss_count:
                    missing.append(
                        f"{group}: waiver for {label!r} accounts for "
                        f"{waiver.missing} missing bins, observed {miss_count}"
                    )
                cross_waived += waiver.missing
        totals.append(
            HarcFunctionalCoverageTotals(
                group=group,
                coverpoint_hit=cp_hit,
                coverpoint_total=cp_total,
                declared_cross_hit=cross_hit,
                declared_cross_waived=cross_waived,
                declared_cross_total=cross_total,
                declared_crosses=len(declared_crosses),
            )
        )

    unused_waivers = sorted(set(reviewed_waivers) - used_waivers)
    if unused_waivers:
        missing.append(f"unused functional coverage waivers: {unused_waivers}")
    for total in totals:
        if total.coverpoint_hit != total.coverpoint_total:
            missing.append(
                f"{total.group}: coverpoints "
                f"{total.coverpoint_hit}/{total.coverpoint_total}"
            )
        if total.declared_crosses == 0:
            missing.append(f"{total.group}: no declared crosses reported")
        if (
            total.declared_cross_hit + total.declared_cross_waived
            != total.declared_cross_total
        ):
            missing.append(
                f"{total.group}: declared crosses hit+waived "
                f"{total.declared_cross_hit}+{total.declared_cross_waived}/"
                f"{total.declared_cross_total}"
            )
    if missing:
        raise AssertionError(
            "merged functional coverage gate failed: " + ", ".join(missing)
        )
    return tuple(totals)


def assert_merged_harc_functional_selected_cross_waivers(
    artifact_path: PathLike,
    *,
    covergroup: str,
    waivers: Sequence[FunctionalCoverageWaiver],
) -> HarcFunctionalCoverageTotals:
    """Validate selected whole-cross waivers without claiming full covergroup closure."""

    artifact = json.loads(Path(artifact_path).read_text())
    if artifact.get("format") != "harc-functional-coverage-merged-v1":
        raise AssertionError(f"unknown merged functional coverage artifact: {artifact_path}")
    groups = artifact.get("groups")
    if not isinstance(groups, dict):
        raise AssertionError(f"merged functional coverage artifact has no groups: {artifact_path}")
    group_data = groups.get(covergroup)
    if not isinstance(group_data, dict):
        raise AssertionError(f"merged functional coverage artifact missing {covergroup}")
    declared_crosses = group_data.get("declared_crosses")
    if not isinstance(declared_crosses, dict):
        raise AssertionError(f"{covergroup}: no declared cross data")

    if not waivers:
        raise AssertionError("selected functional coverage waiver gate requires waivers")

    reviewed_waivers: dict[tuple[str, str, str], FunctionalCoverageWaiver] = {}
    for waiver in waivers:
        if waiver.group != covergroup:
            raise AssertionError(
                f"selected functional coverage waiver names unknown group: {waiver}"
            )
        if waiver.kind != "cross":
            raise AssertionError(
                f"unsupported functional coverage waiver kind: {waiver.kind!r}"
            )
        if waiver.missing <= 0:
            raise AssertionError(
                f"functional coverage waiver missing count must be positive: {waiver}"
            )
        if not waiver.reason.strip():
            raise AssertionError(
                f"functional coverage waiver missing design reason: {waiver}"
            )
        if not waiver.reason_class.strip():
            raise AssertionError(
                f"functional coverage waiver missing reason class: {waiver}"
            )
        if not waiver.reviewed_by.strip():
            raise AssertionError(
                f"functional coverage waiver missing reviewer: {waiver}"
            )
        if not waiver.review_date.strip():
            raise AssertionError(
                f"functional coverage waiver missing review date: {waiver}"
            )
        key = (waiver.group, waiver.kind, waiver.label)
        if key in reviewed_waivers:
            raise AssertionError(f"duplicate functional coverage waiver: {waiver}")
        reviewed_waivers[key] = waiver

    cross_hit = cross_total = cross_waived = 0
    for waiver in waivers:
        cross = declared_crosses.get(waiver.label)
        if not isinstance(cross, dict):
            raise AssertionError(
                f"{covergroup}: waiver for {waiver.label!r} names unknown cross"
            )
        missing_bins = cross.get("missing_bins", ())
        if not isinstance(missing_bins, list):
            raise AssertionError(
                f"{covergroup}: cross {waiver.label!r} has invalid missing bins"
            )
        observed_missing = len(missing_bins)
        if waiver.missing != observed_missing:
            raise AssertionError(
                f"{covergroup}: waiver for {waiver.label!r} accounts for "
                f"{waiver.missing} missing bins, observed {observed_missing}"
            )
        hit = int(cross.get("hit", 0))
        total = int(cross.get("total", 0))
        if hit + waiver.missing != total:
            raise AssertionError(
                f"{covergroup}: waiver for {waiver.label!r} leaves selected "
                f"cross at {hit}+{waiver.missing}/{total}"
            )
        cross_hit += hit
        cross_total += total
        cross_waived += waiver.missing

    return HarcFunctionalCoverageTotals(
        group=covergroup,
        coverpoint_hit=int(group_data.get("coverpoint_hit", 0)),
        coverpoint_total=int(group_data.get("coverpoint_total", 0)),
        declared_cross_hit=cross_hit,
        declared_cross_waived=cross_waived,
        declared_cross_total=cross_total,
        declared_crosses=len(waivers),
    )


def assert_merged_harc_functional_selected_cross_bin_waivers(
    artifact_path: PathLike,
    *,
    covergroup: str,
    waivers: Sequence[FunctionalCoverageBinWaiver],
) -> HarcFunctionalCoverageTotals:
    """Validate selected cross-bin waivers without claiming full covergroup closure."""

    artifact = json.loads(Path(artifact_path).read_text())
    if artifact.get("format") != "harc-functional-coverage-merged-v1":
        raise AssertionError(f"unknown merged functional coverage artifact: {artifact_path}")
    groups = artifact.get("groups")
    if not isinstance(groups, dict):
        raise AssertionError(f"merged functional coverage artifact has no groups: {artifact_path}")
    group_data = groups.get(covergroup)
    if not isinstance(group_data, dict):
        raise AssertionError(f"merged functional coverage artifact missing {covergroup}")
    declared_crosses = group_data.get("declared_crosses")
    if not isinstance(declared_crosses, dict):
        raise AssertionError(f"{covergroup}: no declared cross data")

    if not waivers:
        raise AssertionError("selected functional coverage bin waiver gate requires waivers")

    reviewed_waivers: dict[tuple[str, str, str, str], FunctionalCoverageBinWaiver] = {}
    for waiver in waivers:
        if waiver.group != covergroup:
            raise AssertionError(
                f"selected functional coverage bin waiver names unknown group: {waiver}"
            )
        if waiver.kind != "cross_bin":
            raise AssertionError(
                f"unsupported functional coverage bin waiver kind: {waiver.kind!r}"
            )
        if not waiver.label.strip() or not waiver.bin.strip():
            raise AssertionError(f"incomplete functional coverage bin waiver: {waiver}")
        if not waiver.reason.strip():
            raise AssertionError(
                f"functional coverage bin waiver missing design reason: {waiver}"
            )
        if not waiver.reason_class.strip():
            raise AssertionError(
                f"functional coverage bin waiver missing reason class: {waiver}"
            )
        if not waiver.reviewed_by.strip():
            raise AssertionError(
                f"functional coverage bin waiver missing reviewer: {waiver}"
            )
        if not waiver.review_date.strip():
            raise AssertionError(
                f"functional coverage bin waiver missing review date: {waiver}"
            )
        key = (waiver.group, waiver.kind, waiver.label, waiver.bin)
        if key in reviewed_waivers:
            raise AssertionError(f"duplicate functional coverage bin waiver: {waiver}")
        reviewed_waivers[key] = waiver

    selected_crosses: dict[str, tuple[int, int]] = {}
    cross_waived = 0
    for waiver in waivers:
        cross = declared_crosses.get(waiver.label)
        if not isinstance(cross, dict):
            raise AssertionError(
                f"{covergroup}: waiver for {waiver.label!r} names unknown cross"
            )
        missing_bins = cross.get("missing_bins", ())
        hit_bins = cross.get("hit_bins", ())
        universe = cross.get("universe", ())
        if not isinstance(missing_bins, list):
            raise AssertionError(
                f"{covergroup}: cross {waiver.label!r} has invalid missing bins"
            )
        if not isinstance(hit_bins, list):
            raise AssertionError(
                f"{covergroup}: cross {waiver.label!r} has invalid hit bins"
            )
        if not isinstance(universe, list):
            raise AssertionError(
                f"{covergroup}: cross {waiver.label!r} has invalid universe"
            )
        if waiver.bin not in universe:
            raise AssertionError(
                f"{covergroup}: waiver for {waiver.label!r} names unknown bin "
                f"{waiver.bin!r}"
            )
        if waiver.bin in hit_bins or waiver.bin not in missing_bins:
            raise AssertionError(
                f"{covergroup}: waiver for {waiver.label!r} bin "
                f"{waiver.bin!r} is not currently missing"
            )
        hit = int(cross.get("hit", 0))
        total = int(cross.get("total", 0))
        selected_crosses.setdefault(waiver.label, (hit, total))
        cross_waived += 1

    cross_hit = sum(hit for hit, _ in selected_crosses.values())
    cross_total = sum(total for _, total in selected_crosses.values())
    return HarcFunctionalCoverageTotals(
        group=covergroup,
        coverpoint_hit=int(group_data.get("coverpoint_hit", 0)),
        coverpoint_total=int(group_data.get("coverpoint_total", 0)),
        declared_cross_hit=cross_hit,
        declared_cross_waived=cross_waived,
        declared_cross_total=cross_total,
        declared_crosses=len(selected_crosses),
    )


def harc_functional_coverage_totals(
    output: str,
    *,
    covergroups: Iterable[str],
) -> tuple[HarcFunctionalCoverageTotals, ...]:
    """Parse HARC `cov.report()` summaries for reviewed covergroups.

    Declared crosses are parsed separately from auto-crosses. Auto-crosses are
    useful diagnostics, but full-verification gates should fail on reviewed,
    user-declared coverage intent.
    """

    requested = tuple(covergroups)
    if not requested:
        raise AssertionError("functional coverage gate requires covergroups")
    requested_set = set(requested)

    coverpoint_hits: dict[str, tuple[int, int]] = {}
    declared_cross_hits: dict[str, list[tuple[int, int, str]]] = {
        group: [] for group in requested
    }

    for raw in output.splitlines():
        if match := _HARC_COVERGROUP_RE.match(raw):
            group = match.group("group")
            if group in requested_set:
                coverpoint_hits[group] = (
                    int(match.group("hit")),
                    int(match.group("total")),
                )
            continue

        if match := _HARC_CROSS_RE.match(raw):
            if match.group("kind") != "cross":
                continue
            group = match.group("group")
            if group in requested_set:
                declared_cross_hits[group].append(
                    (
                        int(match.group("hit")),
                        int(match.group("total")),
                        match.group("label"),
                    )
                )

    totals = []
    missing = []
    for group in requested:
        if group not in coverpoint_hits:
            missing.append(f"{group}: no covergroup summary")
            continue
        cp_hit, cp_total = coverpoint_hits[group]
        crosses = declared_cross_hits[group]
        totals.append(
            HarcFunctionalCoverageTotals(
                group=group,
                coverpoint_hit=cp_hit,
                coverpoint_total=cp_total,
                declared_cross_hit=sum(hit for hit, _, _ in crosses),
                declared_cross_waived=0,
                declared_cross_total=sum(total for _, total, _ in crosses),
                declared_crosses=len(crosses),
            )
        )

    if missing:
        raise AssertionError(
            "functional coverage gate failed: " + ", ".join(missing)
        )
    return tuple(totals)


def assert_harc_functional_coverage_100(
    output: str,
    *,
    covergroups: Iterable[str],
    require_declared_crosses: bool = True,
    waivers: Sequence[FunctionalCoverageWaiver] | None = None,
) -> tuple[HarcFunctionalCoverageTotals, ...]:
    """Require 100% HARC functional coverpoint and declared-cross coverage."""

    requested = tuple(covergroups)
    if not requested:
        raise AssertionError("functional coverage gate requires covergroups")
    requested_set = set(requested)
    reviewed_waivers: dict[tuple[str, str, str], FunctionalCoverageWaiver] = {}
    for waiver in waivers or ():
        if waiver.group not in requested_set:
            raise AssertionError(
                f"functional coverage waiver names unknown group: {waiver}"
            )
        if waiver.kind != "cross":
            raise AssertionError(
                f"unsupported functional coverage waiver kind: {waiver.kind!r}"
            )
        if waiver.missing <= 0:
            raise AssertionError(
                f"functional coverage waiver missing count must be positive: {waiver}"
            )
        if not waiver.reason.strip():
            raise AssertionError(
                f"functional coverage waiver missing design reason: {waiver}"
            )
        if not waiver.reason_class.strip():
            raise AssertionError(
                f"functional coverage waiver missing reason class: {waiver}"
            )
        if not waiver.reviewed_by.strip():
            raise AssertionError(
                f"functional coverage waiver missing reviewer: {waiver}"
            )
        if not waiver.review_date.strip():
            raise AssertionError(
                f"functional coverage waiver missing review date: {waiver}"
            )
        key = (waiver.group, waiver.kind, waiver.label)
        if key in reviewed_waivers:
            raise AssertionError(f"duplicate functional coverage waiver: {waiver}")
        reviewed_waivers[key] = waiver

    coverpoint_hits: dict[str, tuple[int, int]] = {}
    declared_cross_hits: dict[str, list[tuple[int, int, str]]] = {
        group: [] for group in requested
    }

    for raw in output.splitlines():
        if match := _HARC_COVERGROUP_RE.match(raw):
            group = match.group("group")
            if group in requested_set:
                coverpoint_hits[group] = (
                    int(match.group("hit")),
                    int(match.group("total")),
                )
            continue
        if match := _HARC_CROSS_RE.match(raw):
            if match.group("kind") != "cross":
                continue
            group = match.group("group")
            if group in requested_set:
                declared_cross_hits[group].append(
                    (
                        int(match.group("hit")),
                        int(match.group("total")),
                        match.group("label"),
                    )
                )

    missing = []
    used_waivers: set[tuple[str, str, str]] = set()
    totals = []
    for group in requested:
        if group not in coverpoint_hits:
            missing.append(f"{group}: no covergroup summary")
            continue

        cp_hit, cp_total = coverpoint_hits[group]
        cross_hit = cross_total = cross_waived = 0
        crosses = declared_cross_hits[group]
        for hit, total, label in crosses:
            cross_hit += hit
            cross_total += total
            waiver = reviewed_waivers.get((group, "cross", label))
            if waiver is not None:
                used_waivers.add((group, "cross", label))
                if hit + waiver.missing != total:
                    missing.append(
                        f"{group}: waiver for {label!r} accounts for "
                        f"{waiver.missing} missing bins, observed {total - hit}"
                    )
                cross_waived += waiver.missing

        totals.append(
            HarcFunctionalCoverageTotals(
                group=group,
                coverpoint_hit=cp_hit,
                coverpoint_total=cp_total,
                declared_cross_hit=cross_hit,
                declared_cross_waived=cross_waived,
                declared_cross_total=cross_total,
                declared_crosses=len(crosses),
            )
        )

    unused_waivers = sorted(set(reviewed_waivers) - used_waivers)
    if unused_waivers:
        missing.append(f"unused functional coverage waivers: {unused_waivers}")

    for total in totals:
        if total.coverpoint_hit != total.coverpoint_total:
            missing.append(
                f"{total.group}: coverpoints "
                f"{total.coverpoint_hit}/{total.coverpoint_total}"
            )
        if require_declared_crosses and total.declared_crosses == 0:
            missing.append(f"{total.group}: no declared crosses reported")
        if (
            total.declared_cross_hit + total.declared_cross_waived
            != total.declared_cross_total
        ):
            missing.append(
                f"{total.group}: declared crosses hit+waived "
                f"{total.declared_cross_hit}+{total.declared_cross_waived}/"
                f"{total.declared_cross_total}"
            )

    if missing:
        raise AssertionError(
            "functional coverage gate failed: " + ", ".join(missing)
        )
    return totals


def assert_harc_functional_coverage_at_least(
    output: str,
    *,
    covergroups: Iterable[str],
    min_coverpoint_percent: float,
    min_declared_cross_percent: float,
    require_declared_crosses: bool = True,
) -> tuple[HarcFunctionalCoverageTotals, ...]:
    """Require minimum HARC functional coverpoint and declared-cross coverage."""

    totals = harc_functional_coverage_totals(output, covergroups=covergroups)
    missing = []
    for total in totals:
        coverpoint_percent = (
            100.0
            if total.coverpoint_total == 0
            else 100.0 * total.coverpoint_hit / total.coverpoint_total
        )
        if coverpoint_percent < min_coverpoint_percent:
            missing.append(
                f"{total.group}: coverpoints "
                f"{total.coverpoint_hit}/{total.coverpoint_total} "
                f"({coverpoint_percent:.2f}%) < {min_coverpoint_percent:.2f}%"
            )
        if require_declared_crosses and total.declared_crosses == 0:
            missing.append(f"{total.group}: no declared crosses reported")
        if total.declared_cross_total:
            declared_cross_percent = (
                100.0
                * (total.declared_cross_hit + total.declared_cross_waived)
                / total.declared_cross_total
            )
            if declared_cross_percent < min_declared_cross_percent:
                missing.append(
                    f"{total.group}: declared crosses "
                    f"{total.declared_cross_hit}+{total.declared_cross_waived}/"
                    f"{total.declared_cross_total} "
                    f"({declared_cross_percent:.2f}%) < "
                    f"{min_declared_cross_percent:.2f}%"
                )
    if missing:
        raise AssertionError(
            "functional coverage gate failed: " + ", ".join(missing)
        )
    return totals


def _sim_args(
    config: HarcSim,
    *,
    emit_only: bool,
    coverage: bool,
    coverage_json: PathLike | None = None,
) -> list[str]:
    args = ["sim"]
    has_sv = bool(config.sv_files)
    has_dut = bool(config.dut_files)
    if has_sv == has_dut:
        raise AssertionError("harc sim requires exactly one backend: sv_files or dut_files")
    if any(
        arg == "--codegen" or str(arg).startswith("--codegen=")
        for arg in config.extra_args
    ):
        raise AssertionError("HARC runner forbids --codegen; use default TBIR")
    if any(arg == "--seed" or str(arg).startswith("--seed=") for arg in config.extra_args):
        raise AssertionError("HARC runner requires seed=... instead of --seed")
    if any(
        arg == "--coverage-json" or str(arg).startswith("--coverage-json=")
        for arg in config.extra_args
    ):
        raise AssertionError("HARC runner owns --coverage-json export paths")
    for sv in _as_path_args(config.sv_files):
        args.extend(["--sv", sv])
    for dut in _as_path_args(config.dut_files):
        args.extend(["--dut", dut])
    if config.top:
        args.extend(["--top", config.top])
    if config.test:
        args.extend(["--test", config.test])
    if config.outdir is not None:
        args.extend(["--outdir", str(Path(config.outdir))])
    if config.seed is not None:
        if config.seed < 0:
            raise AssertionError(f"HARC seed must be non-negative: {config.seed}")
        args.extend(["--seed", str(config.seed)])
    for src in _as_path_args(config.ref_src):
        args.extend(["--ref-src", src])
    for name, value in sorted(config.parameters.items()):
        if isinstance(value, bool):
            value = int(value)
        args.extend(["--param", f"{name}={value}"])
    for arg in config.verilator_args:
        args.extend(["--verilator-arg", arg])
    if emit_only:
        args.append("--emit-only")
    if coverage:
        args.append("--coverage")
    if coverage_json is not None:
        args.extend(["--coverage-json", str(Path(coverage_json))])
    args.extend(config.extra_args)
    args.extend(_as_path_args(config.harc_files))
    return args


def _sim_env(config: HarcSim, *, emit_only: bool) -> dict[str, str] | None:
    if config.test and not emit_only:
        return {"HARC_TEST": config.test}
    return None


def harc_sim_coverage_command(
    config: HarcSim,
    *,
    coverage_json: PathLike | None = None,
) -> tuple[str, ...]:
    """Return the exact `harc sim --coverage` command without running it."""

    binary = str(config.harc_bin) if config.harc_bin is not None else resolve_harc_bin()
    return (
        binary,
        *_sim_args(
            config,
            emit_only=False,
            coverage=True,
            coverage_json=coverage_json,
        ),
    )


def crv_seed_manifest_entry(
    *,
    seed: int,
    profile: str,
    iterations: int,
    config: HarcSim,
    coverage_db: PathLike | None = None,
    functional_coverage_jsonl: PathLike | None = None,
    trace: PathLike | None = None,
    status: str = "planned",
) -> CrvSeedManifestEntry:
    """Create one reviewed CRV campaign manifest entry without executing HARC."""

    if config.outdir is None:
        raise AssertionError("CRV seed manifest requires a per-seed outdir")
    backend = "dut" if config.dut_files else "sv" if config.sv_files else ""
    command_config = replace(
        config,
        seed=seed,
    )
    coverage_path = (
        Path(coverage_db)
        if coverage_db is not None
        else Path(config.outdir) / "coverage.dat"
    )
    return CrvSeedManifestEntry(
        seed=seed,
        profile=profile,
        iterations=iterations,
        command=harc_sim_coverage_command(
            command_config,
            coverage_json=functional_coverage_jsonl,
        ),
        backend=backend,
        codegen="default-tbir",
        outdir=config.outdir,
        coverage_db=coverage_path,
        trace=trace,
        status=status,
    )


def write_crv_seed_manifest(
    entries: Sequence[CrvSeedManifestEntry],
    *,
    output: PathLike,
) -> Path:
    """Write a deterministic JSON manifest for a parallel CRV seed campaign."""

    if not entries:
        raise AssertionError("CRV seed manifest requires at least one entry")
    seen: set[tuple[str, int]] = set()
    payload = []
    for entry in sorted(entries, key=lambda item: (item.profile, item.seed)):
        key = (entry.profile, entry.seed)
        if key in seen:
            raise AssertionError(f"duplicate CRV seed manifest entry: {key}")
        seen.add(key)
        payload.append(entry.as_json_obj())
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return out


def run_crv_seed_campaign(
    *,
    config: HarcSim,
    seeds: Sequence[int],
    profile: str,
    iterations: int,
    campaign_dir: PathLike,
    manifest_output: PathLike | None = None,
    merged_coverage_output: PathLike | None = None,
    functional_covergroups: Sequence[str] = (),
    merged_functional_coverage_output: PathLike | None = None,
    functional_hole_report_output: PathLike | None = None,
    max_workers: int = 3,
) -> CrvSeedCampaignRun:
    """Run independent CRV seeds in parallel, then manifest and merge coverage.

    Each seed gets a distinct outdir under `campaign_dir`. The helper keeps
    default-TBIR enforcement centralized through `harc_sim_coverage_command`
    and merges only coverage databases from passing seeds.
    """

    seed_values = tuple(seeds)
    if not seed_values:
        raise AssertionError("CRV seed campaign requires at least one seed")
    if len(set(seed_values)) != len(seed_values):
        raise AssertionError("CRV seed campaign seeds must be unique")
    if any(seed < 0 for seed in seed_values):
        raise AssertionError("CRV seed campaign seeds must be non-negative")
    if max_workers <= 0:
        raise AssertionError("CRV seed campaign max_workers must be positive")
    if iterations <= 0:
        raise AssertionError("CRV seed campaign iterations must be positive")

    root = Path(campaign_dir)
    root.mkdir(parents=True, exist_ok=True)
    workers = min(max_workers, len(seed_values))

    def run_one(seed: int) -> tuple[int, HarcSim, HarcCoverageRun]:
        seed_config = replace(config, seed=seed, outdir=root / f"seed_{seed}")
        functional_jsonl = (
            Path(seed_config.outdir) / "functional_coverage.jsonl"
            if functional_covergroups
            else None
        )
        run = run_harc(
            _sim_args(
                seed_config,
                emit_only=False,
                coverage=True,
                coverage_json=functional_jsonl,
            ),
            cwd=seed_config.cwd,
            harc_bin=seed_config.harc_bin,
            env=_sim_env(seed_config, emit_only=False),
        )
        trace = Path(seed_config.outdir) / "harc_sim.log"
        trace.write_text(
            "stdout:\n"
            + run.stdout
            + "\n\nstderr:\n"
            + run.stderr
            + "\n",
            encoding="utf-8",
        )
        return seed, seed_config, HarcCoverageRun(
            run,
            coverage_files_from_outdir(seed_config.outdir),
        )

    by_seed: dict[int, tuple[HarcSim, HarcCoverageRun]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, seed): seed for seed in seed_values}
        for future in as_completed(futures):
            seed = futures[future]
            try:
                done_seed, seed_config, run = future.result()
            except Exception as exc:
                raise AssertionError(f"CRV seed {seed} failed") from exc
            by_seed[done_seed] = (seed_config, run)

    coverage_files: list[Path] = []
    functional_files: list[Path] = []
    entries: list[CrvSeedManifestEntry] = []
    for seed in sorted(seed_values):
        seed_config, run = by_seed[seed]
        if not run.coverage_files:
            raise AssertionError(f"CRV seed {seed} produced no coverage.dat")
        coverage_files.extend(run.coverage_files)
        if functional_covergroups:
            functional_jsonl = Path(seed_config.outdir) / "functional_coverage.jsonl"
            functional_files.append(
                write_harc_functional_coverage_artifact_from_jsonl(
                    functional_jsonl,
                    covergroups=functional_covergroups,
                    path=Path(seed_config.outdir) / "functional_coverage.json",
                    seed=seed,
                    profile=profile,
                )
            )
        entries.append(
            crv_seed_manifest_entry(
                seed=seed,
                profile=profile,
                iterations=iterations,
                config=seed_config,
                coverage_db=run.coverage_files[0],
                functional_coverage_jsonl=(
                    Path(seed_config.outdir) / "functional_coverage.jsonl"
                    if functional_covergroups
                    else None
                ),
                trace=Path(seed_config.outdir) / "harc_sim.log",
                status="passed",
            )
        )

    manifest = write_crv_seed_manifest(
        entries,
        output=manifest_output or root / "seed_manifest.json",
    )
    merged = merge_coverage_dat(
        coverage_files,
        output=merged_coverage_output or root / "merged_coverage.dat",
        cwd=config.cwd,
    )
    merged_functional: HarcFunctionalCoverageArtifacts | None = None
    if functional_covergroups:
        merged_functional = merge_harc_functional_coverage_artifacts(
            functional_files,
            output=merged_functional_coverage_output
            or root / "merged_functional_coverage.json",
            hole_report_output=functional_hole_report_output
            or root / "functional_hole_report.json",
        )
    return CrvSeedCampaignRun(
        manifest=manifest,
        merged_coverage=merged,
        entries=tuple(entries),
        coverage_files=tuple(coverage_files),
        functional_coverage_files=tuple(functional_files),
        merged_functional_coverage=(
            None if merged_functional is None else merged_functional.merged
        ),
        functional_hole_report=(
            None if merged_functional is None else merged_functional.hole_report
        ),
    )


def harc_check(
    harc_files: Sequence[PathLike],
    *,
    cwd: PathLike = REPO_ROOT,
    harc_bin: PathLike | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `harc check` for one or more HARC files."""

    config = HarcCheck(harc_files=harc_files, cwd=cwd, harc_bin=harc_bin)
    return run_harc(
        ["check", *_as_path_args(config.harc_files)],
        cwd=config.cwd,
        harc_bin=config.harc_bin,
    )


def harc_sim_emit_only(
    *,
    harc_files: Sequence[PathLike],
    sv_files: Sequence[PathLike] = (),
    dut_files: Sequence[PathLike] = (),
    top: str | None = None,
    test: str | None = None,
    outdir: PathLike | None = None,
    ref_src: Sequence[PathLike] = (),
    verilator_args: Sequence[str] = (),
    parameters: Mapping[str, object] | None = None,
    seed: int | None = None,
    cwd: PathLike = REPO_ROOT,
    harc_bin: PathLike | None = None,
    extra_args: Sequence[str] = (),
) -> subprocess.CompletedProcess[str]:
    """Run `harc sim --emit-only` for an SV or ARCH DUT and HARC test files.

    Parameter overrides are passed through HARC-native `--param Name=value`.
    """

    config = HarcSim(
        harc_files=harc_files,
        sv_files=sv_files,
        dut_files=dut_files,
        top=top,
        test=test,
        outdir=outdir,
        ref_src=ref_src,
        verilator_args=verilator_args,
        parameters=parameters or {},
        seed=seed,
        cwd=cwd,
        harc_bin=harc_bin,
        extra_args=extra_args,
    )
    return run_harc(
        _sim_args(config, emit_only=True, coverage=False),
        cwd=config.cwd,
        harc_bin=config.harc_bin,
        env=_sim_env(config, emit_only=True),
    )


def harc_sim_sv_coverage(
    *,
    sv_files: Sequence[PathLike],
    harc_files: Sequence[PathLike],
    top: str | None = None,
    test: str | None = None,
    outdir: PathLike | None = None,
    ref_src: Sequence[PathLike] = (),
    verilator_args: Sequence[str] = (),
    parameters: Mapping[str, object] | None = None,
    seed: int | None = None,
    cwd: PathLike = REPO_ROOT,
    harc_bin: PathLike | None = None,
    extra_args: Sequence[str] = (),
) -> HarcCoverageRun:
    """Run `harc sim --sv ... --coverage` for an SV DUT and HARC test files.

    Parameter overrides are passed through HARC-native `--param Name=value`.
    """
    if outdir is None:
        raise AssertionError("coverage simulation requires an outdir")

    config = HarcSim(
        harc_files=harc_files,
        sv_files=sv_files,
        top=top,
        test=test,
        outdir=outdir,
        ref_src=ref_src,
        verilator_args=verilator_args,
        parameters=parameters or {},
        seed=seed,
        cwd=cwd,
        harc_bin=harc_bin,
        extra_args=extra_args,
    )
    proc = run_harc(
        _sim_args(config, emit_only=False, coverage=True),
        cwd=config.cwd,
        harc_bin=config.harc_bin,
        env=_sim_env(config, emit_only=False),
    )
    return HarcCoverageRun(proc, coverage_files_from_outdir(outdir))


def harc_sim_dut_coverage(
    *,
    dut_files: Sequence[PathLike],
    harc_files: Sequence[PathLike],
    top: str | None = None,
    test: str | None = None,
    outdir: PathLike | None = None,
    ref_src: Sequence[PathLike] = (),
    verilator_args: Sequence[str] = (),
    parameters: Mapping[str, object] | None = None,
    seed: int | None = None,
    cwd: PathLike = REPO_ROOT,
    harc_bin: PathLike | None = None,
    extra_args: Sequence[str] = (),
) -> HarcCoverageRun:
    """Run `harc sim --dut ... --coverage` for ARCH DUTs and HARC tests."""
    if outdir is None:
        raise AssertionError("coverage simulation requires an outdir")

    config = HarcSim(
        harc_files=harc_files,
        dut_files=dut_files,
        top=top,
        test=test,
        outdir=outdir,
        ref_src=ref_src,
        verilator_args=verilator_args,
        parameters=parameters or {},
        seed=seed,
        cwd=cwd,
        harc_bin=harc_bin,
        extra_args=extra_args,
    )
    proc = run_harc(
        _sim_args(config, emit_only=False, coverage=True),
        cwd=config.cwd,
        harc_bin=config.harc_bin,
        env=_sim_env(config, emit_only=False),
    )
    return HarcCoverageRun(proc, coverage_files_from_outdir(outdir))
