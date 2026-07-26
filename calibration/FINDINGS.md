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

## Correspondences used (v4, current -- 5 points)

| # | Landmark | Floor plan (px) | Photo (px) |
|---|---|---|---|
| 1 | Couch near-end armrest, front-top corner | (719, 161) | (292, 285) |
| 2 | Left monitor top-left corner (proxy: CRAIG DESK box top-left, plan doesn't draw individual monitors) | (205, 114) | (607, 233) |
| 3 | Couch far-end armrest, front-top corner | (719, 415) | (80, 310) |
| 4 | Stairwell opening centroid | (782, 600) | (385, 245) |
| 5 | Rug pinecone panel, center (proxy: plan's "RUG" text label, plan doesn't draw the rug outline) | (510, 313) | (372, 384) |

Both couch points intentionally reference the *armrest* (not the floor
corner) since the floor corners are occluded by a coffee table/guitar in
the reference photo. This means the fit is anchored slightly above the
true floor plane (~2ft), not on it.

## History: v3 collinearity issue (resolved) and v4 accuracy issue (open)

**v3 (4 points, points 1-4 only):** exact fit, 0px residual, but an
out-of-sample check (projecting other known plan landmarks through H)
showed six unrelated landmarks collapsing onto nearly the same tiny
region of the photo. Cause: 3 of the 4 points (couch near-end, couch
far-end, stairwell) sat close to the same vertical line in the floor
plan (x ~ 719-782) -- close to the textbook degenerate configuration for
a 4-point homography.

**v4 (5 points, current):** point 5 (rug) was added specifically off
that line (plan x=510) to break the collinearity. This worked --
`degeneracy_check.png` (regenerated for v4) shows the same six
out-of-sample landmarks now spread out across the photo instead of
collapsing to one spot.

However, fixing conditioning surfaced a second, previously-hidden
problem: the fit is now overdetermined (5 points, 4 minimum) and has a
real residual of **27.9px RMS** (see `homography.py` output), and the
out-of-sample landmarks still land in visibly wrong places (clustered
near the railing rather than near the actual chairs/desk they represent).

Likely cause: the 5 correspondence points are not actually coplanar in
the real room. Points 1-2 (couch armrest, monitor) sit ~2.5-4ft above
the floor; points 4-5 (stairwell, rug) are at floor level. A homography
is only exact for points on a single plane -- mixing heights biases the
fit toward an ill-defined compromise plane that doesn't match any of
them well.

**Practical takeaway:** v4 is better-conditioned than v3 (no more
collapse-to-a-point failure), but its absolute accuracy off the 5 fit
points is still unverified and likely poor given the height-mixing
problem. Next step, if better accuracy is needed: re-pick correspondence
points that are all genuinely at the same height (e.g. all floor-level,
using visible floor-plane corners only), rather than mixing furniture-top
and floor-level landmarks.

## Re-calibrating after the rig moves

1. Take a new photo from the rig.
2. Locate the same 4 (ideally 5+, see above) physical landmarks in the
   new photo.
3. Update the `*_photo` coordinates in `homography.py`.
4. Re-run `python3 homography.py` to regenerate the `.npy` matrices.
