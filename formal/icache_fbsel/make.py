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
srcs = [b / f for f in ("ibex_core_shared_pkg.sv", "fb_age_arb.sv", "ram_port_arb.sv", "bus_resp_fifo.sv",
                        "inval_ctrl.sv", "ibex_icache_output_stage.sv", "ibex_icache.sv")]
v = subprocess.run(["sv2v", *map(str, srcs)], check=True, capture_output=True, text=True).stdout
m = re.search(r"^module IbexIcacheOutputStage \(", v, re.M)
end = v.index("\nendmodule", m.start())
v = v[:end] + "\n" + (here / "prop.v").read_text() + v[end:]
# helper lemma on the fill-buffer registers, before ibex_icache's endmodule
m = re.search(r"^module ibex_icache \(", v, re.M)
end = v.index("\nendmodule", m.start())
v = v[:end] + "\n" + (here / "lemma.v").read_text() + v[end:]
# Formal-only observation ports on BusRespFifo (its array and pointers), wired
# to f_bq_* nets in ibex_icache, so the lemmas can relate the response queue
# to the fill-buffer counters (Yosys's frontend has no hierarchical refs).
hdr = "module BusRespFifo (\n\tclk_i,"
assert v.count(hdr) == 1
v = v.replace(hdr, "module BusRespFifo (\n\tf_mem_flat,\n\tf_wr,\n\tf_rd,\n\tclk_i,")
a0 = v.index("module BusRespFifo ("); z0 = v.index("\nendmodule", a0)
v = v[:z0] + """
\toutput wire [15:0] f_mem_flat;
\toutput wire [3:0] f_wr;
\toutput wire [3:0] f_rd;
\tassign f_mem_flat = {mem[7], mem[6], mem[5], mem[4], mem[3], mem[2], mem[1], mem[0]};
\tassign f_wr = wr_ptr;
\tassign f_rd = rd_ptr;""" + v[z0:]
inst = "\tBusRespFifo bus_resp_q(\n"
assert v.count(inst) == 1
v = v.replace(inst, "\twire [15:0] f_bq_mem;\n\twire [3:0] f_bq_wr;\n\twire [3:0] f_bq_rd;\n"
              + inst + "\t\t.f_mem_flat(f_bq_mem),\n\t\t.f_wr(f_bq_wr),\n\t\t.f_rd(f_bq_rd),\n")
# Formal-only age input on the output stage (the pre-restructure select
# ordered covering FBs by age; EQUIV rebuilds that select to compare against).
hdr = "module IbexIcacheOutputStage (\n\tclk_i,"
assert v.count(hdr) == 1
v = v.replace(hdr, "module IbexIcacheOutputStage (\n\tf_age,\n\tclk_i,")
a1 = v.index("module IbexIcacheOutputStage ("); z1 = v.index("\nendmodule", a1)
v = v[:z1] + "\n\tinput wire [7:0] f_age;" + v[z1:]
oinst = "\tIbexIcacheOutputStage output_stage(\n"
assert v.count(oinst) == 1
v = v.replace(oinst, oinst + "\t\t.f_age(fb_age_q),\n")
a = v.index("module InvalCtrl"); z = v.index("endmodule", a)
assert v[a:z].count("8'd255") == 2, "expected 2 walk terminators in InvalCtrl"
v = v[:a] + v[a:z].replace("8'd255", "8'd3") + v[z:]
(out / "icache_fbsel.v").write_text(v)
(out / "live_top.v").write_text((here.parent / "icache_liveness" / "live_top.v").read_text())
# Mutant for the proof: allocation ignores the coalesce check, so a second
# fill buffer can be allocated for a line already in flight. The uniqueness
# property must FAIL on it.
n = v.count("!coalesce_ic0")
assert n == 6, f"expected 6 coalesce gates (4 allocates + 2 IC1 regs), found {n}"
(out / "icache_nocoal.v").write_text(v.replace("!coalesce_ic0", "1'b1"))
# Mutants of the restructured select, for the EQUIV proof (both must FAIL):
#   noopen: the select ignores the open (allocated, non-stale) gating
#   nogate: the lifecycle index is no longer 0 when no FB covers
m, n = re.subn(r"assign (fb[0-3])_sel = \1_open && ", r"assign \1_sel = 1'b1 && ", v)
assert n == 4, f"noopen: expected 4 selects, found {n}"
(out / "icache_noopen.v").write_text(m)
g = "assign raw_fb_idx = (fb_any ? fb_sel_idx : 2'd0);"
assert v.count(g) == 1, "nogate: raw_fb_idx gating not found"
(out / "icache_nogate.v").write_text(v.replace(g, "assign raw_fb_idx = fb_sel_idx;"))
# Mutant for EQUIV2: the bus-only views also drop the same-cycle bus beat,
# so an FB covering through rvalid is missed by fb_any_d (A1 must FAIL).
nr = v
for i in range(4):
    a = f"assign fb{i}_beats_bus = (rvalid_v[{i}] ? fb{i}_beats_rcvd + 2'd1 : fb{i}_beats_rcvd);"
    assert nr.count(a) == 1, f"norv: fb{i}_beats_bus not found"
    nr = nr.replace(a, f"assign fb{i}_beats_bus = fb{i}_beats_rcvd;")
(out / "icache_norv.v").write_text(nr)

