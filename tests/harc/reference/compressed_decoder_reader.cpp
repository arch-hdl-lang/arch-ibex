// Strict corpus transport; expectations were produced by independent RTL.
#include <array>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>
namespace {
using Row=std::array<uint64_t,9>;
std::vector<Row> rows;
uint64_t next_row=0;
void load() {
    if(!rows.empty()) return;
    const char* path=std::getenv("IBEX_DECODER_VECTORS");
    if(!path) throw std::runtime_error("missing IBEX_DECODER_VECTORS");
    std::ifstream in(path);
    uint64_t count=0;
    if(!(in>>count) || count==0 || count>2000000) throw std::runtime_error("invalid vector count");
    rows.resize(count);
    for(auto& r:rows) {
        for(auto& v:r) if(!(in>>v)) throw std::runtime_error("truncated/malformed vectors");
        if(r[0]>1||r[1]>1||r[2]>1||r[3]>UINT32_MAX||r[4]>UINT32_MAX||r[5]>1||r[6]>1||r[7]>2||r[8]>2)
            throw std::runtime_error("out-of-range vector field");
    }
    std::string extra;
    if(in>>extra) throw std::runtime_error("extra vector data");
}
}
extern "C" uint64_t cd_count() { load(); return rows.size(); }
extern "C" uint64_t cd_field(uint64_t row,uint64_t col) {
    load(); if(row!=next_row||row>=rows.size()||col>=9) throw std::runtime_error("invalid vector access");
    return rows[row][col];
}
extern "C" uint64_t cd_accept(uint64_t row) {
    if(row!=next_row||row>=rows.size()) throw std::runtime_error("invalid vector acceptance");
    return ++next_row;
}
extern "C" uint64_t cd_finish() {
    if(rows.empty()||next_row!=rows.size()) throw std::runtime_error("unconsumed vectors");
    return next_row;
}
