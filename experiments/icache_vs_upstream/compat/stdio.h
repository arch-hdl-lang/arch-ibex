/* Freestanding stubs for the riscv-tests benchmarks (the Homebrew
 * riscv64-elf toolchain ships no libc headers). Definitions come from the
 * benchmarks' own common/syscalls.c. */
#pragma once
int printf(const char *fmt, ...);
int sprintf(char *str, const char *fmt, ...);
int putchar(int ch);
