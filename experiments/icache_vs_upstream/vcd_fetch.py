#!/usr/bin/env python3
"""Print per-cycle instruction-bus requests and icache data-RAM writes from a
COREMARK_VCD window (first-declared, i.e. top-most, signal of each name).

    vcd_fetch.py <w.vcd>
"""
import sys

WANT = ["IO_CLK", "instr_req_o", "instr_gnt_i", "instr_addr_o", "instr_rvalid_i",
        "ic_data_write_o", "ic_data_addr_o", "ic_data_req_o", "pc_id_o"]


def main(path):
    ids, val = {}, {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("$var"):
                f = line.split()
                if f[4] in WANT and f[4] not in ids.values():
                    ids.setdefault(f[3], f[4])
            if line.startswith("$enddefinitions"):
                break
        rising = False
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if line[0] == "#":
                continue
            if line[0] == "b":
                v, i = line[1:].split()
                if i in ids:
                    val[ids[i]] = int(v, 2) if "x" not in v else -1
            elif line[0] in "01xz" and line[1:] in ids:
                name = ids[line[1:]]
                val[name] = 1 if line[0] == "1" else 0
                if name == "IO_CLK" and val[name] == 1:
                    g = val.get
                    ev = []
                    if g("instr_req_o") and g("instr_gnt_i"):
                        ev.append(f"REQ {g('instr_addr_o', 0):08x}")
                    if g("instr_rvalid_i"):
                        ev.append("RVALID")
                    if g("ic_data_write_o") and g("ic_data_req_o"):
                        ev.append(f"RAMWR idx={g('ic_data_addr_o', 0):02x} way={g('ic_data_req_o')}")
                    print(f"pc_id={g('pc_id_o', 0):08x} " + " ".join(ev))


if __name__ == "__main__":
    main(sys.argv[1])
