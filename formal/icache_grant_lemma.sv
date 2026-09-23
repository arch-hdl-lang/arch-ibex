// Formal harness for the icache `lookup_grant` timing rewrite.
//
// Context: `da9059f` (fix Bug C -- writeback starvation) changed
//     lookup_grant = lookup_req_ic0;                              // upstream
// to
//     lookup_grant = lookup_req_ic0 && !((coalesce_ic0 || fb_full) && fill_write_req);
// which put a 4-way fill-buffer line-tag comparison against lookup_addr_ic0
// onto the icache RAM grant. On a branch lookup_addr_ic0 is the ALU adder's
// output, so the RAM request now sits behind the adder: post-P&R the Arch
// lane's 5 worst paths all run
//     IF/ID instr reg -> ALU adder -> FB tag compare -> lookup_grant
//                     -> icache RAM req -> 16K-flop fanout -> rdata reg
// at -15.07 ns WNS vs the SV lane's -9.66 ns.
//
// Two properties, selected by `define:
//
//   COALESCE_LEMMA  -- is a registered coalesce term equivalent to the
//                      combinational one? (the "just register it" rewrite)
//   GRANT_INDEP     -- is `lookup_grant` independent of the lookup address?
//                      This is the timing question stated formally: two
//                      copies with identical fill-buffer state but different
//                      lookup lines must produce the same grant. Upstream's
//                      grant satisfies it; the current one does not. Any
//                      candidate rewrite must satisfy it to get the adder
//                      off the RAM path -- necessary, not sufficient
//                      (liveness is a separate obligation).
//
// Widths and structure follow src/IbexIcache.arch: 4 fill buffers, line tag
// = addr[31:3] (29 bits), fb_busy_recent_mask = fb_busy_mask OR'd with four
// cycles of history, and pending_alloc_match_ic0 off the IC1 registers.

`define NFB 4
`define LINEW 29

module icache_grant_lemma (
  input                    clk, rst_n,
  // lookup address formation: lookup_addr_ic0 = branch_i ? addr_i : prefetch_addr_q
  input                    branch_i,
  input       [31:0]       addr_i, prefetch_addr_q,
  // a second, independent lookup line for the GRANT_INDEP two-copy miter
  input       [`LINEW-1:0] alt_line,
  // fill-buffer state (all registers in the design)
  input       [`NFB-1:0]   fb_busy_mask, stale_q,
  input       [`LINEW-1:0] fb0_addr, fb1_addr, fb2_addr, fb3_addr,
  // IC1-stage pending-allocate bypass
  input                    lookup_alloc_ic1_q,
  input       [`LINEW-1:0] lookup_addr_ic1_q,
  // grant inputs
  input                    lookup_req_ic0, fb_full, fill_write_req
);
  wire [31:0]       lookup_addr_ic0 = branch_i ? addr_i : prefetch_addr_q;
  wire [`LINEW-1:0] lookup_line_ic0 = lookup_addr_ic0[31:3];

  // fb_busy_recent_mask = fb_busy_mask | prev1..prev4   (IbexIcache.arch:556)
  reg [`NFB-1:0] p1, p2, p3, p4;
  always @(posedge clk)
    if (!rst_n) begin p1<=0; p2<=0; p3<=0; p4<=0; end
    else        begin p1<=fb_busy_mask; p2<=p1; p3<=p2; p4<=p3; end
  wire [`NFB-1:0] fb_busy_recent_mask = fb_busy_mask | p1 | p2 | p3 | p4;

  // coalesce_ic0, parameterised on which line is being looked up
  function automatic coalesce_of(input [`LINEW-1:0] line);
    begin
      coalesce_of =
        ((fb_busy_recent_mask[0] & ~stale_q[0] & (fb0_addr == line)) |
         (fb_busy_recent_mask[1] & ~stale_q[1] & (fb1_addr == line)) |
         (fb_busy_recent_mask[2] & ~stale_q[2] & (fb2_addr == line)) |
         (fb_busy_recent_mask[3] & ~stale_q[3] & (fb3_addr == line)))
        | (lookup_alloc_ic1_q & (lookup_addr_ic1_q == line));
    end
  endfunction

  wire coalesce_comb = coalesce_of(lookup_line_ic0);

  reg past1 = 1'b0, past2 = 1'b0, rst_q = 1'b0;
  always @(posedge clk) begin past1<=1'b1; past2<=past1; rst_q<=rst_n; end
  wire steady = rst_n && rst_q && past2;

`ifdef COALESCE_LEMMA
  // the "just register it" rewrite
  reg coalesce_q;
  always @(posedge clk) if (!rst_n) coalesce_q <= 1'b0; else coalesce_q <= coalesce_comb;

  // stability of the WHOLE cone, not just the address
  reg [`LINEW-1:0] s_line, s_f0, s_f1, s_f2, s_f3, s_a1;
  reg [`NFB-1:0]   s_mask, s_stale, s_recent;
  reg              s_alloc;
  always @(posedge clk) begin
    s_line<=lookup_line_ic0; s_f0<=fb0_addr; s_f1<=fb1_addr; s_f2<=fb2_addr; s_f3<=fb3_addr;
    s_mask<=fb_busy_mask; s_stale<=stale_q; s_recent<=fb_busy_recent_mask;
    s_alloc<=lookup_alloc_ic1_q; s_a1<=lookup_addr_ic1_q;
  end
  wire cone_stable = (s_line==lookup_line_ic0) && (s_f0==fb0_addr) && (s_f1==fb1_addr)
                  && (s_f2==fb2_addr) && (s_f3==fb3_addr) && (s_mask==fb_busy_mask)
                  && (s_stale==stale_q) && (s_recent==fb_busy_recent_mask)
                  && (s_alloc==lookup_alloc_ic1_q) && (s_a1==lookup_addr_ic1_q);
  `ifdef ASSUME_STABLE
  always @(posedge clk) if (rst_n) assume (cone_stable);
  `endif
  `ifdef IMPLIES
  always @(posedge clk) if (steady) assert (!coalesce_comb || coalesce_q);
  `else
  always @(posedge clk) if (steady) assert (coalesce_q == coalesce_comb);
  `endif
`endif

`ifdef GRANT_INDEP
  // Two copies: identical fill-buffer state, different lookup line.
  // `grant_of` is the design under test.
  function automatic grant_of(input [`LINEW-1:0] line);
    begin
  `ifdef GRANT_PREFIX
      // upstream / pre-da9059f: lookup_grant_ic0 = lookup_req_ic0
      grant_of = lookup_req_ic0;
  `else
      // current: address-dependent
      grant_of = lookup_req_ic0 & ~((coalesce_of(line) | fb_full) & fill_write_req);
  `endif
    end
  endfunction
  always @(posedge clk) if (steady)
    assert (grant_of(lookup_line_ic0) == grant_of(alt_line));
`endif
endmodule
