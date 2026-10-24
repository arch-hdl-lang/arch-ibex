#!/usr/bin/env python3
"""mkmiter.py <ref_build_dir> <dut_build_dir> <out_dir>

Formal harness for the icache output-path ablation study.
  * Both designs are the real generated ibex_icache (+ sub-modules), sv2v'd;
    the DUT copy has every module renamed with suffix _D.
  * Environment (mtop): adversarial core + OBI memory as in
    formal/icache_liveness/live_top.v (gnt only answers a request, rvalid only
    for an outstanding grant, branch_i => req_i), PLUS a coherent tag/data RAM
    model (prim_ram_1p-like: 1-cycle read latency, read data held between
    reads, arbitrary initial contents, written only by the icache). The RAM is
    driven by the REF design's RAM port; under EQUIV the DUT's RAM port is
    asserted equal, so up to the first mismatch both see the same RAM.
  * Bus read data is coherent too: rdata = f(address) for a fixed but
    arbitrary f (anyconst key), via a queue of granted addresses.
  * Same short-walk abstraction as formal/icache_liveness (InvalCtrl
    8'd255 -> 8'd3; RAM contents are free, so the walk constrains nothing).
Checks (defines):
  EQUIV      cycle-exact equivalence of every icache output, with rdata_o /
             err_o / err_plus2_o compared only while valid_o (they are
             don't-care otherwise, spec Integration constraints).
  ROUT2_REF  R-OUT-2 stability on REF: valid_o && !ready_i && !branch_i &&
  ROUT2_DUT  !err_o at t  ==>  valid_o and rdata/addr/err/err_plus2 unchanged
             at t+1.
  COVERS     non-vacuity covers (backpressure on a valid output; pool full).
"""
import pathlib, re, subprocess, sys
ref_dir, dut_dir, out = map(pathlib.Path, sys.argv[1:4])
out.mkdir(parents=True, exist_ok=True)
FILES = ("ibex_core_shared_pkg.sv", "fb_age_arb.sv", "ram_port_arb.sv", "bus_resp_fifo.sv",
         "inval_ctrl.sv", "ibex_icache_output_stage.sv", "ibex_icache.sv")

def conv(d, suffix):
    v = subprocess.run(["sv2v", *[str(d / f) for f in FILES]], check=True,
                       capture_output=True, text=True).stdout
    a = v.index("module InvalCtrl"); z = v.index("endmodule", a)
    assert v[a:z].count("8'd255") == 2
    v = v[:a] + v[a:z].replace("8'd255", "8'd3") + v[z:]
    if suffix:
        for name in re.findall(r"^module (\w+)", v, re.M):
            v = re.sub(r"\b%s\b" % re.escape(name), name + suffix, v)
    return v

(out / "ref.v").write_text(conv(ref_dir, ""))
(out / "dut.v").write_text(conv(dut_dir, "_D"))

PORTS_IN = "req_i branch_i addr_i ready_i instr_gnt_i instr_rdata_i instr_rvalid_i".split()
OUTS = ["valid_o", "rdata_o", "addr_o", "err_o", "err_plus2_o", "instr_req_o", "instr_addr_o",
        "ic_tag_req_o", "ic_tag_write_o", "ic_tag_addr_o", "ic_tag_wdata_o",
        "ic_data_req_o", "ic_data_write_o", "ic_data_addr_o", "ic_data_wdata_o",
        "ic_scr_key_req_o", "busy_o", "ecc_error_o"]
W = {"rdata_o": 32, "addr_o": 32, "instr_addr_o": 32, "ic_tag_req_o": 2, "ic_tag_addr_o": 8,
     "ic_tag_wdata_o": 22, "ic_data_req_o": 2, "ic_data_addr_o": 8, "ic_data_wdata_o": 64}

def decl(sfx):
    return "\n".join(f"  wire {'[%d:0] ' % (W[o]-1) if o in W else ''}{o}{sfx};" for o in OUTS)

def inst(mod, name, sfx):
    conns = [".clk_i(clk)", ".rst_ni(rst_ni)", ".req_i(req_i)", ".branch_i(branch_i)",
             ".addr_i(addr_i)", ".ready_i(ready_i)", ".instr_gnt_i(instr_gnt_i)",
             ".instr_rdata_i(bus_rdata)", ".instr_err_i(1'b0)", ".instr_rvalid_i(instr_rvalid_i)",
             ".ic_tag_rdata_i(tag_rdata)", ".ic_data_rdata_i(data_rdata)",
             ".ic_scr_key_valid_i(1'b1)", ".icache_enable_i(1'b1)", ".icache_inval_i(1'b0)"]
    conns += [f".{o}({o}{sfx})" for o in OUTS]
    return f"  {mod} {name} (\n    " + ",\n    ".join(conns) + "\n  );"

top = f"""
module mtop (
  input clk,
  input req_i, input branch_i, input [31:0] addr_i, input ready_i,
  input instr_gnt_i, input instr_rvalid_i
);
  reg [1:0] rst_cnt = 2'd0;
  wire rst_ni = rst_cnt[1];
  always @(posedge clk) if (!rst_cnt[1]) rst_cnt <= rst_cnt + 2'd1;

{decl("_r")}
{decl("_d")}

  // ---- OBI memory: in-order responses, coherent data = f(address) ----
  (* anyconst *) reg [31:0] f_key;
  reg [2:0] outstanding = 3'd0;
  reg [31:0] q_addr [0:7];
  reg [2:0] q_wr = 3'd0, q_rd = 3'd0;
  always @(posedge clk)
    if (!rst_ni) begin outstanding <= 3'd0; q_wr <= 3'd0; q_rd <= 3'd0; end
    else begin
      outstanding <= outstanding + {{2'd0, instr_req_o_r & instr_gnt_i}} - {{2'd0, instr_rvalid_i}};
      if (instr_req_o_r & instr_gnt_i) begin q_addr[q_wr] <= instr_addr_o_r; q_wr <= q_wr + 3'd1; end
      if (instr_rvalid_i) q_rd <= q_rd + 3'd1;
    end
  wire [31:0] rsp_addr = q_addr[q_rd];
  wire [31:0] bus_rdata = rsp_addr ^ f_key;
  always @(*) begin
    if (instr_gnt_i)    assume (instr_req_o_r);
    if (instr_rvalid_i) assume (outstanding != 3'd0);
    if (branch_i)       assume (req_i);
  end

  // ---- tag/data RAM (ram_model.v), driven by the REF design's RAM port ----
  wire [43:0]  tag_rdata;
  wire [127:0] data_rdata;
  ram_model u_ram (.clk(clk),
    .tag_req(ic_tag_req_o_r), .tag_write(ic_tag_write_o_r), .tag_addr(ic_tag_addr_o_r), .tag_wdata(ic_tag_wdata_o_r),
    .data_req(ic_data_req_o_r), .data_write(ic_data_write_o_r), .data_addr(ic_data_addr_o_r), .data_wdata(ic_data_wdata_o_r),
    .tag_rdata(tag_rdata), .data_rdata(data_rdata));

{inst("ibex_icache", "u_ref", "_r")}
{inst("ibex_icache_D", "u_dut", "_d")}

`ifdef EQUIV
  always @(*) if (rst_ni) begin
    assert (valid_o_r == valid_o_d);
    assert (addr_o_r == addr_o_d);
    if (valid_o_r) begin
      assert (rdata_o_r == rdata_o_d);
      assert (err_o_r == err_o_d);
      assert (err_plus2_o_r == err_plus2_o_d);
    end
    assert (instr_req_o_r == instr_req_o_d);
    if (instr_req_o_r) assert (instr_addr_o_r == instr_addr_o_d);
    assert (ic_tag_req_o_r == ic_tag_req_o_d);
    assert (ic_data_req_o_r == ic_data_req_o_d);
    if (|ic_tag_req_o_r) begin
      assert (ic_tag_write_o_r == ic_tag_write_o_d);
      assert (ic_tag_addr_o_r == ic_tag_addr_o_d);
      if (ic_tag_write_o_r) assert (ic_tag_wdata_o_r == ic_tag_wdata_o_d);
    end
    if (|ic_data_req_o_r) begin
      assert (ic_data_write_o_r == ic_data_write_o_d);
      assert (ic_data_addr_o_r == ic_data_addr_o_d);
      if (ic_data_write_o_r) assert (ic_data_wdata_o_r == ic_data_wdata_o_d);
    end
    assert (busy_o_r == busy_o_d);
  end
`endif

  // ---- R-OUT-2 stability ----
  reg f_past_hold_r = 1'b0, f_past_hold_d = 1'b0;
  reg [31:0] p_rdata_r, p_addr_r, p_rdata_d, p_addr_d;
  reg p_err_r, p_e2_r, p_err_d, p_e2_d;
  always @(posedge clk) begin
    f_past_hold_r <= rst_ni && valid_o_r && !ready_i && !branch_i && !err_o_r;
    f_past_hold_d <= rst_ni && valid_o_d && !ready_i && !branch_i && !err_o_d;
    p_rdata_r <= rdata_o_r; p_addr_r <= addr_o_r; p_err_r <= err_o_r; p_e2_r <= err_plus2_o_r;
    p_rdata_d <= rdata_o_d; p_addr_d <= addr_o_d; p_err_d <= err_o_d; p_e2_d <= err_plus2_o_d;
  end
`ifdef ROUT2_REF
  always @(*) if (rst_ni && f_past_hold_r) begin
    assert (valid_o_r); assert (rdata_o_r == p_rdata_r); assert (addr_o_r == p_addr_r);
    assert (err_o_r == p_err_r); assert (err_plus2_o_r == p_e2_r);
  end
`endif
`ifdef ROUT2_DUT
  always @(*) if (rst_ni && f_past_hold_d) begin
    assert (valid_o_d); assert (rdata_o_d == p_rdata_d); assert (addr_o_d == p_addr_d);
    assert (err_o_d == p_err_d); assert (err_plus2_o_d == p_e2_d);
  end
`endif
`ifdef COVERS
  reg [3:0] f_stall_run = 4'd0;
  always @(posedge clk) f_stall_run <= f_past_hold_d ? f_stall_run + (f_stall_run != 4'hf) : 4'd0;
  always @(*) if (rst_ni) begin
    cover (f_stall_run >= 4'd3);                               // 3+ cycles of backpressure
    cover (f_past_hold_d && f_stall_run == 4'd0 && addr_o_d[2]);  // backpressure on a beat-1 output
  end
`endif
endmodule
"""
(out / "mtop.v").write_text(top)

sby = """[tasks]
equiv
rout2_ref
rout2_dut
cover

[options]
equiv: mode bmc
rout2_ref: mode bmc
rout2_dut: mode bmc
equiv: aigsmt z3
rout2_ref: aigsmt z3
rout2_dut: aigsmt z3
cover: mode cover
depth DEPTH

[engines]
equiv: abc bmc3
rout2_ref: abc bmc3
rout2_dut: abc bmc3
cover: smtbmc boolector

[script]
equiv: read_verilog -formal -DEQUIV mtop.v
rout2_ref: read_verilog -formal -DROUT2_REF mtop.v
rout2_dut: read_verilog -formal -DROUT2_DUT mtop.v
cover: read_verilog -formal -DCOVERS mtop.v
read_verilog -formal ram_model.v
read_verilog -formal ref.v
read_verilog -formal dut.v
prep -top mtop
async2sync
flatten
memory -nomap
memory_map
opt -full
techmap
opt -fast
setundef -undriven -anyseq
setundef -anyseq

[files]
mtop.v
ram_model.v
ref.v
dut.v
"""
import shutil
shutil.copy(pathlib.Path(__file__).parent / "ram_model.v", out / "ram_model.v")
depth = sys.argv[4] if len(sys.argv) > 4 else "30"
(out / "miter.sby").write_text(sby.replace("DEPTH", depth))
print("wrote", out)
