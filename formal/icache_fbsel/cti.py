#!/usr/bin/env python3
"""Print fill-buffer state per step of an SBY VCD trace (vectors MSB-first = fb3..fb0)."""
import sys
txt = open(sys.argv[1]).read()
hdr, body = txt.split('$enddefinitions $end')
scope = []; ids = {}
for line in hdr.split('\n'):
    t = line.split()
    if not t: continue
    if t[0] == '$scope': scope.append(t[2])
    elif t[0] == '$upscope': scope.pop()
    elif t[0] == '$var': ids.setdefault(t[3], []).append('.'.join(scope + [t[4]]))
want = {'u_icache.phase_q': 'phase', 'u_icache.stale_q': 'stale', 'u_icache.out_done_q': 'odone',
        'u_icache.wants_out_v': 'want', 'u_icache.rvalid_v': 'rv', 'u_icache.data_we_ic1_hit_v': 'ic1',
        'u_icache.beats_rcvd_q': 'rcvd', 'u_icache.hit_q': 'hit', 'u_icache.alloc_q': 'alloc',
        'output_stage.source_line_addr': 'src', 'bus_resp_q.wr_ptr': 'wr', 'bus_resp_q.rd_ptr': 'rd', 'bus_resp_q.pop_data': 'head', 'bus_resp_q.bypass_valid': 'byp', 'u_icache.beats_sent_q': 'sent', 'live_top.outstanding': 'envout', 'u_icache.addr_q': 'addr', 'output_stage.f_ncand': 'ncand'}
for n in ('fb0_wants_out', 'fb1_wants_out', 'fb2_wants_out', 'fb3_wants_out'): want['output_stage.' + n] = n
sel = {i: want[k] for i, ns in ids.items() for n in ns for k in want if n.endswith(k)}
cur = {}; rows = []; t = None
for line in body.split('\n'):
    line = line.strip()
    if not line: continue
    if line[0] == '#':
        if t is not None: rows.append(dict(cur))
        t = int(line[1:]); continue
    v, i = (line[1:].split() if line[0] == 'b' else (line[0], line[1:]))
    if i in sel: cur[sel[i]] = v
rows.append(dict(cur))
def h(x): return hex(int(x, 2)) if x and all(c in '01' for c in x) else '?'
prev = None
for k, c in enumerate(rows):
    key = tuple(sorted(c.items()))
    if key == prev: continue
    prev = key
    a = c.get('addr', '')
    lines = [h(a[::-1][32*f+3:32*f+32][::-1]) for f in range(4)] if len(a) == 128 else '?'
    live = ''.join(c.get(f'fb{f}_wants_out', '?') for f in (3, 2, 1, 0))
    print(f"row{k}: phase {c.get('phase')} stale {c.get('stale')} odone {c.get('odone')} hit {c.get('hit')} alloc {c.get('alloc')} "
          f"rcvd {c.get('rcvd')} want {c.get('want')} live {live} rv {c.get('rv')} ic1 {c.get('ic1')} "
          f"sent {c.get('sent')} wr {c.get('wr')} rd {c.get('rd')} head {c.get('head')} byp {c.get('byp')} envout {c.get('envout')} src {h(c.get('src'))} lines(fb0..3) {lines} ncand {h(c.get('ncand'))}")
