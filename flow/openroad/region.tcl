# Optional placement region (fence) for one group of instances, shared by
# lane.tcl (run.sh) and estimate.tcl (estimate.sh).
#
#   PLACE_REGION="<inst glob>@<x1>,<y1>,<x2>,<y2>"     (um, die coordinates)
#   e.g. PLACE_REGION="u_ibex_core.pmp_i/*@2380,1000,2640,1350"
#
# Unset or empty = no region (the plain flow). Instances are matched by their
# flattened OpenROAD name, so the module must survive synthesis as hierarchy
# (flow/sky130_synth.sh SYNTH_KEEP_HIER) -- a flattened netlist only has
# anonymous _NNN_ cells. This OpenROAD has no create_region / fence command;
# the region is built with the odb API, which both placers honour:
#   - global placement (gpl) places each region group with its own placer,
#     inside the region, and blocks the region's sites for every other cell
#     (gpl placerBase.cpp, replace.cpp getRegions()/getGroups());
#   - detailed placement (dpl) legalises group members inside the region
#     (dpl dbToOpendp.cpp setUpPlacementGroups).
# Cells inserted later (repair_design / repair_timing buffers) are not in
# the group; the legaliser keeps them out of the region.
proc apply_place_region {} {
  if { ![info exists ::env(PLACE_REGION)] || $::env(PLACE_REGION) == "" } {
    return
  }
  if { ![regexp {^(.+)@([0-9.]+),([0-9.]+),([0-9.]+),([0-9.]+)$} \
          $::env(PLACE_REGION) -> pat x1 y1 x2 y2] } {
    error "PLACE_REGION: expected <glob>@x1,y1,x2,y2 (um), got '$::env(PLACE_REGION)'"
  }
  set block [ord::get_db_block]
  set region [odb::dbRegion_create $block place_region]
  odb::dbBox_create $region [ord::microns_to_dbu $x1] [ord::microns_to_dbu $y1] \
    [ord::microns_to_dbu $x2] [ord::microns_to_dbu $y2]
  set group [odb::dbGroup_create $region place_group]
  set n 0
  set area 0.0
  foreach inst [$block getInsts] {
    if { [string match $pat [$inst getName]] } {
      $group addInst $inst
      incr n
      set m [$inst getMaster]
      set area [expr $area + [ord::dbu_to_microns [$m getWidth]] * [ord::dbu_to_microns [$m getHeight]]]
    }
  }
  set box_area [expr ($x2 - $x1) * ($y2 - $y1)]
  puts [format "PLACE_REGION %s: %d instances, %.0f um2 of cells in a %.0f um2 box (%.0f%%)" \
    $::env(PLACE_REGION) $n $area $box_area [expr 100.0 * $area / $box_area]]
  if { $n == 0 } { error "PLACE_REGION: no instance matches '$pat'" }
}
