#pragma once
#include <stddef.h>
void exit(int code) __attribute__((noreturn));
void abort(void) __attribute__((noreturn));
long atol(const char *str);
