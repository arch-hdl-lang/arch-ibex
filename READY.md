# READY — D2-flip: SoC PMPEnable=1

## Status: READY TO ARCHIVE

D2-flip wires the merged D2 IbexPmp into IbexCore and flips
the SoC pin from `PMPEnable=0` to `PMPEnable=1`. PMP is now active
end-to-end through the ARCH-emitted core. Default-zero `PmpCfgRst`
gives M-mode default-allow, so existing CPU programs see no
behavioural change until they write to PMP CSRs.

## What was done

1. **`src/IbexCore.arch`** — `param PMPEnable` flipped 0 → 1.
   Replaced the `pmp_req_err = 3'd0` tieoff with a real
   `inst pmp_i: ibex_pmp` block. Three channels driven per upstream
   `g_pmp` (`ibex_core.sv:1176-1196`):
   - `pmp_req_addr_in[0]  = {2'd0, pc_if}`     (PMP_I — fetch)
   - `pmp_req_addr_in[1]  = {2'd0, pc_if + 2}` (PMP_I2 — fetch+2 for unaligned-32 upper)
   - `pmp_req_addr_in[2]  = {2'd0, data_addr_o}` (PMP_D — load/store)
   - `pmp_req_type_in[2]  = data_we_o ? PMP_ACC_WRITE : PMP_ACC_READ`
   - `priv_mode` for I/I2 = `priv_mode_id`; for D = `priv_mode_lsu`
   - `cs_registers_i.PMPEnable` propagated from IbexCore's param
     (was hardcoded `1'd0`).
   - Build-helper wires (`pmp_req_addr_in`, `pmp_req_type_in`,
     `pmp_priv_mode_in`, `pmp_req_err_out`) used because arch-com
     doesn't accept `port[idx] <- expr` inside an inst block.

2. **`tests/test_ibex_{core,top}_unit{,_full}.py`** — added
   `PMP_SV = build/ibex_pmp.sv` to source bundles; flipped
   `parameters={"PMPEnable": ...}` from 0 to 1 to match the new
   IbexCore.arch hardcode.

3. **No changes to `IbexPmp.arch`** — the spec'd module is
   untouched. D2-flip is purely consumer-side wiring.

## Results

- **SoC lint** GREEN with `PMPEnable=1`.
- **CPU programs** 5/5 PASS — default `PmpCfgRst` keeps M-mode
  default-allow, so timer / sw / ext / multictx / wfi all run
  unchanged.
- **`tests/test_ibex_pmp_unit.py`** 22/22 PASS.
- **`tests/test_ibex_pmp_unit_full.py`** 28/28 PASS.
- **`tests/test_ibex_icache_unit.py`** 45/53 PASS (unchanged from
  D1).
- **`tests/test_ibex_core_unit.py`** 19/21 (req6 + req10 fail —
  **pre-existing D1 regressions, NOT caused by D2-flip**;
  confirmed by running before and after the flip).
- **`tests/test_ibex_top_unit.py`** 14/15 (1 pre-existing failure).
- All other unit suites unchanged-green.

## Why default-zero PmpCfgRst keeps existing programs working

With `PMPEnable=1`:
- The CSR file (`soc/ibex_cs_registers_hybrid.sv`, upstream-SV)
  now drives `csr_pmp_cfg_o`, `csr_pmp_addr_o`, `csr_pmp_mseccfg_o`
  from real PMP CSR values.
- Out of reset, `PmpCfgRst` is all-zeros (every region OFF, mml=0,
  mmwp=0). `PmpAddrRst` is all-zeros.
- Per spec REQ-MMWP-2 (mmwp=0, M-mode, no match → allow): every
  M-mode access is allowed.
- ISR programs run entirely in M-mode without writing PMP CSRs,
  so the verdict stream is identical to PMPEnable=0.

The PMP module is now load-bearing. Future CPU programs that
write PMP CSRs will see real protection-fault behaviour through
the existing exception path (`pmp_err_if_i`,
`pmp_err_if_plus2_i`, `data_pmp_err_i` muxes already in place).

## Files modified

- `src/IbexCore.arch` (PMPEnable flip + IbexPmp inst block)
- `tests/test_ibex_core_unit.py`
- `tests/test_ibex_core_unit_full.py`
- `tests/test_ibex_top_unit.py`
- `tests/test_ibex_top_unit_full.py`
- `soc/ibex_mini_soc.sv` — **not touched**: SoC currently doesn't
  pass an explicit `.PMPEnable(...)` override, and the IbexCore.arch
  hardcoded param now defaults to 1, so the SoC inherits PMPEnable=1
  through the param chain.

## Not done (stop before step 9)

Archive step intentionally NOT done — orchestrator serialises the
commit. No change folder needs archiving (D2-flip is small enough
to land directly).
