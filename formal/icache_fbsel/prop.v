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
`ifdef EQUIV
  // Equivalence with the pre-restructure select: the minimum-age FB among
  // the covering ones (ties -> lower index; 0 when none covers).
  wire [2:0] f_oc0 = fb0_covers ? {1'b0, f_age[1:0]} : 3'd4;
  wire [2:0] f_oc1 = fb1_covers ? {1'b0, f_age[3:2]} : 3'd4;
  wire [2:0] f_oc2 = fb2_covers ? {1'b0, f_age[5:4]} : 3'd4;
  wire [2:0] f_oc3 = fb3_covers ? {1'b0, f_age[7:6]} : 3'd4;
  wire [2:0] f_om01 = (f_oc0 <= f_oc1) ? f_oc0 : f_oc1;
  wire [1:0] f_oi01 = (f_oc0 <= f_oc1) ? 2'd0 : 2'd1;
  wire [2:0] f_om23 = (f_oc2 <= f_oc3) ? f_oc2 : f_oc3;
  wire [1:0] f_oi23 = (f_oc2 <= f_oc3) ? 2'd2 : 2'd3;
  wire [1:0] f_old_idx = (f_om01 <= f_om23) ? f_oi01 : f_oi23;
  // (1) the lifecycle index (out_done pulses, hold_done_idx_q) is unchanged,
  //     always; (2) the data-path select agrees whenever a FB covers -- the
  //     only case in which fb_sel_line/addr/beats/err reach anything.
  always @(posedge clk_i) if (rst_ni) begin
    assert (raw_fb_idx == f_old_idx);
    assert (!fb_any || fb_sel_idx == f_old_idx);
  end
`endif
`ifdef EQUIV2
  // Data-path fb_any_d (bus-only views) vs fb_any (live views). With these,
  // raw_valid / raw_line / raw_beats / raw_err0/1 equal their fb_any forms:
  //   A0: fb_any_d implies fb_any;
  //   A1: where they differ, ic1_covers holds (IC1 source has priority in
  //       raw_line and is part of ic1_any_covers in raw_valid);
  //   A2: where they differ, the selected FB's line is complete and
  //       error-free, so raw_beats = 2 and raw_err0/1 = 0 either way.
  always @(posedge clk_i) if (rst_ni) begin
    assert (!fb_any_d || fb_any);
    assert (!(fb_any && !fb_any_d) || ic1_covers);
    assert (!(fb_any && !fb_any_d) || (fb_sel_beats == 2'd2 && !fb_sel_err0 && !fb_sel_err1));
  end
`endif
`ifdef COVERS
  // the case EQUIV2 is about: an FB covers only through the IC1-hit capture
  always @(posedge clk_i) if (rst_ni) cover (fb_any && !fb_any_d);
  // Non-vacuity: several FBs wanting out at once (so uniqueness is not
  // trivially implied by a single live FB), and a candidate whose beat is not
  // ready this cycle (the case a registered select would treat differently).
  always @(posedge clk_i) if (rst_ni) cover (f_nwant >= 3'd2);
  always @(posedge clk_i) if (rst_ni) cover (f_nwant >= 3'd2 && f_ncand == 3'd1);
  always @(posedge clk_i) if (rst_ni) cover (f_ncand == 3'd1 && !(fb0_covers || fb1_covers || fb2_covers || fb3_covers));
`endif
`endif
