import sys
M = 0xffffffff
def h(x):
    x &= M; x ^= x >> 16; x = (x * 0x7feb352d) & M; x ^= x >> 15; x = (x * 0x846ca68b) & M; x ^= x >> 16; return x
seed = int(sys.argv[1]); salt = h(seed * 7919)
def word(a):
    hh = h((a >> 2) ^ salt); w = hh
    w = (w & ~3 & M) | (3 if (hh >> 20) & 1 else ((hh >> 21) % 3))
    w = (w & ~0x30000 & M) | ((3 if (hh >> 23) & 1 else ((hh >> 24) % 3)) << 16)
    return w
for a in sys.argv[2:]:
    a = int(a, 16)
    for o in range(-8, 12, 4):
        print(hex(a + o), hex(word(a + o)))
