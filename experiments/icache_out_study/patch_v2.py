#!/usr/bin/env python3
"""V2: remove the output stage's backpressure hold register (hold_*_q).
valid_o/rdata_o come straight from the (IC1 / IC1-hold / FB / skid) resolver,
as upstream Ibex does; stability under ready_i=0 relies on the sources
staying put (IC1 hold line, FB data until out_done, skid until accept)."""
import pathlib, sys
root = pathlib.Path(sys.argv[1])
p = root / "src/IbexIcacheOutputStage.arch"; s = p.read_text()
def rep(a, b, n=1):
    global s
    assert s.count(a) == n, (a, s.count(a)); s = s.replace(a, b)
rep("""/// This block owns only the IF-facing stream position (`addr_out_q`), a
/// one-entry hold register for backpressure, and the misaligned-32 skid
/// halfword.""", """/// This block owns only the IF-facing stream position (`addr_out_q`), the
/// IC1 hold line and the misaligned-32 skid halfword. (exp V2: no
/// backpressure hold register; under ready_i=0 the output is held by its
/// sources -- IC1 hold line, FB data until out_done, skid until accept.)""")
rep("""  reg hold_valid_q:     Bool reset rst_ni => false;
  reg hold_rdata_q:     UInt<32> guard hold_valid_q reset none;
  reg hold_err_q:       Bool guard hold_valid_q reset none;
  reg hold_err_plus2_q: Bool guard hold_valid_q reset none;
  reg hold_done_q:      Bool guard hold_valid_q reset none;
  reg hold_done_idx_q:  UInt<2> guard hold_valid_q reset none;

""", "")
rep("""  let need_skid_load: Bool =
    (not hold_valid_q)
    and raw_valid""", """  let need_skid_load: Bool =
    raw_valid""")
rep("""  let out_valid_comb: Bool = hold_valid_q or nonheld_valid;
  let out_rdata_comb: UInt<32> = hold_valid_q ? hold_rdata_q : nonheld_rdata;
  let out_err_comb: Bool = hold_valid_q ? hold_err_q : nonheld_err;
  let out_err_plus2_comb: Bool =
    hold_valid_q ? hold_err_plus2_q : nonheld_err_plus2;""", """  let out_valid_comb: Bool = nonheld_valid;
  let out_rdata_comb: UInt<32> = nonheld_rdata;
  let out_err_comb: Bool = nonheld_err;
  let out_err_plus2_comb: Bool = nonheld_err_plus2;""")
rep("""  let accept_done: Bool =
    (hold_valid_q and hold_done_q)
    or ((not hold_valid_q) and nonheld_valid and source_done_on_accept);
  let accept_done_idx: UInt<2> =
    hold_valid_q ? hold_done_idx_q : raw_fb_idx;""", """  let accept_done: Bool = nonheld_valid and source_done_on_accept;
  let accept_done_idx: UInt<2> = raw_fb_idx;""")
rep("""  seq on clk_i rising
    if branch_i
      hold_valid_q <= false;
    elsif hold_valid_q
      if ready_i
        hold_valid_q <= false;
      end if
    elsif nonheld_valid and (not ready_i)
      hold_valid_q     <= true;
      hold_rdata_q     <= nonheld_rdata;
      hold_err_q       <= nonheld_err;
      hold_err_plus2_q <= nonheld_err_plus2;
      hold_done_q      <= source_done_on_accept;
      hold_done_idx_q  <= raw_fb_idx;
    end if
  end seq

""", "")
rep("""    elsif nonheld_valid and (skid_complete_instr or skid_bridge_valid)
      // The full instruction has been materialized either directly on
      // the bus or in the hold register; the skid halfword is no longer
      // needed even if ready_i is low this cycle.
      skid_valid_q <= false;""", """    elsif accept_output and (skid_complete_instr or skid_bridge_valid)
      // (exp V2) No hold register: the skid halfword is part of the
      // presented instruction and stays until the IF stage accepts it.
      skid_valid_q <= false;""")
p.write_text(s)
# Test helper: _snapshot reads output_stage.hold_valid_q (diagnostic only).
t = root / "tests/cocotb_tests/test_ibex_icache_unit.py"; s = t.read_text()
rep("""        "hold_valid_q":      int(out.hold_valid_q.value),""",
    """        "hold_valid_q":      (int(out.hold_valid_q.value)
                              if hasattr(out, "hold_valid_q") else 0),""")
t.write_text(s)
print("V2 applied")
