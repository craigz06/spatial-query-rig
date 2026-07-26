import numpy as np

# Point correspondences: floor-plane landmarks, picked from
# office_floor_plan_v2.png (plan, rendered from office_floor_plan_v2.svg
# at 1910x2436) and rig_view.png (photo).
# Format: name -> (plan_xy, photo_xy)
# v6: ELEVATED-PLANE calibration. All 4 points sit roughly chair-seat to
# armrest/cabinet-top height (~1.5-2.5ft above the floor) -- floor-level
# points (stairwell, rug, guard rail) and the too-high monitor-top point
# were deliberately dropped. See FINDINGS.md "v6" section for why, and
# for the valid height band this homography should be trusted within.
#
# A 5th candidate point (craig_desk_surface, desk box center) was tried
# and dropped: it produced a ~719px reprojection outlier while the other
# 4 points held to <25px. Cause: the CRAIG DESK plan box is wide (230
# units, spans both monitors) and the floor plan is a schematic/cognitive
# map, not a precisely-scaled drawing (its own width:height ratios don't
# match the couch's real 11ft:2.8ft ratio) -- so the box's geometric
# center doesn't reliably correspond to a specific real-world point the
# way a small, well-defined object's does.
correspondences = {
    "couch_near_end_armrest": ((1411, 1256), (292, 285)),   # ~2-2.2ft (armrest)
    "couch_far_end_armrest":  ((1411, 1885), (80, 310)),    # ~2-2.2ft (armrest)
    "file_cabinet_top":       ((587, 1880), (595, 308)),    # ~2.3-2.5ft (cabinet top)
    "craig_chair_seat":       ((402, 1413), (540, 355)),    # ~1.5-1.8ft (chair seat)
}
# A 5th point (coffee table surface, ~1.3-1.5ft) was tested for
# consistency and DROPPED: it pushed the RMS residual from 0px (4-pt
# exact fit) to ~32px, with couch_far_end_armrest alone jumping to 56px
# error. Even within this restricted "elevated" band, height still
# matters -- 1.3ft (table) vs 2.0-2.5ft (armrest/cabinet) is enough
# spread to measurably strain the single-plane assumption. Kept to 4
# points, all closer to the intended 1.5-2.5ft band, for a clean fit.
# See FINDINGS.md "v6" section.

# Plan-side coordinates were derived from office_floor_plan_v2.svg's
# embedded drawio model (exact vector shape geometry), converted to pixel
# space via a least-squares affine fit (scale ~2.0, matches the SVG being
# rendered at 2x its 955x1218 viewBox) calibrated against 3 independent
# reference boxes (craig desk, sentinel rig, green couch) -- all 3 matched
# their known width/height aspect ratios to within ~1%. The transform is:
#   pixel_x = 1.9994 * model_x + 2071.24
#   pixel_y = 1.9648 * model_y + 804.30
#
# Since the floor plan is a 2D top-down footprint, plan-side (x,y) is the
# same regardless of which height on an object you pick -- craig_desk_surface
# and file_cabinet_top both use their object's plan-footprint center;
# what changed vs. earlier versions is the PHOTO-side pixel, deliberately
# picked at ~1.5-2.5ft height on each object instead of floor level or
# (for the old monitor point) ~4ft monitor-top height.

# out-of-plane / cross-check points, NOT used in the fit -- for
# sanity-checking only. porthole is a wall-height feature; the rest are
# floor-level plan landmarks. Both groups are expected to reproject
# poorly under this elevated-plane calibration -- see FINDINGS.md.
validation_points = {
    "porthole_center":   ((123, 2258), None),
    "liz_chair":         ((517, 1708), None),
    "kneeling_chair":    ((1202, 2187), None),
    "stair_opening":     ((1571, 2335), None),
    "rug_center":        ((894, 1629), None),
    "guard_rail_left":   ((292, 2278), None),
    "guard_rail_right":  ((1411, 2278), None),
}

def normalize(pts):
    pts = np.asarray(pts, dtype=float)
    centroid = pts.mean(axis=0)
    d = np.sqrt(((pts - centroid) ** 2).sum(axis=1)).mean()
    scale = np.sqrt(2) / d if d > 0 else 1.0
    T = np.array([
        [scale, 0, -scale * centroid[0]],
        [0, scale, -scale * centroid[1]],
        [0, 0, 1],
    ])
    pts_h = np.hstack([pts, np.ones((len(pts), 1))])
    pts_n = (T @ pts_h.T).T
    return pts_n[:, :2], T

def dlt_homography(src, dst):
    """Solve H such that dst ~ H @ src (both Nx2, N>=4)."""
    src_n, Ts = normalize(src)
    dst_n, Td = normalize(dst)
    A = []
    for (x, y), (xp, yp) in zip(src_n, dst_n):
        A.append([-x, -y, -1, 0, 0, 0, x * xp, y * xp, xp])
        A.append([0, 0, 0, -x, -y, -1, x * yp, y * yp, yp])
    A = np.array(A)
    _, _, Vt = np.linalg.svd(A)
    H_n = Vt[-1].reshape(3, 3)
    H = np.linalg.inv(Td) @ H_n @ Ts
    return H / H[2, 2]

def apply_h(H, pts):
    pts = np.asarray(pts, dtype=float)
    pts_h = np.hstack([pts, np.ones((len(pts), 1))])
    out = (H @ pts_h.T).T
    return out[:, :2] / out[:, 2:3]

plan_pts = np.array([v[0] for v in correspondences.values()])
photo_pts = np.array([v[1] for v in correspondences.values()])

H = dlt_homography(plan_pts, photo_pts)
Hinv = np.linalg.inv(H)
Hinv /= Hinv[2, 2]

print("Homography H (plan -> photo pixel coords):")
print(np.array2string(H, precision=5, suppress_small=True))
print()
print("Inverse homography H_inv (photo -> plan pixel coords):")
print(np.array2string(Hinv, precision=5, suppress_small=True))
print()

print("Per-point reprojection check (plan -> photo via H):")
reproj = apply_h(H, plan_pts)
errs = np.linalg.norm(reproj - photo_pts, axis=1)
for name, pred, actual, err in zip(correspondences.keys(), reproj, photo_pts, errs):
    print(f"  {name:28s} predicted={pred.round(1)} actual={actual} err={err:.2f}px")
print(f"  RMS error: {np.sqrt((errs**2).mean()):.3f}px")

print()
print("Out-of-sample check (other known plan landmarks, not used in the fit):")
for name, (plan_xy, _) in validation_points.items():
    pred = apply_h(H, [plan_xy])[0]
    print(f"  {name:20s} plan={plan_xy} -> predicted photo={pred.round(1)}")

import os
_here = os.path.dirname(os.path.abspath(__file__))
np.save(os.path.join(_here, "H_plan_to_photo.npy"), H)
np.save(os.path.join(_here, "H_photo_to_plan.npy"), Hinv)
