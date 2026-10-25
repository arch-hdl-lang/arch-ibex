/* Entry shim that runs a riscv-tests benchmark on the arch-ibex mini SoC.
 *
 * simple_system's crt0.S (assembled with -Dmain=rt_entry) clears .bss and
 * calls rt_entry, which enables the counters and the icache (cpuctrlsts bit 0,
 * as CoreMark's Ibex port does in portable_init) and then enters the
 * benchmark's own _init (riscv-tests common/syscalls.c, patched by
 * build_workloads.py): main(), print "mcycle = N" / "minstret = N" for the
 * setStats(1)..setStats(0) region, and exit(code). The patched exit prints
 * "rt_exit_code=<code>" and halts through simulator_ctrl. */
#include <stdint.h>

void _init(int cid, int nc);
int printf(const char *fmt, ...);

#define SIM_CTRL_CTRL 0x20008

void rt_entry(void) {
  asm volatile("csrw 0x320, zero");   /* mcountinhibit = 0 */
  asm volatile("csrs 0x7c0, 1");      /* cpuctrlsts.icache_enable = 1 */
  _init(0, 1);
}

static void rt_trap(const char *what) {
  uint32_t mcause, mepc, mtval;
  asm volatile("csrr %0, mcause" : "=r"(mcause));
  asm volatile("csrr %0, mepc" : "=r"(mepc));
  asm volatile("csrr %0, mtval" : "=r"(mtval));
  printf("rt_trap=%s mcause=0x%x mepc=0x%x mtval=0x%x\n", what, mcause, mepc, mtval);
  *(volatile uint32_t *)SIM_CTRL_CTRL = 1;
  while (1) {
  }
}

void simple_exc_handler(void) { rt_trap("exception"); }
void simple_timer_handler(void) { rt_trap("timer"); }

/* mm's barrier() uses __sync_fetch_and_add; without the A extension GCC
 * emits a libcall. One hart, so a plain read-modify-write is exact. */
unsigned int __sync_fetch_and_add_4(volatile void *p, unsigned int v) {
  volatile unsigned int *q = (volatile unsigned int *)p;
  unsigned int old = *q;
  *q = old + v;
  return old;
}
