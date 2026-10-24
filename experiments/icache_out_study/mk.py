#!/usr/bin/env python3
"""mk.py <ref_build_dir> <dut_build_dir> <out_dir>

Random differential co-simulation of two generated ibex_icache builds
(Verilator). Each design gets its own coherent tag/data RAM and OBI bus
model; the core-side stimulus is shared. Checks, per design:
  * golden stream: every accepted output has addr_o equal to the expected
    PC (branch target / previous PC + 2 or 4) and rdata_o equal to the
    program memory at that PC (low 16 bits for compressed instructions);
  * R-OUT-2: valid_o && !ready_i && !branch_i && !err_o at t ==> valid_o and
    rdata_o/addr_o/err_o/err_plus2_o unchanged at t+1;
  * progress: no more than STALL_MAX cycles without an accepted output while
    req_i && ready_i and no branch;
and across designs (mode "equiv"): cycle-exact equality of valid_o, addr_o,
instr_req_o, instr_addr_o (when req), RAM ports, busy_o, and rdata_o/err_o/
err_plus2_o while valid_o.
"""
import pathlib, re, subprocess, sys
ref_dir, dut_dir, out = map(pathlib.Path, sys.argv[1:4])
out.mkdir(parents=True, exist_ok=True)
FILES = ("ibex_core_shared_pkg.sv", "fb_age_arb.sv", "ram_port_arb.sv", "bus_resp_fifo.sv",
         "inval_ctrl.sv", "ibex_icache_output_stage.sv", "ibex_icache.sv")

def conv(d, suffix):
    v = subprocess.run(["sv2v", *[str(d / f) for f in FILES]], check=True,
                       capture_output=True, text=True).stdout
    for name in re.findall(r"^module (\w+)", v, re.M):
        v = re.sub(r"\b%s\b" % re.escape(name), name + suffix, v)
    return v

(out / "ref.v").write_text(conv(ref_dir, "_R"))
(out / "dut.v").write_text(conv(dut_dir, "_D"))

def side(mod, sfx):
    return f"""
  // ---------------- {sfx} ----------------
  reg [21:0] tag0_{sfx} [0:255]; reg [21:0] tag1_{sfx} [0:255];
  reg [63:0] dat0_{sfx} [0:255]; reg [63:0] dat1_{sfx} [0:255];
  reg [21:0] tq0_{sfx}, tq1_{sfx}; reg [63:0] dq0_{sfx}, dq1_{sfx};
  wire [1:0] tag_req_{sfx}, data_req_{sfx}; wire tag_we_{sfx}, data_we_{sfx};
  wire [7:0] tag_addr_{sfx}, data_addr_{sfx}; wire [21:0] tag_wd_{sfx}; wire [63:0] data_wd_{sfx};
  initial begin tq0_{sfx} = 0; tq1_{sfx} = 0; dq0_{sfx} = 0; dq1_{sfx} = 0; end
  always @(posedge clk) begin
    if (tag_req_{sfx}[0]) begin if (tag_we_{sfx}) tag0_{sfx}[tag_addr_{sfx}] <= tag_wd_{sfx}; else tq0_{sfx} <= tag0_{sfx}[tag_addr_{sfx}]; end
    if (tag_req_{sfx}[1]) begin if (tag_we_{sfx}) tag1_{sfx}[tag_addr_{sfx}] <= tag_wd_{sfx}; else tq1_{sfx} <= tag1_{sfx}[tag_addr_{sfx}]; end
    if (data_req_{sfx}[0]) begin if (data_we_{sfx}) dat0_{sfx}[data_addr_{sfx}] <= data_wd_{sfx}; else dq0_{sfx} <= dat0_{sfx}[data_addr_{sfx}]; end
    if (data_req_{sfx}[1]) begin if (data_we_{sfx}) dat1_{sfx}[data_addr_{sfx}] <= data_wd_{sfx}; else dq1_{sfx} <= dat1_{sfx}[data_addr_{sfx}]; end
  end
  assign tag_req_o_{sfx} = tag_req_{sfx}; assign tag_we_o_{sfx} = tag_we_{sfx}; assign tag_addr_o_{sfx} = tag_addr_{sfx};
  assign tag_wd_o_{sfx} = tag_wd_{sfx}; assign data_req_o_{sfx} = data_req_{sfx}; assign data_we_o_{sfx} = data_we_{sfx};
  assign data_addr_o_{sfx} = data_addr_{sfx}; assign data_wd_o_{sfx} = data_wd_{sfx};
  {mod} u_{sfx} (
    .clk_i(clk), .rst_ni(rst_ni), .req_i(req_i), .branch_i(branch_i), .addr_i(addr_i), .ready_i(ready_i),
    .valid_o(valid_o_{sfx}), .rdata_o(rdata_o_{sfx}), .addr_o(addr_o_{sfx}), .err_o(err_o_{sfx}), .err_plus2_o(err_plus2_o_{sfx}),
    .instr_req_o(instr_req_o_{sfx}), .instr_gnt_i(instr_gnt_i_{sfx}), .instr_addr_o(instr_addr_o_{sfx}),
    .instr_rdata_i(instr_rdata_i_{sfx}), .instr_err_i(instr_err_i_{sfx}), .instr_rvalid_i(instr_rvalid_i_{sfx}),
    .ic_tag_req_o(tag_req_{sfx}), .ic_tag_write_o(tag_we_{sfx}), .ic_tag_addr_o(tag_addr_{sfx}), .ic_tag_wdata_o(tag_wd_{sfx}),
    .ic_tag_rdata_i({{tq0_{sfx}, tq1_{sfx}}}),
    .ic_data_req_o(data_req_{sfx}), .ic_data_write_o(data_we_{sfx}), .ic_data_addr_o(data_addr_{sfx}), .ic_data_wdata_o(data_wd_{sfx}),
    .ic_data_rdata_i({{dq0_{sfx}, dq1_{sfx}}}),
    .ic_scr_key_valid_i(1'b1), .ic_scr_key_req_o(),
    .icache_enable_i(icache_enable_i), .icache_inval_i(icache_inval_i),
    .busy_o(busy_o_{sfx}), .ecc_error_o()
  );
"""

def ports(sfx):
    return f"""  output valid_o_{sfx}, output [31:0] rdata_o_{sfx}, output [31:0] addr_o_{sfx}, output err_o_{sfx}, output err_plus2_o_{sfx},
  output instr_req_o_{sfx}, input instr_gnt_i_{sfx}, output [31:0] instr_addr_o_{sfx},
  input [31:0] instr_rdata_i_{sfx}, input instr_err_i_{sfx}, input instr_rvalid_i_{sfx},
  output [1:0] tag_req_o_{sfx}, output tag_we_o_{sfx}, output [7:0] tag_addr_o_{sfx}, output [21:0] tag_wd_o_{sfx},
  output [1:0] data_req_o_{sfx}, output data_we_o_{sfx}, output [7:0] data_addr_o_{sfx}, output [63:0] data_wd_o_{sfx},
  output busy_o_{sfx}"""

(out / "dual.v").write_text(f"""
module dual (
  input clk, input rst_ni, input req_i, input branch_i, input [31:0] addr_i, input ready_i,
  input icache_enable_i, input icache_inval_i,
{ports("R")},
{ports("D")}
);
{side("ibex_icache_R", "R")}
{side("ibex_icache_D", "D")}
endmodule
""")
subprocess.run(["cp", str(pathlib.Path(__file__).parent / "tb.cpp"), str(out / "tb.cpp")], check=True)
r = subprocess.run(["verilator", "--cc", "--exe", "--build", "-O2", "-j", "4", "--top-module", "dual",
                    "-Wno-fatal", "-Wno-lint", "-Wno-style", "-Wno-UNOPTFLAT", "-Wno-MULTIDRIVEN",
                    "-o", "cosim", "dual.v", "ref.v", "dut.v", "tb.cpp"],
                   cwd=out, capture_output=True, text=True)
(out / "build.log").write_text(r.stdout + r.stderr)
print("verilator rc", r.returncode)
sys.exit(r.returncode)
