#pragma once
#define fabs(x) __builtin_fabs(x)
/* mm/rb.h calls fma(); there is no libm here. Unfused multiply-add (the
 * benchmark's own check tolerates 1e-6 relative error). */
#define fma(a, b, c) ((a) * (b) + (c))
