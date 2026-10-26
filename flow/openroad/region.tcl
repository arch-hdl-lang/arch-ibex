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
  # Snap the box to the row/site grid (the detailed placer's grid).
  set row [lindex [$block getRows] 0]
  set site [$row getSite]
  set sw [$site getWidth]
  set sh [$site getHeight]
  lassign [$row getOrigin] ox oy
  set bx1 [expr $ox + int(ceil(([ord::microns_to_dbu $x1] - $ox) / double($sw))) * $sw]
  set bx2 [expr $ox + int(floor(([ord::microns_to_dbu $x2] - $ox) / double($sw))) * $sw]
  set by1 [expr $oy + int(ceil(([ord::microns_to_dbu $y1] - $oy) / double($sh))) * $sh]
  set by2 [expr $oy + int(floor(([ord::microns_to_dbu $y2] - $oy) / double($sh))) * $sh]
  set region [odb::dbRegion_create $block place_region]
  odb::dbBox_create $region $bx1 $by1 $bx2 $by2
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
  set box_area [expr [ord::dbu_to_microns [expr $bx2 - $bx1]] * [ord::dbu_to_microns [expr $by2 - $by1]]]
  puts [format "PLACE_REGION %s: %d instances, %.0f um2 of cells in a %.0f um2 box (%.0f%%)" \
    $::env(PLACE_REGION) $n $area $box_area [expr 100.0 * $area / $box_area]]
  if { $n == 0 } { error "PLACE_REGION: no instance matches '$pat'" }
}

# PLACE_REGION_DPL=0: drop the region before detailed placement, so only
# global placement honours it (a soft constraint; the legaliser and the
# repair steps then move cells freely).
proc release_place_region {} {
  if { [info exists ::env(PLACE_REGION_DPL)] && $::env(PLACE_REGION_DPL) == 0 } {
    set block [ord::get_db_block]
    foreach g [$block getGroups] { odb::dbGroup_destroy $g }
    foreach r [$block getRegions] { odb::dbRegion_destroy $r }
    puts "PLACE_REGION released before detailed placement"
  }
}
