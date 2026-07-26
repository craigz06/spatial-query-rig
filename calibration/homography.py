import numpy as np

# Point correspondences: floor-plane landmarks, picked from
# office_floor_plan_v2.png (plan, rendered from office_floor_plan_v2.svg
# at 1910x2436) and rig_view.png (photo).
# Format: name -> (plan_xy, photo_xy)
correspondences = {
    "couch_near_end_armrest":  ((1411, 1256), (292, 285)),
    "liz_monitor_top_left":    ((130, 1143), (607, 233)),
    "couch_far_end_armrest":   ((1411, 1885), (80, 310)),
    "stair_opening_centroid":  ((1571, 2335), (385, 245)),
    "rug_center":              ((894, 1629), (372, 384)),
}

# Plan-side coordinates were derived from office_floor_plan_v2.svg's
# embedded drawio model (exact vector shape geometry), converted to pixel
# space via a least-squares affine fit (scale ~2.0, matches the SVG being
# rendered at 2x its 955x1218 viewBox) calibrated against 3 independent
# reference boxes (craig desk, sentinel rig, green couch) -- all 3 matched
# their known width/height aspect ratios to within ~1%. See
# rsvg_verify.png-style checks in the session for validation; the
# transform is:
#   pixel_x = 1.9994 * model_x + 2071.24
#   pixel_y = 1.9648 * model_y + 804.30
#
# liz_monitor_top_left uses the CRAIG DESK box's top-left corner as a
# proxy -- the plan draws the desk footprint, not individual monitors.
#
# rug_center uses the *overall rug bounding box center* on the plan side
# (now that v2 draws the actual rug artwork/outline, not just a text
# label) and the *pinecone panel* on the photo side (verified by marked
# crop) -- these are both "roughly central on the rug" but not the exact
# same sub-feature, since the rug's true bottom edge is cut off by the
# photo's frame and its exact pattern position could not be reliably
# resolved in the small plan graphic (occluded by FOV-cone overlay lines).

# out-of-plane / cross-check points, NOT used in the fit -- for
# sanity-checking only. porthole is a wall-height feature (expected to
# reproject poorly, confirms plane-only validity); the rest are other
# floor-level plan landmarks (also derived from the SVG model via the
# transform above) used to check whether the fit generalizes beyond the
# 5 points actually used.
validation_points = {
    "porthole_center":   ((123, 2258), None),
    "craig_chair":       ((402, 1413), None),
    "liz_chair":         ((517, 1708), None),
    "file_cabinet":      ((587, 1880), None),
    "kneeling_chair":    ((1202, 2187), None),
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
