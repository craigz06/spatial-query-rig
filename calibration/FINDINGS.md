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

## Correspondences used (v5, current -- 5 points, precise plan coords)

| # | Landmark | Floor plan (px) | Photo (px) |
|---|---|---|---|
| 1 | Couch near-end armrest, front-top corner | (1411, 1256) | (292, 285) |
| 2 | Left monitor top-left corner (proxy: CRAIG DESK box top-left, plan draws the desk footprint not individual monitors) | (130, 1143) | (607, 233) |
| 3 | Couch far-end armrest, front-top corner | (1411, 1885) | (80, 310) |
| 4 | Stairwell opening centroid | (1571, 2335) | (385, 245) |
| 5 | Rug center (plan: overall rug bbox center; photo: pinecone panel -- see note) | (894, 1629) | (372, 384) |

Both couch points intentionally reference the *armrest* (not the floor
corner) since the floor corners are occluded by a coffee table/guitar in
the reference photo. This means the fit is anchored slightly above the
true floor plane (~2ft), not on it.

Point 5's plan and photo sides are not quite the same sub-feature: the
plan side uses the rug's overall bounding-box center (now that v2 draws
the actual rug artwork), while the photo side uses the pinecone panel
specifically (verified by a marked crop) since the rug's true bottom
edge is cut off by the photo's frame, so no true "center" is visible
there. Both are "roughly central on the rug," which is the best
available match.

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

**Practical takeaway:** if better accuracy is needed, re-pick
correspondence points that are all genuinely at the same height (e.g.
all floor-level, using visible floor-plane corners only -- the SVG
model makes plan-side floor corners for any shape trivial to get
precisely), rather than mixing furniture-top and floor-level landmarks.

## Re-calibrating after the rig moves

1. Take a new photo from the rig.
2. Locate the same 5 physical landmarks in the new photo (ideally
   staying at one consistent height, per the note above).
3. Update the `*_photo` coordinates in `homography.py`. If the floor
   plan itself changes, re-derive plan-side coordinates from the
   `.svg`'s embedded model (see "How the v2 plan pixel coordinates were
   derived") rather than eyeballing the raster PNG.
4. Re-run `python3 homography.py` to regenerate the `.npy` matrices.
