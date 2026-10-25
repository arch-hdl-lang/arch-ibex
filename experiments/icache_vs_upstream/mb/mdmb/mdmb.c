// Multiply/divide latency probe (core-side, not icache): for each RV32M op
// and operand pattern, time 32 back-to-back independent copies in a warm
// loop. Output: "mb <op>_<pattern> cycles=<N> instrs=<N>".
#include <stdint.h>
#include "util.h"

int printf(const char *fmt, ...);

#define R8(x) x x x x x x x x
#define R32(x) R8(x) R8(x) R8(x) R8(x)

static uint32_t rd_cycle(void) { uint32_t v; asm volatile("csrr %0, mcycle" : "=r"(v)); return v; }
static uint32_t rd_inst(void) { uint32_t v; asm volatile("csrr %0, minstret" : "=r"(v)); return v; }

#define OPK(op)                                                                 \
  static void __attribute__((noinline)) k_##op(uint32_t a, uint32_t b, int n) { \
    uint32_t t;                                                                 \
    do {                                                                        \
      asm volatile(R32(#op " %0, %1, %2\n") : "=&r"(t) : "r"(a), "r"(b));       \
    } while (--n);                                                              \
  }
// Same op followed by one independent ALU instruction (not back-to-back).
#define OPKG(op)                                                                \
  static void __attribute__((noinline)) k_##op##_gap(uint32_t a, uint32_t b, int n) { \
    uint32_t t, u;                                                              \
    do {                                                                        \
      asm volatile(R32(#op " %0, %2, %3\n addi %1, %2, 1\n") : "=&r"(t), "=&r"(u) : "r"(a), "r"(b)); \
    } while (--n);                                                              \
  }
OPKG(mul) OPKG(mulhu) OPKG(divu)
OPK(mul) OPK(mulh) OPK(mulhsu) OPK(mulhu) OPK(div) OPK(divu) OPK(rem) OPK(remu)

#define RUN(op, pat, a, b) do {                                               \
    k_##op(a, b, 2);                                                          \
    uint32_t c0 = rd_cycle(), i0 = rd_inst();                                 \
    k_##op(a, b, 10);                                                         \
    uint32_t c1 = rd_cycle(), i1 = rd_inst();                                 \
    printf("mb %s_%s cycles=%d instrs=%d\n", #op, pat, (int)(c1 - c0), (int)(i1 - i0)); \
  } while (0)

#define ALL(op)                                     \
  RUN(op, "small", 7u, 3u);                         \
  RUN(op, "big", 0x9abcdef1u, 0x12345u);            \
  RUN(op, "neg", 0xfffffff9u, 3u);                  \
  RUN(op, "negneg", 0x80000001u, 0xfffffffdu);      \
  RUN(op, "zero", 0x12345678u, 0u);                 \
  RUN(op, "minus1", 0x80000000u, 0xffffffffu);

int main(int argc, char **argv) {
  RUN(mul_gap, "small", 7u, 3u);
  RUN(mulhu_gap, "small", 7u, 3u);
  RUN(divu_gap, "small", 7u, 3u);
  ALL(mul) ALL(mulh) ALL(mulhsu) ALL(mulhu) ALL(div) ALL(divu) ALL(rem) ALL(remu)
  return 0;
}
