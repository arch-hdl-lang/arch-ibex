#!/usr/bin/env python3
"""Build the formal-only icache variants for the liveness harness.

Reads build/*.sv (run `make build` first), sv2v's the icache and its
sub-modules, injects prop.v before ibex_icache's endmodule, and writes three
variants that differ ONLY in the lookup_grant line:

  nothrottle   lookup_grant = lookup_req_ic0                         (pre-Bug-C)
  exact        ... !((coalesce_ic0       || fb_full) && fill_write_req)  (Bug C fix as first shipped)
  branchyield  ... !((coalesce_grant_ic0 || fb_full) && fill_write_req)  (main since #10)

FORMAL ABSTRACTION: the cold-boot invalidation walk is shortened from 256 to
4 lines (InvalCtrl's `8'd255` terminator -> `8'd3`). Sound for this
property: RAM contents are free inputs, so the walk's writes constrain
nothing, and inval cycles never count toward starvation. It cuts the
counterexample depth from ~330 to ~80.
"""
import pathlib, re, subprocess, sys
here = pathlib.Path(__file__).resolve().parent
repo = here.parent.parent
out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else repo / "flow/out/formal_live")
out.mkdir(parents=True, exist_ok=True)
b = repo / "build"
srcs = [b / f for f in ("ibex_core_shared_pkg.sv", "fb_age_arb.sv", "ram_port_arb.sv", "bus_resp_fifo.sv",
                        "inval_ctrl.sv", "ibex_icache_output_stage.sv", "ibex_icache.sv")]
v = subprocess.run(["sv2v", *map(str, srcs)], check=True, capture_output=True, text=True).stdout
# the endmodule closing `module ibex_icache (`
m = re.search(r"^module ibex_icache \(", v, re.M)
end = v.index("\nendmodule", m.start())
v = v[:end] + "\n" + (here / "prop.v").read_text() + v[end:]
# short-walk abstraction, InvalCtrl only
a = v.index("module InvalCtrl"); z = v.index("endmodule", a)
n = v[a:z].count("8'd255")
assert n == 2, f"expected 2 walk terminators in InvalCtrl, found {n}"
v = v[:a] + v[a:z].replace("8'd255", "8'd3") + v[z:]
cur = "assign lookup_grant = lookup_req_ic0 && !((coalesce_grant_ic0 || fb_full) && fill_write_req);"
assert v.count(cur) == 1, "lookup_grant line not found -- has the design changed?"
variants = {
    "branchyield": cur,
    "exact": "assign lookup_grant = lookup_req_ic0 && !((coalesce_ic0 || fb_full) && fill_write_req);",
    "nothrottle": "assign lookup_grant = lookup_req_ic0;",
}
for k, line in variants.items():
    (out / f"icache_{k}.v").write_text(v.replace(cur, line))
# Upstream comparison: the SV lane's sv2v'd ibex_top (flow/sv2v.sh), same
# property on upstream's names (fill_req_ic0 / fill_grant_ic0), same
# short-walk abstraction (upstream ends its walk on `&inval_index_q`).
up = repo / "flow/out/sv/ibex_top.v"
if up.exists():
    u = up.read_text()
    a = u.index("module ibex_icache ("); z = u.index("\nendmodule", a)
    body = u[a:z]
    assert body.count("&inval_index_q") == 1, "upstream walk terminator not unique"
    body = body.replace("else if (&inval_index_q)", "else if (inval_index_q == 8'd3)")
    uprop = (here / "prop.v").read_text().replace("fill_write_req", "fill_req_ic0").replace(
        "!fill_grant", "!fill_grant_ic0").replace("fill_grant &&", "fill_grant_ic0 &&")
    (out / "icache_upstream.v").write_text(body + "\n" + uprop + "\nendmodule\n")
    print("wrote upstream variant")
for f in ("live_top.v",):
    (out / f).write_text((here / f).read_text())
print(f"wrote {len(variants)} variants to {out}")
