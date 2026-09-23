// Environment for the icache bounded-liveness proof.
// Free (adversarial) inputs: req_i, branch_i, addr_i, ready_i, tag/data RAM
// read data, bus grant/rvalid/rdata -- constrained only by protocol.
module live_top (
  input clk,
  input req_i, input branch_i, input [31:0] addr_i, input ready_i,
  input instr_gnt_i, input [31:0] instr_rdata_i, input instr_rvalid_i,
  input [43:0] ic_tag_rdata_i, input [127:0] ic_data_rdata_i
);
  // Reset held for the first two cycles, then released for good.
  reg [1:0] rst_cnt = 2'd0;
  wire rst_ni = rst_cnt[1];
  always @(posedge clk) if (!rst_cnt[1]) rst_cnt <= rst_cnt + 2'd1;

  wire instr_req_o;
  // OBI-style bus: gnt only answers a request; rvalid only for a
  // request that was granted in an earlier cycle; responses in order.
  reg [2:0] outstanding = 3'd0;
  always @(posedge clk)
    if (!rst_ni) outstanding <= 3'd0;
    else outstanding <= outstanding + {2'd0, instr_req_o & instr_gnt_i} - {2'd0, instr_rvalid_i};
  always @(*) begin
    if (instr_gnt_i)    assume (instr_req_o);
    if (instr_rvalid_i) assume (outstanding != 3'd0);
    if (branch_i)       assume (req_i);   // the IF stage only branches while requesting
  end


`ifdef BRANCH_FAIR
  // Fairness: the IF stage branches at least once every BRANCH_K cycles.
  reg [7:0] since_branch = 8'd0;
  always @(posedge clk)
    if (!rst_ni || branch_i) since_branch <= 8'd0;
    else if (since_branch != 8'hff) since_branch <= since_branch + 8'd1;
  always @(*) if (rst_ni) assume (since_branch < `BRANCH_K);
`endif

  ibex_icache u_icache (
    .clk_i(clk), .rst_ni(rst_ni),
    .req_i(req_i), .branch_i(branch_i), .addr_i(addr_i), .ready_i(ready_i),
    .valid_o(), .rdata_o(), .addr_o(), .err_o(), .err_plus2_o(),
    .instr_req_o(instr_req_o), .instr_gnt_i(instr_gnt_i), .instr_addr_o(),
    .instr_rdata_i(instr_rdata_i), .instr_err_i(1'b0), .instr_rvalid_i(instr_rvalid_i),
    .ic_tag_req_o(), .ic_tag_write_o(), .ic_tag_addr_o(), .ic_tag_wdata_o(),
    .ic_tag_rdata_i(ic_tag_rdata_i),
    .ic_data_req_o(), .ic_data_write_o(), .ic_data_addr_o(), .ic_data_wdata_o(),
    .ic_data_rdata_i(ic_data_rdata_i),
    .ic_scr_key_valid_i(1'b1), .ic_scr_key_req_o(),
    .icache_enable_i(1'b1), .icache_inval_i(1'b0),
    .busy_o(), .ecc_error_o()
  );
endmodule
