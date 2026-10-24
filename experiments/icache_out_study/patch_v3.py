#!/usr/bin/env python3
"""V3: overlay after select (upstream-like single bypass).
The parent no longer builds four 64-bit live lines (IC1-hit / beat0 / beat1
overlays on fill_data_q, one per FB); the output stage selects the FB's
registered fill_data_q and applies the same-cycle bus beat once, after the
4:1 select. The IC1-hit overlay is dropped from the FB line: whenever the
selected FB is capturing an IC1 hit this cycle, ic1_covers is true for the
same line and the output already takes hit_data_ic1 (IC1 has data
priority). beats/err/wants_out overlays (narrow) are unchanged."""
import pathlib, sys
root = pathlib.Path(sys.argv[1])
p = root / "src/IbexIcacheOutputStage.arch"; s = p.read_text()
def rep(a, b, n=1):
    global s
    assert s.count(a) == n, (a, s.count(a)); s = s.replace(a, b)
rep("""  // Live FB candidates. Parent overlays same-cycle bus rvalid data into
  // fb*_line_live and fb*_beats_live before driving these ports.""",
"""  // FB candidates. fb*_line is the registered fill_data_q image; the
  // same-cycle bus beat is applied once, after the select (fb*_we_beat0/1 +
  // bus_rdata). The parent overlays same-cycle beats into fb*_beats_live.""")
rep("""  port fb3_line:       in UInt<64>;
""", """  port fb3_line:       in UInt<64>;
  port fb0_we_beat0:   in Bool;
  port fb1_we_beat0:   in Bool;
  port fb2_we_beat0:   in Bool;
  port fb3_we_beat0:   in Bool;
  port fb0_we_beat1:   in Bool;
  port fb1_we_beat1:   in Bool;
  port fb2_we_beat1:   in Bool;
  port fb3_we_beat1:   in Bool;
  port bus_rdata:      in UInt<32>;
""")
rep("""  let fb_sel_line: UInt<64> =
    (fb_sel_idx == 2'd0) ? fb0_line :
    ((fb_sel_idx == 2'd1) ? fb1_line :
    ((fb_sel_idx == 2'd2) ? fb2_line : fb3_line));""",
"""  let fb_sel_line_q: UInt<64> =
    (fb_sel_idx == 2'd0) ? fb0_line :
    ((fb_sel_idx == 2'd1) ? fb1_line :
    ((fb_sel_idx == 2'd2) ? fb2_line : fb3_line));
  let fb_sel_we0: Bool =
    (fb_sel_idx == 2'd0) ? fb0_we_beat0 :
    ((fb_sel_idx == 2'd1) ? fb1_we_beat0 :
    ((fb_sel_idx == 2'd2) ? fb2_we_beat0 : fb3_we_beat0));
  let fb_sel_we1: Bool =
    (fb_sel_idx == 2'd0) ? fb0_we_beat1 :
    ((fb_sel_idx == 2'd1) ? fb1_we_beat1 :
    ((fb_sel_idx == 2'd2) ? fb2_we_beat1 : fb3_we_beat1));
  // (exp V3) Same-cycle bus beat applied once, after the select.
  let fb_sel_line: UInt<64> =
    {(fb_sel_we1 ? bus_rdata : fb_sel_line_q[63:32]),
     (fb_sel_we0 ? bus_rdata : fb_sel_line_q[31:0])};""")
p.write_text(s)
p = root / "src/IbexIcache.arch"; s = p.read_text()
for i in range(4):
    rep(f"""  let fb{i}_line_live: UInt<64> =
    fb{i}_data_we_ic1_hit ? ic1_hit_data_combo :
    (fb{i}_data_we_beat0 ? {{fill_data_q[{i}][63:32], instr_rdata_i}} :
    (fb{i}_data_we_beat1 ? {{instr_rdata_i, fill_data_q[{i}][31:0]}} : fill_data_q[{i}]));
""", "")
rep("""  // Live per-FB output candidates for the elastic output resolver.
  // These overlay same-cycle IC1-hit and bus-rvalid data on top of the
  // registered fill_data_q image so the output stage can bypass without
  // waiting an extra clock for fill_data_q / beats_rcvd_q to update.""",
"""  // Live per-FB output candidates for the elastic output resolver.
  // (exp V3) The 64-bit line is NOT overlaid per FB any more: the output
  // stage selects fill_data_q and applies the same-cycle bus beat once.
  // beats/err/wants_out below still overlay same-cycle IC1-hit and
  // bus-rvalid state so the output stage can bypass without waiting an
  // extra clock for fill_data_q / beats_rcvd_q to update.""")
for i in range(4):
    rep(f"""    fb{i}_line           <- fb{i}_line_live;
""", f"""    fb{i}_line           <- fill_data_q[{i}];
""")
rep("""    fb0_err_beat0      <- fb0_err_beat0_live;""", """    fb0_we_beat0       <- fb0_data_we_beat0;
    fb1_we_beat0       <- fb1_data_we_beat0;
    fb2_we_beat0       <- fb2_data_we_beat0;
    fb3_we_beat0       <- fb3_data_we_beat0;
    fb0_we_beat1       <- fb0_data_we_beat1;
    fb1_we_beat1       <- fb1_data_we_beat1;
    fb2_we_beat1       <- fb2_data_we_beat1;
    fb3_we_beat1       <- fb3_data_we_beat1;
    bus_rdata          <- instr_rdata_i;
    fb0_err_beat0      <- fb0_err_beat0_live;""")
p.write_text(s)
print("V3 applied")
