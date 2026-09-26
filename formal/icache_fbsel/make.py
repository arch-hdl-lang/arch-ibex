#!/usr/bin/env python3
"""Build the formal input for the fill-buffer selection check.

Reads build/*.sv (run `make build` first), sv2v's the icache and its
sub-modules, injects prop.v before IbexIcacheOutputStage's endmodule, and
applies the same short-walk abstraction as formal/icache_liveness (InvalCtrl
8'd255 -> 8'd3: RAM contents are free inputs, so the walk constrains nothing).
"""
import pathlib, re, subprocess, sys
here = pathlib.Path(__file__).resolve().parent
repo = here.parent.parent
out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else repo / "flow/out/formal_fbsel")
out.mkdir(parents=True, exist_ok=True)
b = repo / "build"
srcs = [b / f for f in ("ibex_core_shared_pkg.sv", "fb_age_arb.sv", "ram_port_arb.sv",
                        "inval_ctrl.sv", "ibex_icache_output_stage.sv", "ibex_icache.sv")]
v = subprocess.run(["sv2v", *map(str, srcs)], check=True, capture_output=True, text=True).stdout
m = re.search(r"^module IbexIcacheOutputStage \(", v, re.M)
end = v.index("\nendmodule", m.start())
v = v[:end] + "\n" + (here / "prop.v").read_text() + v[end:]
a = v.index("module InvalCtrl"); z = v.index("endmodule", a)
assert v[a:z].count("8'd255") == 2, "expected 2 walk terminators in InvalCtrl"
v = v[:a] + v[a:z].replace("8'd255", "8'd3") + v[z:]
(out / "icache_fbsel.v").write_text(v)
(out / "live_top.v").write_text((here.parent / "icache_liveness" / "live_top.v").read_text())
