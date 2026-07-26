# Floor plan <-> rig view calibration

Homography between `rig/office_floor_plan.png` (top-down plan) and
`rig/rig_view.png` (SENTINEL RIG photo), for mapping floor-plane points
between the two.

## Files

- `homography.py` -- point correspondences + normalized-DLT solver (numpy
  only, no OpenCV). Run it to regenerate the matrices below.
- `H_plan_to_photo.npy` / `H_photo_to_plan.npy` -- the fitted 3x3 homography
  and its inverse.
- `calibration_reference.png` -- side-by-side plan + photo with the 4
  calibration points marked, for re-anchoring after the rig moves.
- `degeneracy_check.png` -- diagnostic image, see "Known issue" below.

## Correspondences used (v3, current)

| # | Landmark | Floor plan (px) | Photo (px) |
|---|---|---|---|
| 1 | Couch near-end armrest, front-top corner | (719, 161) | (292, 285) |
| 2 | Left monitor top-left corner (proxy: CRAIG DESK box top-left, plan doesn't draw individual monitors) | (205, 114) | (607, 233) |
| 3 | Couch far-end armrest, front-top corner | (719, 415) | (80, 310) |
| 4 | Stairwell opening centroid | (782, 600) | (385, 245) |

Both couch points intentionally reference the *armrest* (not the floor
corner) since the floor corners are occluded by a coffee table/guitar in
the reference photo. This means the fit is anchored slightly above the
true floor plane (~2ft), not on it.

## Known issue: fit is poorly conditioned

`degeneracy_check.png` projects six other known plan landmarks (both
couch-side chairs, the file cabinet, the kneeling chair, both guard-rail
ends) through this homography as an out-of-sample check. They all
collapse onto nearly the same small region of the photo
(~x=520-630, y=230-250) regardless of how far apart they actually are in
the room -- a sign of a near-degenerate fit.

Cause: 3 of the 4 correspondence points (couch near-end, couch far-end,
stairwell) sit close to the same vertical line in the floor plan
(x ~ 719-782). Three near-collinear points among four is close to the
textbook degenerate configuration for a 4-point homography: technically
invertible, but numerically unstable everywhere except close to that
line.

**Practical takeaway:** this H is only trustworthy near the couch and
stairwell/monitor area of the photo. It should not be trusted for
mapping points elsewhere in the room (center rug, chairs, file cabinet)
until a 5th correspondence point is added somewhere off that line --
e.g. the rug, or a central object -- to stabilize the fit.

## Re-calibrating after the rig moves

1. Take a new photo from the rig.
2. Locate the same 4 (ideally 5+, see above) physical landmarks in the
   new photo.
3. Update the `*_photo` coordinates in `homography.py`.
4. Re-run `python3 homography.py` to regenerate the `.npy` matrices.
