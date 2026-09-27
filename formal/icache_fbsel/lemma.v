`ifdef FORMAL
`ifdef LEMMA
  // Helper lemma, on registers only: two fill buffers that can still want to
  // output (allocated, not stale, not output-done) never hold the same line.
  // The coalesce check at allocation is meant to guarantee it. It implies the
  // output-stage candidate uniqueness in prop.v and, unlike it, is a property
  // of state -- the form induction can close.
  function f_can_out(input integer fb);
`ifdef LEMMA_STRONG
    f_can_out = (phase_q[2*fb +: 2] != 2'd0) && !stale_q[fb];
`else
    f_can_out = (phase_q[2*fb +: 2] != 2'd0) && !stale_q[fb] && !out_done_q[fb];
`endif
  endfunction
  function [28:0] f_line(input integer fb);
    f_line = addr_q[32*fb+3 +: 29];
  endfunction
  // Environment, stated where the queue is visible: the memory answers only
  // granted, unanswered requests -- exactly the queued ones (live_top's own
  // counter says the same thing about the bus).
  always @(*) if (rst_ni && instr_rvalid_i) assume (!bus_resp_empty);

  // Response queue (BusRespFifo, latency 1): occupancy <= 8, and the
  // registered head equals the array entry at rd_ptr.
  wire [3:0] f_occ = f_bq_wr - f_bq_rd;
  // array rotated so entry k is the k-th queued (k = 0 is the head)
  wire [31:0] f_rot2 = {f_bq_mem, f_bq_mem} >> (6'd2 * f_bq_rd[2:0]);
  wire [1:0] f_q0 = f_rot2[1:0];
  wire [1:0] f_q1 = f_rot2[3:2];
  wire [1:0] f_q2 = f_rot2[5:4];
  wire [1:0] f_q3 = f_rot2[7:6];
  wire [1:0] f_q4 = f_rot2[9:8];
  wire [1:0] f_q5 = f_rot2[11:10];
  wire [1:0] f_q6 = f_rot2[13:12];
  wire [1:0] f_q7 = f_rot2[15:14];
  wire [3:0] f_cnt0 = {3'd0, (f_occ > 4'd0) && (f_q0 == 2'd0)} + {3'd0, (f_occ > 4'd1) && (f_q1 == 2'd0)} + {3'd0, (f_occ > 4'd2) && (f_q2 == 2'd0)} + {3'd0, (f_occ > 4'd3) && (f_q3 == 2'd0)} + {3'd0, (f_occ > 4'd4) && (f_q4 == 2'd0)} + {3'd0, (f_occ > 4'd5) && (f_q5 == 2'd0)} + {3'd0, (f_occ > 4'd6) && (f_q6 == 2'd0)} + {3'd0, (f_occ > 4'd7) && (f_q7 == 2'd0)};
  wire [3:0] f_outs0 = hit_q[0] ? 4'd0 : ({2'd0, beats_sent_q[1:0]} - {2'd0, beats_rcvd_q[1:0]});
  wire [3:0] f_cnt1 = {3'd0, (f_occ > 4'd0) && (f_q0 == 2'd1)} + {3'd0, (f_occ > 4'd1) && (f_q1 == 2'd1)} + {3'd0, (f_occ > 4'd2) && (f_q2 == 2'd1)} + {3'd0, (f_occ > 4'd3) && (f_q3 == 2'd1)} + {3'd0, (f_occ > 4'd4) && (f_q4 == 2'd1)} + {3'd0, (f_occ > 4'd5) && (f_q5 == 2'd1)} + {3'd0, (f_occ > 4'd6) && (f_q6 == 2'd1)} + {3'd0, (f_occ > 4'd7) && (f_q7 == 2'd1)};
  wire [3:0] f_outs1 = hit_q[1] ? 4'd0 : ({2'd0, beats_sent_q[3:2]} - {2'd0, beats_rcvd_q[3:2]});
  wire [3:0] f_cnt2 = {3'd0, (f_occ > 4'd0) && (f_q0 == 2'd2)} + {3'd0, (f_occ > 4'd1) && (f_q1 == 2'd2)} + {3'd0, (f_occ > 4'd2) && (f_q2 == 2'd2)} + {3'd0, (f_occ > 4'd3) && (f_q3 == 2'd2)} + {3'd0, (f_occ > 4'd4) && (f_q4 == 2'd2)} + {3'd0, (f_occ > 4'd5) && (f_q5 == 2'd2)} + {3'd0, (f_occ > 4'd6) && (f_q6 == 2'd2)} + {3'd0, (f_occ > 4'd7) && (f_q7 == 2'd2)};
  wire [3:0] f_outs2 = hit_q[2] ? 4'd0 : ({2'd0, beats_sent_q[5:4]} - {2'd0, beats_rcvd_q[5:4]});
  wire [3:0] f_cnt3 = {3'd0, (f_occ > 4'd0) && (f_q0 == 2'd3)} + {3'd0, (f_occ > 4'd1) && (f_q1 == 2'd3)} + {3'd0, (f_occ > 4'd2) && (f_q2 == 2'd3)} + {3'd0, (f_occ > 4'd3) && (f_q3 == 2'd3)} + {3'd0, (f_occ > 4'd4) && (f_q4 == 2'd3)} + {3'd0, (f_occ > 4'd5) && (f_q5 == 2'd3)} + {3'd0, (f_occ > 4'd6) && (f_q6 == 2'd3)} + {3'd0, (f_occ > 4'd7) && (f_q7 == 2'd3)};
  wire [3:0] f_outs3 = hit_q[3] ? 4'd0 : ({2'd0, beats_sent_q[7:6]} - {2'd0, beats_rcvd_q[7:6]});
  always @(posedge clk_i) if (rst_ni) begin
    assert (f_occ <= 4'd8);
    assert (f_occ == 4'd0 || bus_resp_fb == f_q0);
    // bounds and per-FB queue count, for allocated fill buffers (the
    // counters are only initialised on allocation)
    assert ((phase_q[1:0] == 2'd0) || beats_sent_q[1:0] <= 2'd2);
    assert ((phase_q[1:0] == 2'd0) || hit_q[0] || beats_rcvd_q[1:0] <= beats_sent_q[1:0]);
    assert ((phase_q[1:0] == 2'd0) || f_cnt0 == f_outs0);
    assert ((phase_q[3:2] == 2'd0) || beats_sent_q[3:2] <= 2'd2);
    assert ((phase_q[3:2] == 2'd0) || hit_q[1] || beats_rcvd_q[3:2] <= beats_sent_q[3:2]);
    assert ((phase_q[3:2] == 2'd0) || f_cnt1 == f_outs1);
    assert ((phase_q[5:4] == 2'd0) || beats_sent_q[5:4] <= 2'd2);
    assert ((phase_q[5:4] == 2'd0) || hit_q[2] || beats_rcvd_q[5:4] <= beats_sent_q[5:4]);
    assert ((phase_q[5:4] == 2'd0) || f_cnt2 == f_outs2);
    assert ((phase_q[7:6] == 2'd0) || beats_sent_q[7:6] <= 2'd2);
    assert ((phase_q[7:6] == 2'd0) || hit_q[3] || beats_rcvd_q[7:6] <= beats_sent_q[7:6]);
    assert ((phase_q[7:6] == 2'd0) || f_cnt3 == f_outs3);
    // a held bus request (not yet granted) belongs to a running fill buffer
    // that still owes a beat: it was picked with beats_sent < 2, and neither
    // beats_sent nor the buffer's release can move until its grant
    assert (!(bus_hold_valid_q && bus_hold_fb_q == 2'd0) || (phase_q[1:0] == 2'd3 && !hit_q[0] && beats_sent_q[1:0] < 2'd2));
    assert (!(bus_hold_valid_q && bus_hold_fb_q == 2'd1) || (phase_q[3:2] == 2'd3 && !hit_q[1] && beats_sent_q[3:2] < 2'd2));
    assert (!(bus_hold_valid_q && bus_hold_fb_q == 2'd2) || (phase_q[5:4] == 2'd3 && !hit_q[2] && beats_sent_q[5:4] < 2'd2));
    assert (!(bus_hold_valid_q && bus_hold_fb_q == 2'd3) || (phase_q[7:6] == 2'd3 && !hit_q[3] && beats_sent_q[7:6] < 2'd2));
    // an idle fill buffer has nothing on the bus
    assert (phase_q[1:0] != 2'd0 || f_cnt0 == 4'd0); assert (phase_q[3:2] != 2'd0 || f_cnt1 == 4'd0);
    assert (phase_q[5:4] != 2'd0 || f_cnt2 == 4'd0); assert (phase_q[7:6] != 2'd0 || f_cnt3 == 4'd0);
  end

  always @(posedge clk_i) if (rst_ni) begin
    // the lifecycle is 0 -> 1 -> 3 -> 0; phase 2 is never assigned
    assert (phase_q[1:0] != 2'd2); assert (phase_q[3:2] != 2'd2);
    assert (phase_q[5:4] != 2'd2); assert (phase_q[7:6] != 2'd2);
    // busy_q is set/cleared on the same edges as phase leaves/returns to 0
    assert (busy_q[0] == (phase_q[1:0] != 2'd0)); assert (busy_q[1] == (phase_q[3:2] != 2'd0));
    assert (busy_q[2] == (phase_q[5:4] != 2'd0)); assert (busy_q[3] == (phase_q[7:6] != 2'd0));
    assert (!(f_can_out(0) && f_can_out(1) && f_line(0) == f_line(1)));
    assert (!(f_can_out(0) && f_can_out(2) && f_line(0) == f_line(2)));
    assert (!(f_can_out(0) && f_can_out(3) && f_line(0) == f_line(3)));
    assert (!(f_can_out(1) && f_can_out(2) && f_line(1) == f_line(2)));
    assert (!(f_can_out(1) && f_can_out(3) && f_line(1) == f_line(3)));
    assert (!(f_can_out(2) && f_can_out(3) && f_line(2) == f_line(3)));
  end
`endif
`ifdef MISROUTE_COVER
  // A second bus grant, for a different FB, while the first grant's response
  // is still outstanding: bus_inflight_fb_q (1 deep) is then overwritten and
  // the first response would be routed to the second FB.
  always @(posedge clk_i) if (rst_ni) cover (bus_inflight_valid_q && !instr_rvalid_i
      && instr_req_o && instr_gnt_i && bus_grant_requester != bus_inflight_fb_q);
`endif
`ifdef CTI_COVER
  // Reachability of the induction counterexample: an output-done FB receiving
  // a trailing beat while another FB that can still output holds its line.
  wire [3:0] f_co = {f_can_out(3), f_can_out(2), f_can_out(1), f_can_out(0)};
  wire [3:0] f_dr;   // done, running, not stale, receiving a beat
  assign f_dr[0] = out_done_q[0] && phase_q[1:0] == 2'd3 && !stale_q[0] && rvalid_v[0];
  assign f_dr[1] = out_done_q[1] && phase_q[3:2] == 2'd3 && !stale_q[1] && rvalid_v[1];
  assign f_dr[2] = out_done_q[2] && phase_q[5:4] == 2'd3 && !stale_q[2] && rvalid_v[2];
  assign f_dr[3] = out_done_q[3] && phase_q[7:6] == 2'd3 && !stale_q[3] && rvalid_v[3];
  wire [28:0] f_l0 = addr_q[31:3], f_l1 = addr_q[63:35], f_l2 = addr_q[95:67], f_l3 = addr_q[127:99];
  wire f_twin =
    (f_dr[0] && ((f_co[1] && f_l1 == f_l0) || (f_co[2] && f_l2 == f_l0) || (f_co[3] && f_l3 == f_l0))) ||
    (f_dr[1] && ((f_co[0] && f_l0 == f_l1) || (f_co[2] && f_l2 == f_l1) || (f_co[3] && f_l3 == f_l1))) ||
    (f_dr[2] && ((f_co[0] && f_l0 == f_l2) || (f_co[1] && f_l1 == f_l2) || (f_co[3] && f_l3 == f_l2))) ||
    (f_dr[3] && ((f_co[0] && f_l0 == f_l3) || (f_co[1] && f_l1 == f_l3) || (f_co[2] && f_l2 == f_l3)));
  always @(posedge clk_i) if (rst_ni) cover (f_twin);
`endif
`endif
