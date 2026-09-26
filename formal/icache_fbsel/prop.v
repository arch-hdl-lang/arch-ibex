`ifdef FORMAL
  // Fill-buffer selection uniqueness. A "candidate" is an FB the output stage
  // could pick for the current output line, before the same-cycle beat-ready
  // test: live wants_out and a line-address match. If at most one FB is ever
  // a candidate, the (late) beat-ready term only gates validity and can move
  // after the select, which is what a registered-select restructure needs.
  wire f_c0 = fb0_wants_out && (fb0_addr[31:3] == source_line_addr);
  wire f_c1 = fb1_wants_out && (fb1_addr[31:3] == source_line_addr);
  wire f_c2 = fb2_wants_out && (fb2_addr[31:3] == source_line_addr);
  wire f_c3 = fb3_wants_out && (fb3_addr[31:3] == source_line_addr);
  wire [2:0] f_ncand = {2'd0, f_c0} + {2'd0, f_c1} + {2'd0, f_c2} + {2'd0, f_c3};
  wire [2:0] f_nwant = {2'd0, fb0_wants_out} + {2'd0, fb1_wants_out}
                     + {2'd0, fb2_wants_out} + {2'd0, fb3_wants_out};
  always @(posedge clk_i) if (rst_ni) assert (f_ncand <= 3'd1);
`ifdef COVERS
  // Non-vacuity: several FBs wanting out at once (so uniqueness is not
  // trivially implied by a single live FB), and a candidate whose beat is not
  // ready this cycle (the case a registered select would treat differently).
  always @(posedge clk_i) if (rst_ni) cover (f_nwant >= 3'd2);
  always @(posedge clk_i) if (rst_ni) cover (f_nwant >= 3'd2 && f_ncand == 3'd1);
  always @(posedge clk_i) if (rst_ni) cover (f_ncand == 3'd1 && !(fb0_covers || fb1_covers || fb2_covers || fb3_covers));
`endif
`endif
