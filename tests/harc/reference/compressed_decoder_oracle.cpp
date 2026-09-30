// Independent upstream Ibex RTL oracle. Each row is sampled AFTER one rising
// edge with its inputs; HARC's wait 1 cycle uses the same observation boundary.
#include "Vibex_compressed_decoder.h"
#include <cstdint>
#include <fstream>
#include <stdexcept>
#include <vector>

struct Row { uint32_t rst, valid, ready, instr, out, compressed, illegal, expanded, phase; };
int main(int argc, char** argv) {
    if (argc != 2) throw std::runtime_error("expected output path");
    Vibex_compressed_decoder d;
    std::vector<Row> rows;
    auto step = [&](uint32_t instr, bool valid, bool ready, bool rst = true) {
        d.clk_i=0; d.rst_ni=rst; d.valid_i=valid; d.id_in_ready_i=ready; d.instr_i=instr; d.eval();
        d.clk_i=1; d.eval();
        Row r{uint32_t(rst),uint32_t(valid),uint32_t(ready),instr,d.instr_o,
              d.is_compressed_o,d.illegal_instr_o,d.gets_expanded_o,0};
        // Unmasked, ready-independent phase: probe valid=ready=1 without an edge.
        d.valid_i=1; d.id_in_ready_i=1; d.eval(); r.phase=r.illegal ? 0 : d.gets_expanded_o;
        d.valid_i=valid; d.id_in_ready_i=ready; d.eval();
        rows.push_back(r);
        return r;
    };
    auto reset = [&]() { step(0,0,0,false); };
    // Exhaustive 16-bit decode at both valid levels, with low/high upper halves.
    for (uint32_t word=0; word<65536; ++word) {
        for (uint32_t upper : {0u,0xffff0000u}) {
            reset(); step(upper|word,0,0); step(upper|word,0,1); step(upper|word,1,0);
        }
    }
    for (uint32_t word : {0x00100093u,0x00100073u,0xdeadbeefu,0x5555aaa3u,0xaaaa5557u}) {
        reset(); for (int valid=0;valid<2;++valid) for(int ready=0;ready<2;++ready) step(word,valid,ready);
    }
    // Every legal multi-cycle encoding: normal walk, invalid-ready advancement,
    // stalled valid/invalid samples at every phase, and reset interruption at
    // every possible expansion step. No generated DUT outputs enter this model.
    for (uint32_t word=0;word<65536;++word) {
        reset(); auto first=step(word,1,0);
        if (first.illegal || first.phase!=1) continue;
        for (int invalid=0;invalid<2;++invalid) {
            reset(); step(word,1,0);
            bool ended=false;
            for(int n=0;n<20;++n) {
                step(word,0,0); auto held=step(word,1,0);
                if(held.phase==2) { step(word,!invalid,1); ended=true; break; }
                step(word,invalid && n>0 ? 0:1,1);
            }
            if(!ended) throw std::runtime_error("Zcmp watchdog");
        }
        // Each prefix is reset independently, including all internal states.
        for(int prefix=0;prefix<16;++prefix) {
            reset(); step(word,1,0);
            bool last=false;
            for(int n=0;n<prefix;++n) { auto r=step(word,1,1); if(r.phase==2) {last=true;break;} }
            reset(); step(word,1,0);
            if(last) break;
        }
    }
    // Defensive producer-contract violation: reserved move selector while
    // expansion is active. Flags remain defined; restore and verify state.
    for(uint32_t bad : {0xac02u,0xac42u}) {
        reset(); step(0xac22,1,0); step(0xac22,1,1);
        step(bad,1,0); step(bad,1,1); step(0xac22,1,0);
    }
    std::ofstream out(argv[1]);
    if(!out) throw std::runtime_error("cannot open vectors");
    out << rows.size() << '\n';
    for(auto r:rows) out << r.rst << ' ' << r.valid << ' ' << r.ready << ' ' << r.instr << ' '
        << r.out << ' ' << r.compressed << ' ' << r.illegal << ' ' << r.expanded << ' ' << r.phase << '\n';
    if(!out) throw std::runtime_error("vector write failed");
}
