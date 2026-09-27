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
`ifdef EQUIV3
  // Shadow of the pre-RecentLineRam storage: the old recent_addr_q /
  // recent_line_q registers, updated by the old logic (same priority:
  // clear writes nothing; IC1 hit capture; else completed FB line).
  reg [28:0] f_sa [0:7];
  reg [63:0] f_sl [0:7];
  always @(posedge clk_i)
    if (!(icache_inval_i || !icache_enable_i)) begin
      if (lookup_valid_ic1_q && any_hit_ic1) begin
        f_sa[lookup_recent_idx] <= lookup_addr_ic1_q[31:3];
        f_sl[lookup_recent_idx] <= hit_data_ic1;
      end else if (raw_complete_noerr && fb_any) begin
        f_sa[recent_idx] <= source_line_addr;
        f_sl[recent_idx] <= raw_line;
      end
    end
  wire f_old_recent_covers = recent_valid_q[recent_idx] && (f_sa[recent_idx] == source_line_addr);
  wire [63:0] f_old_raw_line = ic1_covers ? hit_data_ic1 :
                               (ic1_hold_covers ? ic1_hold_line_q :
                               (fb_any ? fb_sel_line : f_sl[recent_idx]));
  always @(posedge clk_i) if (rst_ni) begin
    assert (!recent_valid_q[0] || f_rl_mem[92:0] == {f_sa[0], f_sl[0]});
    assert (!recent_valid_q[1] || f_rl_mem[185:93] == {f_sa[1], f_sl[1]});
    assert (!recent_valid_q[2] || f_rl_mem[278:186] == {f_sa[2], f_sl[2]});
    assert (!recent_valid_q[3] || f_rl_mem[371:279] == {f_sa[3], f_sl[3]});
    assert (!recent_valid_q[4] || f_rl_mem[464:372] == {f_sa[4], f_sl[4]});
    assert (!recent_valid_q[5] || f_rl_mem[557:465] == {f_sa[5], f_sl[5]});
    assert (!recent_valid_q[6] || f_rl_mem[650:558] == {f_sa[6], f_sl[6]});
    assert (!recent_valid_q[7] || f_rl_mem[743:651] == {f_sa[7], f_sl[7]});
    assert (recent_covers == f_old_recent_covers);
    assert (!raw_valid || raw_line == f_old_raw_line);
  end
`endif
`ifdef COVERS
  // an output served from the recent-line buffer (EQUIV3 is about this source)
  always @(posedge clk_i) if (rst_ni) cover (raw_valid && recent_covers && !ic1_any_covers && !fb_any);
  // Non-vacuity: several FBs wanting out at once (so uniqueness is not
  // trivially implied by a single live FB), and a candidate whose beat is not
  // ready this cycle (the case a registered select would treat differently).
  always @(posedge clk_i) if (rst_ni) cover (f_nwant >= 3'd2);
  always @(posedge clk_i) if (rst_ni) cover (f_nwant >= 3'd2 && f_ncand == 3'd1);
  always @(posedge clk_i) if (rst_ni) cover (f_ncand == 3'd1 && !(fb0_covers || fb1_covers || fb2_covers || fb3_covers));
`endif
`endif
