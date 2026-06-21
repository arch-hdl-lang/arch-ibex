"""Small pytest-oriented helpers for running HARC commands."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
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

    HARC's current CLI exposes SV parameter overrides through Verilator flags,
    so `parameters={"W": 8}` lowers to `--verilator-arg -GW=8`.
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
) -> Path:
    """Merge Verilator `coverage.dat` files into one aggregate data file."""

    inputs = _as_path_args(coverage_files)
    if not inputs:
        raise AssertionError("no coverage.dat files provided for merge")
    out = Path(output)
    run_verilator_coverage(["--write", str(out), *inputs], cwd=cwd)
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


def arch_coverage_dat_totals(
    coverage_file: PathLike,
    *,
    source_prefixes: Iterable[PathLike],
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
        if not source:
            continue
        source_records += 1
        if not _source_matches_prefixes(source, prefixes):
            continue
        matched_sources.add(source)

        if page == "v_line":
            line_found += 1
            if count > 0:
                line_hit += 1
        elif page in {"v_branch", "v_user", "v_expr"}:
            branch_found += 1
            if count > 0:
                branch_hit += 1

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
) -> CoverageTotals:
    """Require 100% ARCH native simulator source/control coverage."""

    totals = arch_coverage_dat_totals(
        coverage_file,
        source_prefixes=source_prefixes,
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


def _sim_args(config: HarcSim, *, emit_only: bool, coverage: bool) -> list[str]:
    args = ["sim"]
    has_sv = bool(config.sv_files)
    has_dut = bool(config.dut_files)
    if has_sv == has_dut:
        raise AssertionError("harc sim requires exactly one backend: sv_files or dut_files")
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
    for src in _as_path_args(config.ref_src):
        args.extend(["--ref-src", src])
    for name, value in sorted(config.parameters.items()):
        if isinstance(value, bool):
            value = int(value)
        args.extend(["--verilator-arg", f"-G{name}={value}"])
    for arg in config.verilator_args:
        args.extend(["--verilator-arg", arg])
    if emit_only:
        args.append("--emit-only")
    if coverage:
        args.append("--coverage")
    args.extend(config.extra_args)
    args.extend(_as_path_args(config.harc_files))
    return args


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
    cwd: PathLike = REPO_ROOT,
    harc_bin: PathLike | None = None,
    extra_args: Sequence[str] = (),
) -> subprocess.CompletedProcess[str]:
    """Run `harc sim --emit-only` for an SV or ARCH DUT and HARC test files.

    Parameter overrides are passed through Verilator as `-GName=value`.
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
        cwd=cwd,
        harc_bin=harc_bin,
        extra_args=extra_args,
    )
    return run_harc(
        _sim_args(config, emit_only=True, coverage=False),
        cwd=config.cwd,
        harc_bin=config.harc_bin,
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
    cwd: PathLike = REPO_ROOT,
    harc_bin: PathLike | None = None,
    extra_args: Sequence[str] = (),
) -> HarcCoverageRun:
    """Run `harc sim --sv ... --coverage` for an SV DUT and HARC test files.

    Parameter overrides are passed through Verilator as `-GName=value`.
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
        cwd=cwd,
        harc_bin=harc_bin,
        extra_args=extra_args,
    )
    proc = run_harc(
        _sim_args(config, emit_only=False, coverage=True),
        cwd=config.cwd,
        harc_bin=config.harc_bin,
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
        cwd=cwd,
        harc_bin=harc_bin,
        extra_args=extra_args,
    )
    proc = run_harc(
        _sim_args(config, emit_only=False, coverage=True),
        cwd=config.cwd,
        harc_bin=config.harc_bin,
    )
    return HarcCoverageRun(proc, coverage_files_from_outdir(outdir))
