// Fetch-path microbenchmarks for the icache comparison. Each kernel is a
// counted loop whose body is 64 copies of one instruction shape; it runs
// once to warm the cache, then REPS times under mcycle. Everything is
// explicit assembly (.option rvc / norvc), so the layout is identical on
// both ISAs builds. Output: "mb <name> cycles=<N> instrs=<N>".
#include <stdint.h>
#include "util.h"

int printf(const char *fmt, ...);

#define REPS 20
#define BODY64(x) x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x \
                  x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x

// \1: alignment prologue, \2: body instruction(s)
#define KERNEL(name, pre, body)                                               \
  static void __attribute__((noinline, aligned(64))) name(int n) {            \
    asm volatile(                                                             \
        ".option push\n"                                                      \
        ".option norvc\n"                                                     \
        "  j 2f\n"                                                            \
        ".balign 64\n"                                                        \
        "2:\n"                                                                \
        pre                                                                   \
        "1:\n"                                                                \
        BODY64(body)                                                          \
        ".option norvc\n"                                                     \
        "  addi %0, %0, -1\n"                                                 \
        "  bnez %0, 1b\n"                                                     \
        ".option pop\n"                                                       \
        : "+r"(n) : : "t0", "t1", "memory");                                  \
  }

// 32-bit instructions, 4-byte aligned
KERNEL(k_al32, "", ".option norvc\n addi t0, t0, 1\n")
// 16-bit instructions only
KERNEL(k_c16, "", ".option rvc\n c.addi t0, 1\n")
// 32-bit instructions, all at 2 mod 4 (one c.nop shifts the loop head)
KERNEL(k_mis32, ".option rvc\n c.nop\n", ".option norvc\n addi t0, t0, 1\n")
// alternating 16-bit / 32-bit (every other 32-bit instruction misaligned)
KERNEL(k_mix, "", ".option rvc\n c.addi t0, 1\n.option norvc\n addi t1, t1, 1\n")
// 16+32+16 pattern: 32-bit instructions always misaligned, body of 8 bytes
KERNEL(k_c32c, "", ".option rvc\n c.addi t0, 1\n.option norvc\n addi t1, t1, 1\n.option rvc\n c.addi t0, 1\n")

#define BODY32(x) x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x
// Taken jumps (each to the next instruction / to a fresh 16-byte block).
KERNEL(k_jnext, "", ".option norvc\n j 3f\n3:\n")
KERNEL(k_jblk, "", ".option norvc\n j 3f\n.balign 16\n3:\n")
// Jump to a 32-bit target at offset 2 of an 8-byte line (no straddle) and at
// offset 6 (straddles into the next line). The skipped c.nops pad.
KERNEL(k_jmis2, "", ".option norvc\n j 3f\n.balign 16\n.option rvc\n c.nop\n3:\n.option norvc\n addi t0, t0, 1\n")
KERNEL(k_jmis6, "", ".option norvc\n j 3f\n.balign 16\n.option rvc\n c.nop\n c.nop\n c.nop\n3:\n.option norvc\n addi t0, t0, 1\n")
// Jump to word 0 / word 1 of a 64-bit line, then run sequentially into the
// next line (target, target+4, target+8).
KERNEL(k_jt0, "", ".option norvc\n j 3f\n.balign 16\n3:\n addi t0, t0, 1\n addi t1, t1, 1\n addi t0, t0, 1\n")
KERNEL(k_jt4, "", ".option norvc\n j 3f\n.balign 16\n nop\n3:\n addi t0, t0, 1\n addi t1, t1, 1\n addi t0, t0, 1\n")
// 8 KB of straight-line code (twice the 4 KB cache): capacity misses.
#define KERNEL_BIG(name, body) KERNEL(name, "", BODY32(body))
KERNEL_BIG(k_big32, ".option norvc\n addi t0, t0, 1\n")
KERNEL_BIG(k_big16, ".option rvc\n c.addi t0, 1\n c.addi t0, 1\n")

static uint32_t rd_cycle(void) { uint32_t v; asm volatile("csrr %0, mcycle" : "=r"(v)); return v; }
static uint32_t rd_inst(void) { uint32_t v; asm volatile("csrr %0, minstret" : "=r"(v)); return v; }

#define RUN(k, iters) do {                                       \
    k(iters);                                                    \
    uint32_t c0 = rd_cycle(), i0 = rd_inst();                    \
    for (int r = 0; r < REPS; r++) k(iters);                     \
    uint32_t c1 = rd_cycle(), i1 = rd_inst();                    \
    printf("mb %s cycles=%d instrs=%d\n", #k, (int)(c1 - c0), (int)(i1 - i0)); \
  } while (0)

int main(int argc, char **argv) {
  RUN(k_al32, 10);
  RUN(k_c16, 10);
  RUN(k_mis32, 10);
  RUN(k_mix, 10);
  RUN(k_c32c, 10);
  RUN(k_jnext, 10);
  RUN(k_jblk, 10);
  RUN(k_jmis2, 10);
  RUN(k_jmis6, 10);
  RUN(k_jt0, 10);
  RUN(k_jt4, 10);
  RUN(k_big32, 2);
  RUN(k_big16, 2);
  return 0;
}
