`ifdef FORMAL
  // Bounded liveness for Bug C: a fill buffer waiting to write back
  // (fill_write_req) must be granted within STARVE_N cycles. Cycles where
  // the invalidation walk holds the RAM port are excluded: inval has
  // priority by design and is bounded by the walk itself.
  reg [7:0] f_starve = 8'd0;
  always @(posedge clk_i)
    if (!rst_ni) f_starve <= 8'd0;
    else if (fill_write_req && !fill_grant && !inval_write_req)
      f_starve <= (f_starve == 8'hff) ? 8'hff : f_starve + 8'd1;
    else f_starve <= 8'd0;
  always @(posedge clk_i) if (rst_ni) assert (f_starve < `STARVE_N);
`ifdef COVERS
  // Non-vacuity: under the same assumptions the interesting states must be
  // reachable, or a PASS proves nothing.
  always @(posedge clk_i) if (rst_ni) cover (fill_write_req && branch_i);
  always @(posedge clk_i) if (rst_ni) cover (fill_write_req && f_starve == 8'd12);
`endif
`endif
