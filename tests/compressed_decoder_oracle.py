"""Build a reproducible independent RTL corpus for the default-TBIR decoder gate."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess

UPSTREAM_REV = "eede2fbbef007d53cafbd85d937b897751c40a54"
ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "tests/harc/reference"


def build_corpus(outdir: Path) -> Path:
    upstream = Path(os.environ.get("IBEX_REFERENCE_ROOT", ROOT.parent / "ibex")).resolve()
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(upstream), *args], text=True).strip()
    if git("rev-parse", "HEAD") != UPSTREAM_REV:
        raise AssertionError(f"reference must be pinned to {UPSTREAM_REV}: {upstream}")
    sources = [upstream / "rtl/ibex_pkg.sv", upstream / "rtl/ibex_compressed_decoder.sv"]
    includes = upstream / "vendor/lowrisc_ip/ip/prim/rtl"
    # Include macros participate in compilation and therefore in provenance.
    tracked = [*sources, *sorted(includes.glob("prim_assert*"))]
    for path in tracked:
        expected = subprocess.check_output(["git", "-C", str(upstream), "show", f"{UPSTREAM_REV}:{path.relative_to(upstream)}"])
        if path.read_bytes() != expected:
            raise AssertionError(f"modified reference source: {path}")
    outdir.mkdir(parents=True, exist_ok=True)
    build = outdir / "obj"
    command = ["verilator", "--cc", "--exe", "--build", "-j", "4", "-Wno-fatal",
               "--top-module", "ibex_compressed_decoder", "--Mdir", str(build),
               f"-I{includes}", *map(str, sources), str(REFERENCE / "compressed_decoder_oracle.cpp")]
    proc = subprocess.run(command, text=True, capture_output=True)
    (outdir / "build.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode:
        raise AssertionError(f"oracle build failed: {outdir / 'build.log'}\n{proc.stderr[-4000:]}")
    vectors = outdir / "vectors.txt"
    subprocess.run([str(build / "Vibex_compressed_decoder"), str(vectors)], check=True)
    manifest = {"revision": UPSTREAM_REV, "parameters": {"RV32ZC": 3, "ResetAll": 0},
                "command": command, "verilator": subprocess.check_output(["verilator", "--version"], text=True).strip(),
                "sha256": {str(p.relative_to(upstream)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked},
                "generator_sha256": hashlib.sha256((REFERENCE / "compressed_decoder_oracle.cpp").read_bytes()).hexdigest(),
                "vectors_sha256": hashlib.sha256(vectors.read_bytes()).hexdigest(),
                "rows": int(vectors.open().readline())}
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return vectors
