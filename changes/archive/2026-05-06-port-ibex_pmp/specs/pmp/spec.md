# Specification: ibex_pmp

`ibex_pmp` is a pure combinational permission checker. For each access
channel `c`, it consumes a 34-bit physical address, an access type
(EXEC/WRITE/READ), and the requesting privilege mode, and against a
CSR-supplied region table (`csr_pmp_cfg_i`, `csr_pmp_addr_i`) and ePMP
control (`csr_pmp_mseccfg_i`), it emits `pmp_req_err_o[c]` (`1` = deny).
The module has no clock and no state. Behavior is RISC-V Privileged Spec
PMP + Smepmp (ePMP) compliant. Debug-mode accesses to the Debug Module
address window bypass PMP entirely, per the RISC-V Debug Specification.

*Source: `ibex_pmp.sv:7-31`, `pmp.rst:6`.*

## Module interface

### Parameters

| Parameter        | Type           | Default        | Role                                                           |
|------------------|----------------|----------------|----------------------------------------------------------------|
| `DmBaseAddr`     | int unsigned   | `32'h1A11_0000`| Base address of the Debug Module bypass window (`ibex_pmp.sv:8`).|
| `DmAddrMask`     | int unsigned   | `32'h0000_0FFF`| Mask defining the Debug Module bypass window size (`ibex_pmp.sv:9`).|
| `PMPGranularity` | int unsigned   | `0`            | Granularity G; minimum NAPOT region is `2^(G+2)` bytes (`ibex_pmp.sv:12`).|
| `PMPNumChan`     | int unsigned   | `3`            | Number of independent access-checking channels. Module default is `2` (`ibex_pmp.sv:14`); the SoC overrides via `localparam` in `ibex_core.sv:177`. |
| `PMPNumRegions`  | int unsigned   | `4`            | Number of implemented PMP regions (`ibex_pmp.sv:16`).          |

### Inputs from CSRs

| Port                | Direction | Width / Shape                            | Role                                                                 |
|---------------------|-----------|------------------------------------------|----------------------------------------------------------------------|
| `csr_pmp_cfg_i`     | in        | unpacked `Vec<pmp_cfg_t, PMPNumRegions>` | Per-region cfg (lock/mode/X/W/R) (`ibex_pmp.sv:19`).                 |
| `csr_pmp_addr_i`    | in        | unpacked `Vec<UInt<34>, PMPNumRegions>`  | Per-region NAPOT/NA4/TOR address. Bits `[33:2]` only — bit indices 33..2 of the physical address (`ibex_pmp.sv:20`, `ibex_pkg.sv:408-411`). |
| `csr_pmp_mseccfg_i` | in        | packed `pmp_mseccfg_t` (3 bits)          | ePMP control: `{rlb, mmwp, mml}` (`ibex_pmp.sv:21`).                 |

### Inputs from core

| Port              | Direction | Width / Shape                          | Role                                                       |
|-------------------|-----------|----------------------------------------|------------------------------------------------------------|
| `debug_mode_i`    | in        | 1 bit                                  | Hart is in Debug Mode (`ibex_pmp.sv:23`).                  |
| `priv_mode_i`     | in        | unpacked `Vec<priv_lvl_e, PMPNumChan>` | Privilege level driving each channel (`ibex_pmp.sv:25`).   |
| `pmp_req_addr_i`  | in        | unpacked `Vec<UInt<34>, PMPNumChan>`   | Per-channel request physical address, bits `[33:0]` (`ibex_pmp.sv:27`). |
| `pmp_req_type_i`  | in        | unpacked `Vec<pmp_req_e, PMPNumChan>`  | Per-channel access type (EXEC/WRITE/READ) (`ibex_pmp.sv:28`). |

### Outputs

| Port            | Direction | Width / Shape                  | Role                                                                |
|-----------------|-----------|--------------------------------|---------------------------------------------------------------------|
| `pmp_req_err_o` | out       | unpacked `Vec<bool, PMPNumChan>` | Per-channel access-denied flag (`1` = deny) (`ibex_pmp.sv:29, 251`). |

`[PMP_ADDR_MSB:0]` = 34 bits (`PMP_ADDR_MSB=33`, `PMP_ADDR_LSB=2`); the
bottom 2 bits are present but unused (`ibex_pmp.sv:229-232`). Effective
comparison is on bits `[33:G+2]`.

## Pinned parameters

The proposal pins:
`DmBaseAddr=0`, `DmAddrMask=3`, `PMPGranularity=0`, `PMPNumChan=3`,
`PMPNumRegions=4`.

Effects on the spec body:

- `G=0`: only the `g_region_addr_mask_zero_granularity` branch
  (`ibex_pmp.sv:177-179`) is live; the `>0` branch
  (`ibex_pmp.sv:180-183`) is dead. NA4 is fully usable
  (`pmp.rst:38` — NA4 is disabled only when `G>0`).
- `PMPNumChan=3`: three independent channels indexed `[0..2]` per the
  upstream `localparam` override at `ibex_core.sv:177`. Channel
  semantics (used by the consumer at `ibex_core.sv:1183-1190`):
  `PMP_I=0` (instruction-fetch addr), `PMP_I2=1` (fetch addr + 2,
  used to validate the upper halfword of an unaligned 32-bit
  instruction crossing a region boundary), `PMP_D=2` (data
  load/store addr). The PMP module itself does NOT distinguish
  between channels — each is checked identically against the same
  region table. Spec scenarios use channel `0` (i-side) by default;
  channel-independence is verified by R-CHAN.
- `PMPNumRegions=4`: regions indexed `0..3`.
- `DmBaseAddr=0, DmAddrMask=3`: bypass window is byte range `[0x0..0x3]`.

## Type definitions

All structs/enums are taken from `ibex_pkg.sv`. Per SV `struct packed`
semantics, the first-declared field occupies the MSBs.

### `priv_lvl_e` — 2 bits (`ibex_pkg.sv:216-221`)

`PRIV_LVL_M=2'b11`, `PRIV_LVL_H=2'b10` (unused), `PRIV_LVL_S=2'b01`
(unused), `PRIV_LVL_U=2'b00`. The PMP module only distinguishes M-mode
vs not-M-mode.

### `pmp_req_e` — 2 bits (`ibex_pkg.sv:418-422`)

`PMP_ACC_EXEC=2'b00`, `PMP_ACC_WRITE=2'b01`, `PMP_ACC_READ=2'b10`,
`2'b11` reserved/unused.

### `pmp_cfg_mode_e` — 2 bits (`ibex_pkg.sv:425-430`)

`PMP_MODE_OFF=2'b00`, `PMP_MODE_TOR=2'b01`, `PMP_MODE_NA4=2'b10`,
`PMP_MODE_NAPOT=2'b11`.

### `pmp_cfg_t` — 6 bits packed (`ibex_pkg.sv:432-438`)

SV declaration order `{lock; mode; exec; write; read}`, MSB first:
`[5]=lock`, `[4:3]=mode (pmp_cfg_mode_e)`, `[2]=exec`, `[1]=write`,
`[0]=read`. The ARCH implementer SHOULD model this as a 5-field
record; the bit layout is given only for SV interop.

### `pmp_mseccfg_t` — 3 bits packed (`ibex_pkg.sv:441-445`)

MSB first: `[2]=rlb`, `[1]=mmwp`, `[0]=mml`. `rlb` is consumed only by
`ibex_cs_registers` (CSR-write side); inside `ibex_pmp` it is `unused`
(`ibex_pmp.sv:259-262`). The module reads only `mml` and `mmwp`.

## Requirements

### R-MODE: region match modes

#### REQ-MODE-1: OFF mode never matches

**Given** region `r` with `mode == PMP_MODE_OFF`,
**when** computing `region_match_all[c][r]`,
**then** it SHALL be `0` regardless of the request address.

*Source: `ibex_pmp.sv:204`.*

#### REQ-MODE-2: NA4 match

**Given** region `r` with `mode == PMP_MODE_NA4`,
**when** comparing addresses,
**then** `region_match_all[c][r]` SHALL be `1` iff
`pmp_req_addr_i[c][33:2] == csr_pmp_addr_i[r][33:2]` (the address-mask
is all-ones for non-NAPOT modes, so `region_match_eq` is an exact compare).

*Source: `ibex_pmp.sv:170, 178-179, 191-193, 205`.*

#### REQ-MODE-3: NAPOT match

**Given** region `r` with `mode == PMP_MODE_NAPOT`,
**when** comparing addresses,
**then** `region_match_all[c][r]` SHALL be `1` iff
`(pmp_req_addr_i[c][33:2] & mask) == (csr_pmp_addr_i[r][33:2] & mask)`,
where `mask` has bit 2 cleared and bit `b` (for `b > 2`) cleared iff
every `csr_pmp_addr_i[r][b-1:2]` bit is `1` (NAPOT size-encoding rule).

*Source: `ibex_pmp.sv:170, 178-179, 191-193, 206`.*

#### REQ-MODE-4: TOR match (region > 0)

**Given** region `r > 0` with `mode == PMP_MODE_TOR`,
**when** comparing addresses,
**then** `region_match_all[c][r]` SHALL be `1` iff
`csr_pmp_addr_i[r-1][33:2] <= pmp_req_addr_i[c][33:2] < csr_pmp_addr_i[r][33:2]`.

*Source: `ibex_pmp.sv:163-164, 194-199, 207-210`.*

#### REQ-MODE-5: TOR match for region 0

**Given** region `0` with `mode == PMP_MODE_TOR`,
**when** computing the range,
**then** the lower bound SHALL be `0`, so the region matches iff
`0 <= pmp_req_addr_i[c][33:2] < csr_pmp_addr_i[0][33:2]`.

*Source: `ibex_pmp.sv:159-161` (the `g_entry0` branch substitutes
`34'h0` for the previous-region address).*

### R-PERM: basic permission rules

#### REQ-PERM-1: Basic permission check encoding

**Given** any region `r` and channel `c`,
**when** computing `region_basic_perm_check[c][r]`,
**then** it SHALL be `cfg.exec` if type==EXEC, `cfg.write` if type==WRITE,
`cfg.read` if type==READ, else `0` (reserved encoding).

*Source: `ibex_pmp.sv:216-219`.*

#### REQ-PERM-2: MML=0, M-mode — lock gates basic check

**Given** `mml == 0`, `priv_mode_i[c] == PRIV_LVL_M`,
**when** computing `region_perm_check[c][r]`,
**then** it SHALL equal `(~cfg.lock) | basic_perm_check[c][r]` — unlocked
regions always grant M-mode access; locked regions require the basic R/W/X
bit.

*Source: `ibex_pmp.sv:101-110, 113-125`.*

#### REQ-PERM-3: MML=0, non-M-mode — basic check only

**Given** `mml == 0`, `priv_mode_i[c] != PRIV_LVL_M`,
**when** computing `region_perm_check[c][r]`,
**then** it SHALL equal `basic_perm_check[c][r]` (lock irrelevant).

*Source: `ibex_pmp.sv:104-109`.*

### R-MML: Machine Mode Lockdown

#### REQ-MML-1: MML {R=0, W=1} shared-region table

**Given** `mml == 1`, region with `{read, write} == {0, 1}`,
**when** computing `region_perm_check`, the result SHALL match the
four-row table indexed by `{lock, exec}`:

- `{L=0, X=0}`: READ any mode; WRITE only M-mode.
- `{L=0, X=1}`: READ or WRITE from any mode.
- `{L=1, X=0}`: EXEC only, any mode.
- `{L=1, X=1}`: EXEC any mode; READ only M-mode.

*Source: `ibex_pmp.sv:66-83`.*

#### REQ-MML-2: MML shared-read-only (L=W=R=X=1)

**Given** `mml == 1`, region with `lock & read & write & exec` all set,
**when** computing `region_perm_check`,
**then** it SHALL grant only `PMP_ACC_READ` (any privilege).

*Source: `ibex_pmp.sv:85-88`.*

#### REQ-MML-3: MML otherwise — lock-bit polarity flips

**Given** `mml == 1`, region not in REQ-MML-1 or REQ-MML-2,
**when** computing `region_perm_check[c][r]`,
**then** it SHALL equal
`basic_perm_check[c][r] & (priv_mode_i[c]==PRIV_LVL_M ? lock : ~lock)`.
M-mode requires `lock=1`; non-M-mode requires `lock=0`. (Inverse of
REQ-PERM-2.)

*Source: `ibex_pmp.sv:90-94`; see `pmp.rst:42-52` for ePMP intent.*

### R-MMWP: Machine Mode Whitelist Policy

#### REQ-MMWP-1: MMWP=1 → unmatched is always denied

**Given** `mmwp == 1`,
**when** no region matches (`|match_all == 0`) for channel `c`,
**then** `pmp_req_err_o[c]` SHALL be `1` regardless of privilege.

*Source: `ibex_pmp.sv:138`.*

#### REQ-MMWP-2: MMWP=0 — M-mode default-allow

**Given** `mmwp == 0`, no matching region, `priv_mode_i[c] == PRIV_LVL_M`,
**and** not (`mml == 1` and `pmp_req_type_i[c] == PMP_ACC_EXEC`) (see
REQ-MMWP-3),
**when** evaluating the access,
**then** it SHALL be allowed (ignoring debug bypass).

*Source: `ibex_pmp.sv:138`.*

#### REQ-MMWP-3: MML M-mode EXEC requires a matching region

**Given** `mml == 1`, `priv_mode_i[c] == PRIV_LVL_M`,
`pmp_req_type_i[c] == PMP_ACC_EXEC`,
**when** no region matches,
**then** the access SHALL be denied even if `mmwp == 0`.

*Source: `ibex_pmp.sv:138-139`.*

#### REQ-MMWP-4: Non-M-mode default is deny

**Given** `priv_mode_i[c] != PRIV_LVL_M`,
**when** no region matches for channel `c`,
**then** the access SHALL be denied regardless of `mseccfg`.

*Source: `ibex_pmp.sv:138`.*

### R-DBG: Debug-mode bypass

#### REQ-DBG-1: Debug-Module address bypass

**Given** `debug_mode_i == 1`,
`(pmp_req_addr_i[c][31:0] & ~DmAddrMask) == DmBaseAddr`,
**when** evaluating the access,
**then** `pmp_req_err_o[c]` SHALL be `0`, overriding any region/MML/MMWP
verdict.

*Source: `ibex_pmp.sv:239-240, 251`. Mandated by RISC-V Debug Spec v1.0.0
§A.2 (`pmp.rst:62-66`).*

#### REQ-DBG-2: Bypass scope

**Given** `debug_mode_i == 1` but the address is outside the Debug-Module
window,
**when** evaluating the access,
**then** the normal PMP check applies; debug mode does NOT blanket-bypass.

*Source: `ibex_pmp.sv:239, 251`.*

#### REQ-DBG-3: Bypass uses bits [31:0] only

**Given** `debug_mode_i == 1`,
**when** evaluating the bypass test,
**then** only `pmp_req_addr_i[c][31:0]` SHALL participate; bits `[33:32]`
SHALL be ignored.

*Source: `ibex_pmp.sv:240`.*

### R-PRIO: Region priority

#### REQ-PRIO-1: Lowest-index match wins

**Given** multiple matching regions `r0 < r1 < ... < rk`,
**when** computing `access_fault_check_res[c]`,
**then** the verdict SHALL come from `region_perm_check[c][r0]` only;
higher-indexed matches are ignored.

*Source: `ibex_pmp.sv:142-149` (the `if (!matched && match_all[r])` gate).*

### R-CHAN: Per-channel independence

#### REQ-CHAN-1: Channels are independent

**Given** distinct channels `c0`, `c1`,
**when** computing `pmp_req_err_o[c0]` and `pmp_req_err_o[c1]`,
**then** each output SHALL depend only on its own channel's inputs plus
the shared CSR/debug inputs; no cross-channel coupling.

*Source: `ibex_pmp.sv:188-257`.*

#### REQ-CHAN-2: Channels share the region table

The CSR ports (`csr_pmp_cfg_i`, `csr_pmp_addr_i`, `csr_pmp_mseccfg_i`) are
not channel-indexed; all channels see the same region table.

*Source: `ibex_pmp.sv:19-21`.*

#### REQ-CHAN-3: Output formula

**Given** any channel `c`,
**then** `pmp_req_err_o[c] == ~debug_mode_allowed_access[c] &
access_fault_check_res[c]`.

*Source: `ibex_pmp.sv:251`.*

## Scenarios

### S1: OFF region never matches

**Given** region 0 with `mode == PMP_MODE_OFF` and any request,
**when** computing `region_match_all[c][0]`,
**then** `region_match_all[c][0] == 0`. With all other regions also OFF
and `priv_mode_i[c] == PRIV_LVL_U`, `pmp_req_err_o[c] == 1` per
REQ-MMWP-4.

*Source: `ibex_pmp.sv:204`.*

### S2: TOR region inclusive lower / exclusive upper

**Given** region 1 with `mode == PMP_MODE_TOR`,
`csr_pmp_addr_i[0] = 0x100`, `csr_pmp_addr_i[1] = 0x200`,
**when** `pmp_req_addr_i[c][33:2] == 0x100`, `region_match_all[c][1] == 1`
(inclusive lower); when it equals `0x200`, `region_match_all[c][1] == 0`
(exclusive upper).

*Source: `ibex_pmp.sv:194-199, 207-210` (`<=` lower, strict `<` upper).*

### S3: NAPOT at granularity 0

**Given** `PMPGranularity == 0`, region 0 with `mode == PMP_MODE_NAPOT`,
`csr_pmp_addr_i[0] = 34'h...0000_001F` (low 5 bits all-ones encodes a
16-byte NAPOT region at byte base `0x10`),
**when** the address mask is computed (bit 2 always masked; higher bits
masked while `csr_pmp_addr[r][b-1:2]` is all-ones),
**then** `region_match_all[c][0] == 1` iff
`pmp_req_addr_i[c][33:2] ∈ {0x4..0x7}` (byte addrs `0x10..0x1F`).

*Source: `ibex_pmp.sv:170, 178-179, 191-193, 206`.*

### S4: Locked region + M-mode + read (MML=0)

**Given** `mml == 0`, region 0 with `{lock=1, mode=NAPOT, R=1, W=0, X=0}`
matching the request, `priv_mode_i[c] == PRIV_LVL_M`,
**when** `pmp_req_type_i[c] == PMP_ACC_READ`,
**then** `region_perm_check = (~L | basic) = (0 | 1) = 1` — allowed.
With `PMP_ACC_WRITE`, `basic = 0` and `region_perm_check = 0` — denied.

*Source: `ibex_pmp.sv:101-110`.*

### S5: Multiple matches — lowest index wins

**Given** regions 0 and 2 both match the request, region 0 has `R=1`
(allow), region 2 has `R=0` (deny),
**when** the request is `PMP_ACC_READ`,
**then** the access is allowed; region 0's verdict decides. Conversely,
if region 0 denies and region 2 allows, the access is denied.

*Source: `ibex_pmp.sv:142-149`.*

### S6: MML M-only execute encoding

**Given** `csr_pmp_mseccfg_i.mml == 1`,
**and** region 0 has `{lock=1, mode=NAPOT, exec=1, write=0, read=0}`
matching the request,
**when** `priv_mode_i[c] == PRIV_LVL_M, pmp_req_type_i[c] == PMP_ACC_EXEC`,
**then** by REQ-MML-3, `region_perm_check = exec & (M ? L : ~L) = 1 & 1 = 1`
— allowed (M-mode execute). The same region under U-mode gives
`1 & ~1 = 0` — denied. Cfg `{L=1, X=1, R=0, W=0}` under MML thus encodes
"M-only execute".

*Source: `ibex_pmp.sv:66-95`.*

### S7: MMWP=1, M-mode access without matching region

**Given** `mmwp == 1, mml == 0`, all regions OFF,
`priv_mode_i[c] == PRIV_LVL_M`,
**when** any access is requested,
**then** `pmp_req_err_o[c] == 1` (MMWP flips M-mode default to deny).

*Source: `ibex_pmp.sv:138`.*

### S8: Debug mode + Debug-Module address → bypass

**Given** `debug_mode_i == 1`, `DmBaseAddr = 32'h0`, `DmAddrMask = 32'h3`,
**and** `pmp_req_addr_i[c][31:0] == 32'h0000_0002`, MMWP=1 with no
matching region,
**when** the access is `PMP_ACC_EXEC`,
**then** `pmp_req_err_o[c] == 0` (bypass via `debug_mode_allowed_access`
overrides the would-be MMWP-deny).
**Conversely** with `pmp_req_addr_i[c][31:0] == 32'h0000_0004`,
`debug_mode_allowed_access[c] == 0` and MMWP-deny applies.

*Source: `ibex_pmp.sv:239-240, 251`.*

### S9: i-side execute vs d-side load/store independence

**Given** `PMPNumChan == 3` and a region table chosen so channel 0
(EXEC at `A_X`, U-mode) is permitted while channel 2 (WRITE at `A_W`,
M-mode) is denied (e.g. MML=1, MMWP=0),
**when** both checks resolve combinationally,
**then** `pmp_req_err_o[0] == 0` AND `pmp_req_err_o[2] == 1`
independently — neither channel's verdict can affect the other.

*Source: `ibex_pmp.sv:188-257`.*

### S10: All-zero CSR + non-M-mode → deny

**Given** all `csr_pmp_cfg_i = 0` (all OFF), `csr_pmp_addr_i = 0`,
`csr_pmp_mseccfg_i = 0`, `priv_mode_i[c] == PRIV_LVL_U`,
`debug_mode_i == 0`,
**when** any access is requested,
**then** `pmp_req_err_o[c] == 1` (no match + non-M-mode → deny per
REQ-MMWP-4). This matches the SoC reset state (`ibex_pkg.sv:686-727`).

*Source: `ibex_pmp.sv:138, 251`.*

## Spec ambiguities flagged

### A1: MML retroactive reinterpretation of locked regions

`mml_perm_check` (`ibex_pmp.sv:59-97`) is consulted unconditionally when
`mseccfg.mml == 1`; there is no "applies only to regions locked after MML
was set" gate. Once `mml=1`, the current `pmp_cfg_t` of every region is
reinterpreted under MML rules.

> Resolution: match upstream — MML reinterprets all regions immediately
> on the cycle it is set. CSR-level "RLB" and "sticky MML" protections
> are out of scope (handled by `ibex_cs_registers`). Do NOT add any
> "MML-set-time" latch in the PMP module.

### A2: Non-contiguous `DmAddrMask`

`debug_mode_allowed_access` uses literal masked-equality
(`ibex_pmp.sv:239-240`). The SV does not constrain `DmAddrMask` to be of
form `2^N - 1`; non-contiguous masks would yield a non-contiguous bypass
region.

> Resolution: under the SoC pinning `DmAddrMask = 0x3` (contiguous). The
> spec body assumes contiguity; non-contiguous masks are out of scope.
> The implementation MUST still use the literal masked-equality formula
> — do not add a contiguity assumption.

### A3: PMPGranularity=0 NAPOT degenerate case

At `G=0`, a NAPOT region with `csr_pmp_addr_i[r][33:2]` ending in no `1`
bits has its address-mask reduced to all-ones (same as NA4) — i.e. a
4-byte region. This is correct ePMP behavior.

> Resolution: implement the literal `~&csr_pmp_addr_i[r][b-1:2]` rule
> (`ibex_pmp.sv:178-179`); a NAPOT region with no size bits set is a
> 4-byte region by construction. No special case needed.

### A4: `csr_pmp_mseccfg_i.rlb` is unused

`ibex_pmp.sv:259-262` ties `rlb` to `unused_csr_pmp_mseccfg_rlb`. The bit
has no effect on `pmp_req_err_o`.

> Resolution: model `pmp_mseccfg_t` with all three fields for shape
> compatibility. Inside `IbexPmp.arch`, mark `rlb` as deliberately
> unused. Do NOT drop the field from the type.

### A5: `pmp_req_e == 2'b11` (reserved encoding)

Only `EXEC=00`, `WRITE=01`, `READ=10` are defined; `2'b11` is reserved.
Upstream's `region_basic_perm_check` (lines 216-219) returns `0` for
this encoding (no OR-arm fires) and the MML EXEC-deny clause is not
triggered.

> Resolution: behave as upstream — reserved encoding always yields
> denied (unless debug-mode bypass). Do not assert against it; the
> consumer never drives it (`ibex_core.sv:1184, 1187, 1190`).

## Out of scope

- `PMPGranularity > 0` (the `>0` mask branch `ibex_pmp.sv:180-183` and
  NA4-disabled-when-G>0 per `pmp.rst:38`).
- `PMPNumRegions != 4`; `PMPNumChan != 3` (covers the upstream
  channel set `{PMP_I, PMP_I2, PMP_D}` at `ibex_core.sv:1183-1190`).
- ePMP CSR-write-side semantics (`mseccfg.rlb`, sticky bits, RLB)
  — those live in `ibex_cs_registers`.
- Coverage macros (`DV_FCOV_SIGNAL`, `ibex_pmp.sv:255-256`).
- `PMPEnable=0` SoC tieoff (`ibex_core.sv:1211-1226`) — integration-level.
