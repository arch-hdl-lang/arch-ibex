// Random differential co-simulation driver for dual.v (see mk.py).
//   cosim <seed> <cycles> <equiv:0|1> <err:0|1> [profile]
#include "Vdual.h"
#include "verilated.h"
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <random>

static uint32_t hash32(uint32_t x) {
  x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16; return x;
}
static uint32_t g_salt = 0; static int g_rv32 = 0;
static uint32_t mem_word(uint32_t a) {
  uint32_t h = hash32((a >> 2) ^ g_salt);
  uint32_t w = h;
  // ~50% 32-bit instructions per halfword position
  w = (w & ~0x3u) | (((h >> 20) & 1) ? 3u : ((h >> 21) % 3));
  w = (w & ~0x30000u) | ((((h >> 23) & 1) ? 3u : ((h >> 24) % 3)) << 16);
  if (g_rv32) w |= 0x30003u;
  return w;
}
static uint32_t mem_half(uint32_t a) { return (mem_word(a & ~3u) >> ((a & 2) ? 16 : 0)) & 0xffff; }
static bool mem_err(uint32_t a, int errmode) { return errmode && (hash32((a >> 2) * 2654435761u ^ 0xabcdu) % 64 == 0); }

struct Bus {
  std::mt19937 rng;
  struct Rsp { uint32_t addr; uint64_t ready_at; };
  std::deque<Rsp> q;
  int gnt_pct, max_lat;
  bool rvalid = false; uint32_t rdata = 0; bool rerr = false; bool gnt = false;
  Bus(uint32_t seed, int g, int l) : rng(seed), gnt_pct(g), max_lat(l) {}
  void pre(uint64_t cyc, int errmode) {
    rvalid = !q.empty() && q.front().ready_at <= cyc;
    rdata = rvalid ? mem_word(q.front().addr) : (uint32_t)rng();
    rerr = rvalid ? mem_err(q.front().addr, errmode) : false;
  }
  void decide(bool req) { gnt = req && (int)(rng() % 100) < gnt_pct; }
  void post(uint64_t cyc, bool req, uint32_t addr) {
    if (rvalid) q.pop_front();
    if (req && gnt) q.push_back({addr, cyc + 1 + rng() % max_lat});
  }
};

struct Side {
  const char* name;
  bool exp_valid = false; uint32_t exp_pc = 0; bool err_seen = false;
  bool p_hold = false; uint32_t p_rdata = 0, p_addr = 0; bool p_err = false, p_e2 = false;
  uint64_t known_skid = 0, no_progress = 0, accepts = 0, max_no_progress = 0, stall_cycles = 0, rout2_checks = 0;
  long errors = 0;
};

static long total_errors = 0;
#define FAIL(...) do { if (total_errors < 20) { std::printf(__VA_ARGS__); std::printf("\n"); } total_errors++; } while (0)

int main(int argc, char** argv) {
  uint32_t seed = argc > 1 ? atoi(argv[1]) : 1;
  uint64_t cycles = argc > 2 ? strtoull(argv[2], 0, 10) : 100000;
  int equiv = argc > 3 ? atoi(argv[3]) : 1;
  int errmode = argc > 4 ? atoi(argv[4]) : 0;
  int profile = argc > 5 ? atoi(argv[5]) : (int)(seed % 4);
  int flags = argc > 6 ? atoi(argv[6]) : 0;  // 1: no inval, 2: no enable toggles, 4: no far-tag branches
  g_salt = hash32(seed * 7919u);
  g_rv32 = argc > 6 && (atoi(argv[6]) & 16);
  // profiles: bus grant %, max latency, ready %, branch per-mille, region lines
  int gnt_pct[] = {70, 40, 95, 60}, max_lat[] = {3, 6, 1, 4}, ready_pct[] = {70, 50, 90, 30};
  int br_pm[] = {40, 15, 80, 25};
  Verilated::commandArgs(argc, argv);
  Vdual* t = new Vdual;
  std::mt19937 rng(seed);
  Bus bR(seed * 3 + 1, gnt_pct[profile], max_lat[profile]);
  Bus bD(seed * 3 + 1, gnt_pct[profile], max_lat[profile]);
  Side sR{"REF"}, sD{"DUT"};
  bool req = false, en = true; int req_off = 0;
  const uint64_t STALL_MAX = 400;
  uint64_t equiv_checks = 0;
  for (uint64_t cyc = 0; cyc < cycles; cyc++) {
    // ---- inputs for this cycle (clk low) ----
    t->clk = 0;
    t->rst_ni = cyc >= 4;
    bool started = cyc >= 280;            // past the cold-boot invalidation walk
    if (req_off > 0) { req_off--; req = false; }
    else { req = started; if (started && rng() % 1000 < 3) req_off = 1 + rng() % 8; }
    bool branch = req && (cyc == 280 || ((flags & 8) ? (rng() % 20000 == 0) : ((int)(rng() % 1000) < br_pm[profile])));
    uint32_t base = (rng() % 8 == 0 && !(flags & 4)) ? 0x20000000u : 0x10000000u;   // same index, other tag: way conflicts
    uint32_t region = (profile == 1) ? 4096 : 1024;
    uint32_t addr = base + (rng() % region) * 2;
    if (g_rv32) addr &= ~3u;
    bool ready = req && (int)(rng() % 100) < ready_pct[profile];
    bool inval = started && rng() % 20000 == 0 && !(flags & 1);
    if (started && rng() % 50000 == 0 && !(flags & 2)) en = !en;
    if (inval) std::printf("[cyc %llu] INVAL pulse\n", (unsigned long long)cyc);
    t->req_i = req; t->branch_i = branch; t->addr_i = addr; t->ready_i = ready;
    t->icache_enable_i = en; t->icache_inval_i = inval;
    bR.pre(cyc, errmode); bD.pre(cyc, errmode);
    t->instr_rvalid_i_R = bR.rvalid; t->instr_rdata_i_R = bR.rdata; t->instr_err_i_R = bR.rerr;
    t->instr_rvalid_i_D = bD.rvalid; t->instr_rdata_i_D = bD.rdata; t->instr_err_i_D = bD.rerr;
    t->instr_gnt_i_R = 0; t->instr_gnt_i_D = 0;
    t->eval();
    bR.decide(t->instr_req_o_R); bD.decide(t->instr_req_o_D);
    t->instr_gnt_i_R = bR.gnt; t->instr_gnt_i_D = bD.gnt;
    t->eval();
#ifdef DBG_DUT
    {
      static long dbg = getenv("DBG") ? atol(getenv("DBG")) : -100;
      static long dbgw = getenv("DBGW") ? atol(getenv("DBGW")) : 8;
      if ((long)cyc >= dbg - dbgw && (long)cyc <= dbg + 1) {
        auto* r = t->rootp;
#define OS(x) (unsigned long)r->dual__DOT__u_D__DOT__output_stage__DOT__##x
#define IC(x) (unsigned long)r->dual__DOT__u_D__DOT__##x
        std::printf("DBG cyc %llu: rdy=%d br=%d v=%d a=%08x | ic1cov=%lu holdcov=%lu fbany=%lu holdv=%lu holda=%07lx srcline=%07lx | wants=%lu%lu%lu%lu busy=%lx open=%lu%lu%lu%lu fbsel=%lu | lkv=%lu hit=%lu lka=%08lx skidv=%lu beats=%lu,%lu,%lu,%lu\n",
          (unsigned long long)cyc, (int)t->ready_i, (int)t->branch_i, (int)t->valid_o_D, t->addr_o_D,
          OS(ic1_covers), OS(ic1_hold_covers), OS(fb_any), OS(ic1_hold_valid_q), OS(ic1_hold_addr_q), OS(source_line_addr),
          IC(fb0_wants_out_live), IC(fb1_wants_out_live), IC(fb2_wants_out_live), IC(fb3_wants_out_live), IC(fb_busy_mask),
          OS(fb0_open), OS(fb1_open), OS(fb2_open), OS(fb3_open), OS(fb_sel_idx),
          IC(lookup_valid_ic1_q), IC(any_hit_ic1), IC(lookup_addr_ic1_q), OS(skid_valid_q),
          OS(fb0_beats_live), OS(fb1_beats_live), OS(fb2_beats_live), OS(fb3_beats_live));
      }
    }
#endif
    // ---- checks on the settled pre-edge outputs ----
    if (t->rst_ni) {
      struct O { bool v; uint32_t rd, a; bool e, e2, rq; uint32_t ra; };
      O oR{(bool)t->valid_o_R, t->rdata_o_R, t->addr_o_R, (bool)t->err_o_R, (bool)t->err_plus2_o_R, (bool)t->instr_req_o_R, t->instr_addr_o_R};
      O oD{(bool)t->valid_o_D, t->rdata_o_D, t->addr_o_D, (bool)t->err_o_D, (bool)t->err_plus2_o_D, (bool)t->instr_req_o_D, t->instr_addr_o_D};
      if (equiv) {
        equiv_checks++;
        bool bad = oR.v != oD.v || oR.a != oD.a || oR.rq != oD.rq || (oR.rq && oR.ra != oD.ra)
                || (oR.v && (oR.rd != oD.rd || oR.e != oD.e || oR.e2 != oD.e2))
                || t->tag_req_o_R != t->tag_req_o_D || t->data_req_o_R != t->data_req_o_D
                || (t->tag_req_o_R && (t->tag_we_o_R != t->tag_we_o_D || t->tag_addr_o_R != t->tag_addr_o_D
                                       || (t->tag_we_o_R && t->tag_wd_o_R != t->tag_wd_o_D)))
                || (t->data_req_o_R && (t->data_we_o_R != t->data_we_o_D || t->data_addr_o_R != t->data_addr_o_D
                                        || (t->data_we_o_R && t->data_wd_o_R != t->data_wd_o_D)))
                || t->busy_o_R != t->busy_o_D;
        if (bad) FAIL("[cyc %llu] EQUIV mismatch: REF v=%d a=%08x rd=%08x e=%d e2=%d rq=%d ra=%08x | DUT v=%d a=%08x rd=%08x e=%d e2=%d rq=%d ra=%08x",
                      (unsigned long long)cyc, oR.v, oR.a, oR.rd, oR.e, oR.e2, oR.rq, oR.ra, oD.v, oD.a, oD.rd, oD.e, oD.e2, oD.rq, oD.ra);
      }
      Side* ss[2] = {&sR, &sD}; O* oo[2] = {&oR, &oD};
      for (int i = 0; i < 2; i++) {
        Side& s = *ss[i]; O& o = *oo[i];
        // R-OUT-2 (checked against the previous cycle's hold condition)
        if (s.p_hold) {
          s.rout2_checks++;
          if (!o.v || o.rd != s.p_rdata || o.a != s.p_addr || o.e != s.p_err || o.e2 != s.p_e2) {
            FAIL("[cyc %llu] %s R-OUT-2 violated: was v=1 a=%08x rd=%08x e=%d e2=%d, now v=%d a=%08x rd=%08x e=%d e2=%d",
                 (unsigned long long)cyc, s.name, s.p_addr, s.p_rdata, s.p_err, s.p_e2, o.v, o.a, o.rd, o.e, o.e2);
            s.errors++;
          }
        }
        // golden stream
        if (o.v && s.exp_valid && !s.err_seen) {
          uint32_t pc = s.exp_pc, lo = mem_half(pc), hi = mem_half(pc + 2);
          bool comp = (lo & 3) != 3;
          if (o.a != pc) { FAIL("[cyc %llu] %s addr_o=%08x expected %08x", (unsigned long long)cyc, s.name, o.a, pc); s.errors++; }
          else if (!o.e) {
            bool ok = comp ? ((o.rd & 0xffff) == lo) : (o.rd == ((hi << 16) | lo));
            // Known main bug (adbe54d): a 32-bit instruction at line offset 2
            // whose beat 1 is not yet live goes through the skid, and the skid
            // bridge then takes the low half of beat 0 again instead of beat 1
            // (source_beat1 forced to 0 for an intra-line crossing).
            bool known = !ok && !comp && (pc & 7) == 2 && o.rd == ((mem_half(pc - 2) << 16) | lo);
            if (known) { s.known_skid++; ok = true; if (s.known_skid <= 2) std::printf("[cyc %llu] %s known intra-line skid bug at %08x\n", (unsigned long long)cyc, s.name, pc); }
            if (!ok) { FAIL("[cyc %llu] %s rdata=%08x at %08x expected %s%04x", (unsigned long long)cyc, s.name, o.rd, pc, comp ? "....": "", comp ? lo : ((hi << 16) | lo)); s.errors++; }
          }
        }
        bool accept = o.v && ready && !branch;
        if (accept) { s.accepts++; s.no_progress = 0; }
        else if (req && ready && !branch && s.exp_valid && !s.err_seen) {
          s.no_progress++; s.stall_cycles++;
          if (s.no_progress > s.max_no_progress) s.max_no_progress = s.no_progress;
          if (s.no_progress == STALL_MAX) { FAIL("[cyc %llu] %s no progress for %llu cycles at pc %08x", (unsigned long long)cyc, s.name, (unsigned long long)STALL_MAX, s.exp_pc); s.errors++; }
        }
        if (branch) { s.exp_valid = true; s.exp_pc = addr; s.err_seen = false; s.no_progress = 0; }
        else if (accept) {
          if (o.e) s.err_seen = true;   // R-OUT-3: outputs may change until the next branch
          s.exp_pc += ((mem_half(s.exp_pc) & 3) != 3 || o.e) ? 2 : 4;
        }
        s.p_hold = o.v && !ready && !branch && !o.e && !s.err_seen;
        s.p_rdata = o.rd; s.p_addr = o.a; s.p_err = o.e; s.p_e2 = o.e2;
      }
    }
    // ---- rising edge ----
    bool rqR = t->instr_req_o_R, rqD = t->instr_req_o_D; uint32_t raR = t->instr_addr_o_R, raD = t->instr_addr_o_D;
    t->clk = 1; t->eval();
    bR.post(cyc, rqR, raR); bD.post(cyc, rqD, raD);
  }
  std::printf("seed=%u profile=%d cycles=%llu equiv=%d err=%d | REF skidbug=%llu accepts=%llu stall=%llu maxgap=%llu rout2=%llu | DUT skidbug=%llu accepts=%llu stall=%llu maxgap=%llu rout2=%llu | equiv_checks=%llu errors=%ld\n",
              seed, profile, (unsigned long long)cycles, equiv, errmode,
              (unsigned long long)sR.known_skid, (unsigned long long)sR.accepts, (unsigned long long)sR.stall_cycles, (unsigned long long)sR.max_no_progress, (unsigned long long)sR.rout2_checks,
              (unsigned long long)sD.known_skid, (unsigned long long)sD.accepts, (unsigned long long)sD.stall_cycles, (unsigned long long)sD.max_no_progress, (unsigned long long)sD.rout2_checks,
              (unsigned long long)equiv_checks, total_errors);
  delete t;
  return total_errors ? 1 : 0;
}
