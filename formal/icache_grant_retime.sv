// Can the coalesce comparison be retimed one cycle earlier?
//
// lookup_line_ic0 = (branch_i ? addr_i : prefetch_addr_q)[31:3]
//
//   prefetch leg : every input is a register, so the compare can be pushed
//                  back across them -- evaluate on the D side in cycle N-1
//                  and register the RESULT. Standard retiming.
//   branch  leg  : addr_i is the ALU adder's output in cycle N. No register
//                  sits between the adder and the compare, so there is
//                  nothing to retime across.
//
// Every register in the cone is modelled explicitly as Q <= D so the D-side
// (next-state) values the retiming needs actually exist in the model.
`define NFB 4
`define LINEW 29

module icache_grant_retime (
  input clk, rst_n,
  // D-side (next-cycle) values of every register in the coalesce cone
  input [`LINEW-1:0] prefetch_line_d, fb0_d, fb1_d, fb2_d, fb3_d, alloc_addr_d,
  input [`NFB-1:0]   busy_d, stale_d,
  input              alloc_d,
  // same-cycle inputs
  input              branch_i, lookup_req_ic0, fb_full, fill_write_req,
  input [`LINEW-1:0] addr_i_line,   // ALU adder output -- exists only in cycle N
  input [`LINEW-1:0] alt_line       // second line for the independence miter
);
  // ── the registers ────────────────────────────────────────────────────
  reg [`LINEW-1:0] prefetch_line_q, fb0_q, fb1_q, fb2_q, fb3_q, alloc_addr_q;
  reg [`NFB-1:0]   busy_q, stale_q, h1, h2, h3, h4;
  reg              alloc_q;
  always @(posedge clk) begin
    prefetch_line_q<=prefetch_line_d; fb0_q<=fb0_d; fb1_q<=fb1_d; fb2_q<=fb2_d;
    fb3_q<=fb3_d; alloc_addr_q<=alloc_addr_d; busy_q<=busy_d; stale_q<=stale_d;
    alloc_q<=alloc_d; h1<=busy_q; h2<=h1; h3<=h2; h4<=h3;
  end
  wire [`NFB-1:0] recent_q = busy_q | h1 | h2 | h3 | h4;
  // the D-side mirror of recent_q: what recent_q will be next cycle
  wire [`NFB-1:0] recent_d = busy_d | busy_q | h1 | h2 | h3;

  // ── coalesce, Q side (what the design computes today) ────────────────
  function automatic co_q(input [`LINEW-1:0] line);
    co_q = ((recent_q[0] & ~stale_q[0] & (fb0_q==line)) |
            (recent_q[1] & ~stale_q[1] & (fb1_q==line)) |
            (recent_q[2] & ~stale_q[2] & (fb2_q==line)) |
            (recent_q[3] & ~stale_q[3] & (fb3_q==line)))
           | (alloc_q & (alloc_addr_q==line));
  endfunction
  // ── coalesce, D side (the same function on next-state values) ────────
  function automatic co_d(input [`LINEW-1:0] line);
    co_d = ((recent_d[0] & ~stale_d[0] & (fb0_d==line)) |
            (recent_d[1] & ~stale_d[1] & (fb1_d==line)) |
            (recent_d[2] & ~stale_d[2] & (fb2_d==line)) |
            (recent_d[3] & ~stale_d[3] & (fb3_d==line)))
           | (alloc_d & (alloc_addr_d==line));
  endfunction

  wire [`LINEW-1:0] line_now = branch_i ? addr_i_line : prefetch_line_q;

  // RETIMED prefetch-leg result: computed in cycle N-1 from D-side values
  // against the D-side prefetch line, then registered.
  reg retimed_prefetch_q;
  always @(posedge clk) retimed_prefetch_q <= co_d(prefetch_line_d);

  reg p1=1'b0,p2=1'b0,rq=1'b0;
  always @(posedge clk) begin p1<=1'b1; p2<=p1; rq<=rst_n; end
  wire steady = rst_n && rq && p2;

`ifdef RETIME_SOUND
  // Is the retimed prefetch-leg compare equal to computing it live?
  always @(posedge clk) if (steady) assert (retimed_prefetch_q == co_q(prefetch_line_q));
`endif

`ifdef RETIME_BRANCH_ATTEMPT
  // Try to retime the BRANCH leg the same way. There is no earlier copy of
  // addr_i, so the only candidate is last cycle's adder output.
  reg [`LINEW-1:0] addr_i_line_q;
  always @(posedge clk) addr_i_line_q <= addr_i_line;
  reg retimed_branch_q;
  always @(posedge clk) retimed_branch_q <= co_d(addr_i_line_q);
  always @(posedge clk) if (steady) assert (retimed_branch_q == co_q(line_now));
`endif

`ifdef CANDIDATE_INDEP
  // Candidate: retimed prefetch leg, and on a branch fall back to a
  // conservative constant (yield to fill) instead of comparing the address.
  function automatic grant_cand(input [`LINEW-1:0] line);
    reg co;
    begin
      co = branch_i ? 1'b1 : retimed_prefetch_q;
      grant_cand = lookup_req_ic0 & ~((co | fb_full) & fill_write_req);
    end
  endfunction
  always @(posedge clk) if (steady)
    assert (grant_cand(line_now) == grant_cand(alt_line));
`endif

`ifdef CANDIDATE_CONSERVATIVE
  // Liveness direction: the candidate must yield at least as often as today
  // (today's coalesce implies the candidate's), so fill is never starved
  // more than it is now.
  wire co_today = co_q(line_now);
  wire co_cand  = branch_i ? 1'b1 : retimed_prefetch_q;
  always @(posedge clk) if (steady) assert (!co_today || co_cand);
`endif
endmodule
