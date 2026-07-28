# Floor plan <-> rig view calibration

Homography between `rig/office_floor_plan_v2.png` (top-down plan,
rendered from `rig/office_floor_plan_v2.svg`) and `rig/rig_view.png`
(SENTINEL RIG photo), for mapping floor-plane points between the two.

## Files

- `homography.py` -- point correspondences + normalized-DLT solver (numpy
  only, no OpenCV). Run it to regenerate the matrices below.
- `H_plan_to_photo.npy` / `H_photo_to_plan.npy` -- the fitted 3x3 homography
  and its inverse.
- `calibration_reference.png` -- side-by-side plan + photo with the 5
  calibration points marked, for re-anchoring after the rig moves.
- `degeneracy_check.png` -- diagnostic image, see "History" below.

## Correspondences used (v6, current -- 4 points, elevated plane only)

| # | Landmark | Floor plan (px) | Photo (px) | Approx. height |
|---|---|---|---|---|
| 1 | Couch near-end armrest, front-top corner | (1411, 1256) | (292, 285) | ~2-2.2ft |
| 2 | Couch far-end armrest, front-top corner | (1411, 1885) | (80, 310) | ~2-2.2ft |
| 3 | File cabinet top surface | (587, 1880) | (595, 308) | ~2.3-2.5ft |
| 4 | Craig chair, seat height | (402, 1413) | (540, 355) | ~1.5-1.8ft |

**This homography is only valid for points roughly 1.5-2.5ft above the
floor** (chair-seat to armrest/cabinet-top height). It deliberately
excludes: floor-level points (stairwell, rug, guard rail -- see v3-v5
history below) and the old monitor-top point (~4ft, too high). Floor-
level objects mapped through this H will carry substantially higher
position error -- confirmed below, not just theoretical.

A 5th same-band point (coffee table surface, ~1.3-1.5ft) was tried as a
consistency check and dropped: it pushed the RMS residual from 0px
(4-point exact fit) to ~32px, with `couch_far_end_armrest` alone jumping
to 56px error. Even a modest spread within "elevated" (1.3ft vs
2.0-2.5ft) is enough to measurably strain the single-plane assumption --
this homography is tightest for points near 1.5-2.5ft specifically, not
"elevated" in general.

### Out-of-sample check: floor-level degradation, confirmed

Projecting floor-level plan landmarks (not used in the fit) through this
elevated-plane H:

| Landmark | Plan (px) | Predicted photo (px) | Verdict |
|---|---|---|---|
| kneeling_chair | (1202, 2187) | (18244, -997) | wildly off-frame |
| rug_center | (894, 1629) | (-1444, 143) | off-frame |
| guard_rail_right | (1411, 2278) | (-666, 398) | off-frame |
| stair_opening | (1571, 2335) | (-218, 363) | off-frame |
| guard_rail_left | (292, 2278) | (495, 296) | plausible-looking but unverified |
| liz_chair | (517, 1708) | (578, 322) | plausible-looking but unverified |
| porthole_center | (123, 2258) | (473, 298) | wall-height, not floor -- also off-plane |

Four of seven land off-frame entirely; the rest are unverified guesses
at best. **Do not use this H for floor-level objects** (rug position,
chair/cabinet footprints, anything on the ground) -- re-derive a
separate floor-plane homography (see v3-v5 below) for those instead.

## Previous versions (superseded), kept for context

## How the v2 plan pixel coordinates were derived

`office_floor_plan_v2.svg` is a draw.io export with the diagram's exact
vector shape geometry (x, y, width, height per shape) embedded in its
`content` attribute as an mxGraphModel. Rather than eyeballing pixel
positions on a raster image:

1. The SVG was rasterized with `rsvg-convert` at 1910x2436 (2x its
   955x1218 viewBox) -- `qlmanage` (macOS QuickLook) was tried first but
   silently clipped the image to a square, cutting off the bottom third
   of the room (stairwell, guard rail, kneeling chair, porthole).
2. The mxGraphModel XML was extracted and parsed to get exact
   `(x, y, width, height)` for every labeled shape (couch, desks, rug,
   chairs, etc.), in the diagram's own coordinate space.
3. A least-squares affine transform (`pixel = scale * model + offset`)
   was fit using 3 independent reference shapes (CRAIG DESK, SENTINEL
   RIG, GREEN COUCH boxes) -- their pixel bounding boxes (found via
   flood-fill) matched their known model width/height aspect ratios to
   within ~1%, confirming the transform: `scale_x=1.9994, offset_x=2071.24`,
   `scale_y=1.9648, offset_y=804.30`.
4. All 5 calibration points' plan-side coordinates were computed through
   this transform, then visually verified by drawing them back onto the
   rendered plan -- all landed exactly on their intended shapes (see
   session transcript for the verification image).

This makes the plan-side coordinates essentially exact (sub-pixel),
removing plan-side eyeballing error entirely. Photo-side coordinates are
still hand-picked from the raster photo and carry the usual ~5-20px
estimation uncertainty.

## History: v3 collinearity (resolved), v4/v5 accuracy (still open)

**v3 (4 points):** exact fit, 0px residual, but an out-of-sample check
(projecting other known plan landmarks through H) showed six unrelated
landmarks collapsing onto nearly the same tiny region of the photo.
Cause: 3 of the 4 points (couch near-end, couch far-end, stairwell) sat
close to the same line in the floor plan -- close to the textbook
degenerate configuration for a 4-point homography.

**v4 (5 points, eyeballed plan coords):** point 5 (rug) added off that
line to break the collinearity. Fixed the collapse-to-a-point failure,
but surfaced a real residual (27.9px RMS) and the out-of-sample
landmarks still landed in visibly wrong places.

**v5 (5 points, current -- SVG-precise plan coords):** re-derived all
plan-side coordinates from the SVG's exact vector geometry instead of
eyeballing (see above). Conditioning is still fine (no collapse), but
the residual did not improve (31.5px RMS) and the same out-of-sample
landmarks (chairs, file cabinet, guard rail) still land in the wrong
places, clustered near the railing instead of their real photo
locations.

**Conclusion:** the eyeballing-precision hypothesis is now ruled out --
going from hand-picked to vector-exact plan coordinates did not fix the
accuracy problem, which confirms the real cause is height-mixing:
points 1-2 (couch armrest, monitor) sit ~2.5-4ft above the floor; points
4-5 (stairwell, rug) are at floor level. A homography is only exact for
points on a single plane -- mixing heights biases the fit toward an
ill-defined compromise plane that doesn't match any of them well.

**Practical takeaway that led to v6:** height-mixing was the real
problem, confirmed by restricting to a single elevated band (see v6
above) -- conditioning stayed fine and the out-of-sample floor-level
check now fails predictably/explicitly rather than silently, which is
the honest outcome for a plane-only tool used outside its valid range.

## Re-calibrating after the rig moves

1. Take a new photo from the rig.
2. Locate the same 4 physical landmarks in the new photo, staying in the
   ~1.5-2.5ft height band (armrest, cabinet-top, chair-seat) -- do not
   mix in floor-level or head-height points (see v6 above).
3. Update the `*_photo` coordinates in `homography.py`. If the floor
   plan itself changes, re-derive plan-side coordinates from the
   `.svg`'s embedded model (see "How the v2 plan pixel coordinates were
   derived") rather than eyeballing the raster PNG.
4. Re-run `python3 homography.py` to regenerate the `.npy` matrices.
5. If floor-level mapping is also needed, calibrate a **separate**
   homography using only floor-level points (v3-v5 above are a starting
   point, though none of those achieved a good residual either --
   floor-level correspondences may need points spread further apart to
   avoid the collinearity issue from v3).
# Floor plan <-> rig view calibration

Homography between `rig/office_floor_plan_v2.png` (top-down plan,
rendered from `rig/office_floor_plan_v2.svg`) and `rig/rig_view.png`
(SENTINEL RIG photo), for mapping floor-plane points between the two.

## Correction (2026-07-28)

Points 1 and 2 in the correspondence table below were originally labeled
"couch near-end armrest" and "couch far-end armrest" backwards relative
to the rig — visual inspection of `calibration_reference.png` against
the physical room confirmed the point marked "far" (photo pixel
(80, 310), left edge of frame) is actually the armrest **closer** to
SENTINEL RIG, and the point marked "near" (photo pixel (292, 285)) is
actually **farther**. Labels below are corrected; the plan/photo pixel
values themselves are unchanged, since the SVG-derived plan coordinates
were already visually re-verified against the rendered plan at the time
they were computed (see "How the v2 plan pixel coordinates were
derived" below) — only the near/far English description was wrong, not
the underlying correspondence data. The fitted homography matrices
(`H_plan_to_photo.npy` / `H_photo_to_plan.npy`) required no changes.

## Files

- `homography.py` -- point correspondences + normalized-DLT solver (numpy
  only, no OpenCV). Run it to regenerate the matrices below.
- `H_plan_to_photo.npy` / `H_photo_to_plan.npy` -- the fitted 3x3 homography
  and its inverse.
- `calibration_reference.png` -- side-by-side plan + photo with the 5
  calibration points marked, for re-anchoring after the rig moves.
- `degeneracy_check.png` -- diagnostic image, see "History" below.

## Correspondences used (v6, current -- 4 points, elevated plane only)

| # | Landmark | Floor plan (px) | Photo (px) | Approx. height |
|---|---|---|---|---|
| 1 | Couch far-end armrest, front-top corner | (1411, 1256) | (292, 285) | ~2-2.2ft |
| 2 | Couch near-end armrest, front-top corner | (1411, 1885) | (80, 310) | ~2-2.2ft |
| 3 | File cabinet top surface | (587, 1880) | (595, 308) | ~2.3-2.5ft |
| 4 | Craig chair, seat height | (402, 1413) | (540, 355) | ~1.5-1.8ft |

**This homography is only valid for points roughly 1.5-2.5ft above the
floor** (chair-seat to armrest/cabinet-top height). It deliberately
excludes: floor-level points (stairwell, rug, guard rail -- see v3-v5
history below) and the old monitor-top point (~4ft, too high). Floor-
level objects mapped through this H will carry substantially higher
position error -- confirmed below, not just theoretical.

A 5th same-band point (coffee table surface, ~1.3-1.5ft) was tried as a
consistency check and dropped: it pushed the RMS residual from 0px
(4-point exact fit) to ~32px, with the near-end armrest point alone
jumping to 56px error. Even a modest spread within "elevated" (1.3ft vs
2.0-2.5ft) is enough to measurably strain the single-plane assumption --
this homography is tightest for points near 1.5-2.5ft specifically, not
"elevated" in general.

### Out-of-sample check: floor-level degradation, confirmed

Projecting floor-level plan landmarks (not used in the fit) through this
elevated-plane H:

| Landmark | Plan (px) | Predicted photo (px) | Verdict |
|---|---|---|---|
| kneeling_chair | (1202, 2187) | (18244, -997) | wildly off-frame |
| rug_center | (894, 1629) | (-1444, 143) | off-frame |
| guard_rail_right | (1411, 2278) | (-666, 398) | off-frame |
| stair_opening | (1571, 2335) | (-218, 363) | off-frame |
| guard_rail_left | (292, 2278) | (495, 296) | plausible-looking but unverified |
| liz_chair | (517, 1708) | (578, 322) | plausible-looking but unverified |
| porthole_center | (123, 2258) | (473, 298) | wall-height, not floor -- also off-plane |

Four of seven land off-frame entirely; the rest are unverified guesses
at best. **Do not use this H for floor-level objects** (rug position,
chair/cabinet footprints, anything on the ground) -- re-derive a
separate floor-plane homography (see v3-v5 below) for those instead.

## Previous versions (superseded), kept for context

## How the v2 plan pixel coordinates were derived

`office_floor_plan_v2.svg` is a draw.io export with the diagram's exact
vector shape geometry (x, y, width, height per shape) embedded in its
`content` attribute as an mxGraphModel. Rather than eyeballing pixel
positions on a raster image:

1. The SVG was rasterized with `rsvg-convert` at 1910x2436 (2x its
   955x1218 viewBox) -- `qlmanage` (macOS QuickLook) was tried first but
   silently clipped the image to a square, cutting off the bottom third
   of the room (stairwell, guard rail, kneeling chair, porthole).
2. The mxGraphModel XML was extracted and parsed to get exact
   `(x, y, width, height)` for every labeled shape (couch, desks, rug,
   chairs, etc.), in the diagram's own coordinate space.
3. A least-squares affine transform (`pixel = scale * model + offset`)
   was fit using 3 independent reference shapes (CRAIG DESK, SENTINEL
   RIG, GREEN COUCH boxes) -- their pixel bounding boxes (found via
   flood-fill) matched their known model width/height aspect ratios to
   within ~1%, confirming the transform: `scale_x=1.9994, offset_x=2071.24`,
   `scale_y=1.9648, offset_y=804.30`.
4. All 5 calibration points' plan-side coordinates were computed through
   this transform, then visually verified by drawing them back onto the
   rendered plan -- all landed exactly on their intended shapes (see
   session transcript for the verification image).

This makes the plan-side coordinates essentially exact (sub-pixel),
removing plan-side eyeballing error entirely. Photo-side coordinates are
still hand-picked from the raster photo and carry the usual ~5-20px
estimation uncertainty.

## History: v3 collinearity (resolved), v4/v5 accuracy (still open)

**v3 (4 points):** exact fit, 0px residual, but an out-of-sample check
(projecting other known plan landmarks through H) showed six unrelated
landmarks collapsing onto nearly the same tiny region of the photo.
Cause: 3 of the 4 points (couch near-end, couch far-end, stairwell) sat
close to the same line in the floor plan -- close to the textbook
degenerate configuration for a 4-point homography.

**v4 (5 points, eyeballed plan coords):** point 5 (rug) added off that
line to break the collinearity. Fixed the collapse-to-a-point failure,
but surfaced a real residual (27.9px RMS) and the out-of-sample
landmarks still landed in visibly wrong places.

**v5 (5 points, current -- SVG-precise plan coords):** re-derived all
plan-side coordinates from the SVG's exact vector geometry instead of
eyeballing (see above). Conditioning is still fine (no collapse), but
the residual did not improve (31.5px RMS) and the same out-of-sample
landmarks (chairs, file cabinet, guard rail) still land in the wrong
places, clustered near the railing instead of their real photo
locations.

**Conclusion:** the eyeballing-precision hypothesis is now ruled out --
going from hand-picked to vector-exact plan coordinates did not fix the
accuracy problem, which confirms the real cause is height-mixing:
points 1-2 (couch armrest, monitor) sit ~2.5-4ft above the floor; points
4-5 (stairwell, rug) are at floor level. A homography is only exact for
points on a single plane -- mixing heights biases the fit toward an
ill-defined compromise plane that doesn't match any of them well.

**Practical takeaway that led to v6:** height-mixing was the real
problem, confirmed by restricting to a single elevated band (see v6
above) -- conditioning stayed fine and the out-of-sample floor-level
check now fails predictably/explicitly rather than silently, which is
the honest outcome for a plane-only tool used outside its valid range.

## Re-calibrating after the rig moves

1. Take a new photo from the rig.
2. Locate the same 4 physical landmarks in the new photo, staying in the
   ~1.5-2.5ft height band (armrest, cabinet-top, chair-seat) -- do not
   mix in floor-level or head-height points (see v6 above).
3. Update the `*_photo` coordinates in `homography.py`. If the floor
   plan itself changes, re-derive plan-side coordinates from the
   `.svg`'s embedded model (see "How the v2 plan pixel coordinates were
   derived") rather than eyeballing the raster PNG.
4. Re-run `python3 homography.py` to regenerate the `.npy` matrices.
5. If floor-level mapping is also needed, calibrate a **separate**
   homography using only floor-level points (v3-v5 above are a starting
   point, though none of those achieved a good residual either --
   floor-level correspondences may need points spread further apart to
   avoid the collinearity issue from v3).
