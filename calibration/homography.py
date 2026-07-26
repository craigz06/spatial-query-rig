import numpy as np

# Point correspondences: floor-plane landmarks, picked from
# office_floor_plan.png (plan) and rig_view.png (photo).
# Format: name -> (plan_xy, photo_xy)
correspondences = {
    "couch_near_end_armrest":  ((719, 161), (292, 285)),
    "liz_monitor_top_left":    ((205, 114), (607, 233)),
    "couch_far_end_armrest":   ((719, 415), (80, 310)),
    "stair_opening_centroid":  ((782, 600), (385, 245)),
    "rug_pinecone_panel":      ((510, 313), (372, 384)),
}

# liz_monitor_top_left uses the CRAIG DESK box's top-left corner in the
# floor plan as a proxy -- the plan doesn't draw individual monitors, only
# the desk footprint, so this is an approximation of where the left
# monitor sits.
#
# rug_pinecone_panel uses the plan's "RUG" text label as a proxy for the
# plan-side point -- the plan doesn't draw the rug's outline either, only
# a text label placed somewhere on/near it. This 5th point was added
# specifically to break the near-collinearity of the other 4 points
# (see FINDINGS.md), since it sits at plan x=510, well off the x~719-782
# line the other points cluster around.

# out-of-plane points, NOT used in the fit (wall-height features) -- for
# sanity-checking only, expected to reproject poorly since homography
# assumes a single plane (the floor).
validation_points = {
    "porthole_center": ((202, 584), None),
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
print("Out-of-plane validation point (porthole, on wall not floor):")
for name, (plan_xy, _) in validation_points.items():
    pred = apply_h(H, [plan_xy])[0]
    print(f"  {name}: plan={plan_xy} -> predicted photo={pred.round(1)}"
          f"  (visually, porthole is at ~(700,110) in photo -- large mismatch expected, confirms plane-only validity)")

import os
_here = os.path.dirname(os.path.abspath(__file__))
np.save(os.path.join(_here, "H_plan_to_photo.npy"), H)
np.save(os.path.join(_here, "H_photo_to_plan.npy"), Hinv)
