// FPGA model of lowRISC's prim_clock_gating for the ECP5 flow, used on BOTH
// lanes (flow/ecp5_pnr.sh reads it with `read_verilog -overwrite` after the
// lane's sv2v file). The generic model gates the clock through an enable
// latch; ECP5 has no latch primitive and `synth_ecp5` rejects the design at
// `check -assert`. As Ibex's own FPGA targets do, gating is dropped on FPGA:
// clk_o follows clk_i unconditionally. The enable logic that feeds en_i is
// still synthesised; only the gate itself disappears (identically per lane).
module prim_clock_gating #(
  parameter [0:0] NoFpgaGate = 1'b0,
  parameter [0:0] FpgaBufGlobal = 1'b1
) (
  input  wire clk_i,
  input  wire en_i,
  input  wire test_en_i,
  output wire clk_o
);
  assign clk_o = clk_i;
  wire unused_en = en_i | test_en_i;
endmodule
