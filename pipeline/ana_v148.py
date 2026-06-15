#!/usr/bin/env python3
"""
ANA v1.48 — Detective Measurement Layer
Author: Craig C. Cline / seeitwith.org
AI co-author: Claude (Anthropic)
Date: June 2026
Patent: US Provisional #64/056,727

OBJECTIVE (v1.45 -> v1.48): CAUSAL FENCE — three targeted patches to
    prevent out-of-order frame data from corrupting signal computation:

    [1] compute_hdisp_spread — index monotonicity fence on the keyframe
        seek loop. linspace rounding on short clips can produce duplicate
        or non-monotonic indices; the fence skips any backward seek so
        kf_timeline is strictly forward in time before it leaves this
        function.

    [2] build_spacetime_events — kf_timeline sorted by t before near[]
        extraction. The approach/recede direction logic runs over near[]
        sequentially; if timeline entries arrived out of order (possible
        when stereo and temporal sampling use different granularities)
        the direction logic would fire on the wrong order, producing
        phantom APPROACH or RECEDE events. One sort line closes this.

    [3] Output filenames and VERSION constant updated to v1.48 throughout.
        No signal math changed. No thresholds changed. Measurement layer
        is identical to v1.45 — only causal ordering is hardened.

OBJECTIVE (v1.44 -> v1.45): DETECTIVE, NOT AUTHENTICATOR.
    Deepfake detection is DELETED as a goal. No AUTHENTIC/SYNTHETIC verdict
    is produced anywhere. ANA measures; SCO (in Claude) acts as a detective
    trying to understand the user's intent from the video and answer them —
    as if on a FaceTime call — constrained to view in 3D and watch
    sequentially.

    The video subject IS the user. They may ask a question in words, in
    gesture, or both. ANA's job is to hand SCO everything needed to
    understand the action:

      questioner_state        — behavioral/spatial read of the person
      spacetime_events        — NEW: timestamped 3D event timeline.
                                Approach-toward-camera, recede, motion
                                spikes, settles. This is what catches a
                                hand reaching toward the lens.
      proximity               — NEW: hyperstereo check. Subject too close
                                to the rig produces extreme parallax;
                                depth numbers are then proximity readings,
                                not room structure.
      room_spatial_reference  — spatial fingerprint of the room (constant
                                across sessions; POV shifts slightly)

    SCO protocol footer (in the report): take in everything; answer the
    person directly; add visual detail when applicable; ask for missing
    information; leave the spacetime view to LAST, then check assumptions
    against it for anything missed in frame-by-frame analysis.

Raw signals (measurement layer, no classification):
  TEMPORAL — Delta CoV: frame-to-frame luminance variance.
             Read as behavioral energy.
  SPATIAL  — H-disparity statistics across stereo SBS keyframes.
             Read as presence, proximity, and gesture-in-depth.

CLI:
    python ana_v145.py video.mp4 --force-stereo --seam-x 836
    python ana_v145.py video.mp4 --output-dir /path --quiet

Outputs (no new files — everything folds into json + md + png + anaglyph):
    {stem}_ana_v1.48.json
    {stem}_ana_v1.48_report.md
    {stem}_ana_v1.48_orient.png
    {stem}_ana_v1.48_anaglyph.mp4   (stereo only)

Called automatically by DCI v1.12.1 after [S]top.
"""


import sys
import os
import json
import argparse
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants / thresholds
# ---------------------------------------------------------------------------

VERSION = "1.48"
REVISION_DATE = "2026-06-13"
AUTHOR = "Craig C. Cline"
AI_COANALYST = "Claude (Anthropic)"


# (Legacy verdict thresholds removed in v1.45 — measurement only.)

# Stereo detection: width/height > 2.5 = SBS pair (legacy gate)
# Bypassed when --force-stereo is set.
STEREO_ASPECT_THRESHOLD = 2.5

# Sampling
DELTA_COV_MAX_FRAMES = 300   # sample up to this many frames for CoV
ORIENT_SAMPLE_RATE = 15       # fps equivalent for orientation plot


# ---------------------------------------------------------------------------
# Orientation plot
# ---------------------------------------------------------------------------

def compute_frame_diffs(cap: cv2.VideoCapture,
                         max_frames: int = DELTA_COV_MAX_FRAMES
                         ) -> Tuple[np.ndarray, float, int]:
    """Return (frame_diffs, fps, total_frames). Resets cap to frame 0."""
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    step = max(1, total // max_frames)
    diffs = []
    prev_gray = None
    frame_idx = 0

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev_gray is not None:
            diffs.append(float(np.mean(np.abs(gray - prev_gray))))
        prev_gray = gray
        frame_idx += step
        if frame_idx >= total:
            break

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return np.array(diffs, dtype=np.float32), fps, total


def save_orient_png(diffs: np.ndarray,
                    fps: float,
                    total_frames: int,
                    output_path: str,
                    video_name: str,
                    cov: float,
                    read_label: str) -> bool:
    """Save spacetime orientation PNG."""
    if not MATPLOTLIB_AVAILABLE:
        return False
    try:
        duration = total_frames / fps
        times = np.linspace(0, duration, len(diffs))

        fig, ax = plt.subplots(figsize=(10, 3))
        ax.plot(times, diffs, color='steelblue', linewidth=0.8)
        ax.axhline(np.mean(diffs), color='orange', linestyle='--',
                   linewidth=0.8, label=f'Mean={np.mean(diffs):.2f}')
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Frame delta (mean abs)')
        ax.set_title(f'ANA v{VERSION} Orientation: {video_name}\n'
                     f'Delta CoV={cov:.3f}  |  Read: {read_label}')
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(output_path, dpi=100)
        plt.close(fig)
        return True
    except Exception as e:
        print(f"[ANA] Orient PNG error: {e}")
        return False


# ---------------------------------------------------------------------------
# Signal 1 — Delta CoV  (temporal)
# ---------------------------------------------------------------------------

def compute_delta_cov(diffs: np.ndarray) -> Dict:
    """
    Coefficient of Variation of frame-to-frame luminance delta.
    CoV = std(diffs) / mean(diffs)
    """
    if len(diffs) < 3:
        return {"success": False, "reason": "insufficient_frames"}

    mean_d = float(np.mean(diffs))
    std_d  = float(np.std(diffs))

    if mean_d < 1e-6:
        return {"success": False, "reason": "static_video_mean_near_zero"}

    cov = std_d / mean_d

    return {
        "success": True,
        "delta_cov": round(cov, 4),
        "mean_delta": round(mean_d, 4),
        "std_delta":  round(std_d, 4),
        "n_frames":   len(diffs),
    }


# ---------------------------------------------------------------------------
# Signal 2 — H-disparity spread  (spatial, stereo only)
# ---------------------------------------------------------------------------

def is_stereo_sbs(cap: cv2.VideoCapture) -> bool:
    """Legacy aspect-ratio gate. Bypassed when force_stereo=True."""
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    return (w / h) > STEREO_ASPECT_THRESHOLD if h > 0 else False


def compute_hdisp_spread(cap: cv2.VideoCapture,
                          n_keyframes: int = 32,
                          seam_x: Optional[int] = None) -> Dict:
    """
    Measure horizontal disparity spread across stereo SBS keyframes.
    Uses ORB features matched between left/right eyes.
    Returns RMS spread of horizontal disparity (px).

    seam_x: divider column supplied by DCI (off-center rigs preserved).
            Defaults to frame-center if not supplied.
    """
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    eye_w = w // 2
    if seam_x is None:
        seam_x = eye_w
    seam_band = 8  # px each side of seam to exclude

    orb = cv2.ORB_create(nfeatures=500)
    bf  = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    h_disparities = []
    kf_means = []      # per-keyframe mean disparity — for consistency check
    kf_timeline = []   # per-keyframe spacetime samples (t, mean, nearest)
    keyframe_indices = np.linspace(0, total - 1, n_keyframes, dtype=int)

    # Causal fence [1]: enforce strict forward monotonicity on seeks.
    # linspace rounding on short clips can produce duplicate or non-monotonic
    # integer indices. Any backward or duplicate seek would corrupt kf_timeline
    # ordering before it reaches build_spacetime_events.
    _last_kf_idx = -1

    for idx in keyframe_indices:
        if int(idx) <= _last_kf_idx:
            continue   # causal fence — skip backward or duplicate seek
        _last_kf_idx = int(idx)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if not ret:
            continue

        # Split SBS into left/right eyes, excluding seam band
        left  = cv2.cvtColor(
            frame[:, :seam_x - seam_band], cv2.COLOR_BGR2GRAY)
        right = cv2.cvtColor(
            frame[:, seam_x + seam_band:], cv2.COLOR_BGR2GRAY)

        kp_l, des_l = orb.detectAndCompute(left, None)
        kp_r, des_r = orb.detectAndCompute(right, None)

        if des_l is None or des_r is None or len(des_l) < 5 or len(des_r) < 5:
            continue

        matches = bf.match(des_l, des_r)
        if len(matches) < 5:
            continue

        kf_disps = []
        for m in matches:
            xl = kp_l[m.queryIdx].pt[0]
            xr = kp_r[m.trainIdx].pt[0]
            d = xr - xl
            h_disparities.append(d)
            kf_disps.append(d)
        if len(kf_disps) >= 20:
            kf_means.append(float(np.mean(kf_disps)))
            kf_timeline.append({
                "t": round(float(idx) / fps, 2),
                "mean_disp": round(float(np.mean(kf_disps)), 2),
                "near_disp": round(float(np.percentile(kf_disps, 90)), 2),
                "n": len(kf_disps),
            })

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    if len(h_disparities) < 10:
        return {
            "success": False,
            "reason": "insufficient_matches",
            "n_matches": len(h_disparities)
        }

    arr = np.array(h_disparities)
    # Remove gross outliers (> 3 sigma)
    mu, sig = np.mean(arr), np.std(arr)
    arr = arr[np.abs(arr - mu) < 3 * sig]

    spread = float(np.std(arr))   # RMS spread = std of disparity distribution
    mean_d = float(np.mean(arr))

    # ---- Depth structure metrics (SCO reference) ----
    # Total disparity range — how much depth relief is in the scene
    disp_range = float(np.max(arr) - np.min(arr))

    # Depth layers — histogram bins above 10% of peak count
    # Each bin above threshold represents a distinct disparity cluster = depth plane
    hist, _ = np.histogram(arr, bins=20)
    depth_layers = int(np.sum(hist > 0.10 * hist.max()))

    # Consistency — std of per-keyframe mean disparity
    # Low = depth structure stable over time (authentic); High = flickering
    consistency_std = float(np.std(kf_means)) if len(kf_means) > 1 else 0.0

    # Subject/background separation — mean(top 25%) - mean(bottom 25%)
    # Proxy for foreground vs background depth gap; constrained to evidence in hand
    q25 = float(np.percentile(arr, 25))
    q75 = float(np.percentile(arr, 75))
    lo_mean = float(arr[arr <= q25].mean()) if np.any(arr <= q25) else mean_d
    hi_mean = float(arr[arr >= q75].mean()) if np.any(arr >= q75) else mean_d
    subject_bg_sep = round(abs(hi_mean - lo_mean), 3)

    # Eye width for proximity assessment (narrower side governs)
    eye_w_left = seam_x - seam_band
    eye_w_right = w - (seam_x + seam_band)
    eye_w_min = min(eye_w_left, eye_w_right)

    return {
        "success": True,
        "hdisp_spread_px": round(spread, 3),
        "hdisp_mean_px": round(mean_d, 3),
        "n_matches": len(arr),
        "n_keyframes": n_keyframes,
        "seam_x": seam_x,
        "eye_width_left_px": eye_w_left,
        "eye_width_right_px": eye_w_right,
        "eye_width_min_px": eye_w_min,
        "disparity_range_px": round(disp_range, 3),
        "depth_layers": depth_layers,
        "disparity_consistency_std": round(consistency_std, 3),
        "subject_bg_separation_px": subject_bg_sep,
        "keyframe_timeline": kf_timeline,
    }


# ---------------------------------------------------------------------------
# Anaglyph render  (stereo only)
# ---------------------------------------------------------------------------

def render_anaglyph(video_path: str, output_path: str,
                    seam_x: Optional[int] = None) -> bool:
    """Render red-cyan anaglyph MP4 from SBS stereo source."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False

    fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    eye_w = w // 2
    if seam_x is None:
        seam_x = eye_w
    seam_band = 8

    # Output is half-width (one eye size)
    out_w = seam_x - seam_band

    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    writer = cv2.VideoWriter(output_path, fourcc, fps, (out_w, h))
    if not writer.isOpened():
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_path, fourcc, fps, (out_w, h))

    written = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        left_bgr  = frame[:, :seam_x - seam_band]
        right_bgr = frame[:, seam_x + seam_band: seam_x + seam_band + out_w]

        if right_bgr.shape[1] < out_w:
            right_bgr = cv2.resize(right_bgr, (out_w, h))

        # Red channel from left, cyan (G+B) from right
        anaglyph = np.zeros((h, out_w, 3), dtype=np.uint8)
        anaglyph[:, :, 2] = cv2.cvtColor(left_bgr,  cv2.COLOR_BGR2GRAY)  # R
        anaglyph[:, :, 1] = cv2.cvtColor(right_bgr, cv2.COLOR_BGR2GRAY)  # G
        anaglyph[:, :, 0] = cv2.cvtColor(right_bgr, cv2.COLOR_BGR2GRAY)  # B

        writer.write(anaglyph)
        written += 1

    cap.release()
    writer.release()
    return written > 0


# ---------------------------------------------------------------------------
# Spacetime Events  (v1.45 — the sequential 3D record)
# ---------------------------------------------------------------------------

# Proximity: mean disparity beyond this fraction of eye width = hyperstereo
PROXIMITY_CLOSE_FRAC = 0.06     # > 6% of eye width = CLOSE
PROXIMITY_HYPER_FRAC = 0.15     # > 15% = TOO_CLOSE_FOR_RIG (hyperstereo)
# Approach detection: nearest-object disparity rising by this much between
# consecutive keyframe samples = movement toward camera
APPROACH_STEP_FRAC = 0.02       # 2% of eye width per step
MOTION_SPIKE_SIGMA = 2.0        # diffs > mean + 2*std = motion spike


def build_spacetime_events(diffs: np.ndarray, fps: float, total_frames: int,
                           spatial: Optional[Dict]) -> Dict:
    """
    Timestamped event timeline merging the temporal stream (motion spikes)
    with the depth stream (approach/recede of the nearest object).
    This is the record SCO reviews LAST to check assumptions — it is what
    catches a hand reaching toward the lens that frame-by-frame summary
    statistics wash out.
    """
    events = []

    # --- Motion spikes from the temporal stream ---
    if len(diffs) >= 3:
        duration = total_frames / fps
        times = np.linspace(0, duration, len(diffs))
        mu, sig = float(np.mean(diffs)), float(np.std(diffs))
        thr = mu + MOTION_SPIKE_SIGMA * sig
        in_spike = False
        for t, d in zip(times, diffs):
            if d > thr and not in_spike:
                events.append({"t": round(float(t), 2), "type": "MOTION_SPIKE",
                               "magnitude": round(float(d / (mu + 1e-6)), 2),
                               "detail": f"frame delta {d:.1f} vs mean {mu:.1f}"})
                in_spike = True
            elif d <= mu and in_spike:
                in_spike = False

    # --- Approach / recede from the depth stream (stereo only) ---
    proximity = {"class": "UNKNOWN", "reason": "no stereo signal"}
    if spatial and spatial.get("success"):
        tl = spatial.get("keyframe_timeline", [])
        # Causal fence [2]: sort timeline by t before extracting near[].
        # The approach/recede direction logic runs sequentially over near[];
        # out-of-order entries would produce phantom APPROACH/RECEDE events.
        tl = sorted(tl, key=lambda k: k["t"])
        eye_w = spatial.get("eye_width_min_px", 1) or 1
        step_thr = APPROACH_STEP_FRAC * eye_w

        # Median-filter the nearest-object series (window 3) to suppress
        # spurious-match jitter, then collapse consecutive same-direction
        # steps into single events spanning start -> end.
        if len(tl) >= 3:
            raw_near = [k["near_disp"] for k in tl]
            near = [raw_near[0]] + [
                float(np.median(raw_near[j-1:j+2]))
                for j in range(1, len(raw_near)-1)
            ] + [raw_near[-1]]
        else:
            near = [k["near_disp"] for k in tl]

        run_dir, run_start, run_v0 = 0, None, None
        def _close_run(end_i):
            v1 = near[end_i]
            mag = v1 - run_v0
            if abs(mag) < step_thr * 1.5:   # ignore sub-threshold runs
                return
            etype = ("APPROACH_TOWARD_CAMERA" if mag > 0 else "RECEDE")
            verb = ("moved toward the lens" if mag > 0 else "withdrew from the lens")
            events.append({"t": tl[run_start]["t"], "type": etype,
                           "t_end": tl[end_i]["t"],
                           "magnitude": round(abs(mag), 1),
                           "detail": (f"nearest object {run_v0:.0f} -> {v1:.0f}px "
                                      f"over {tl[run_start]['t']:.1f}-{tl[end_i]['t']:.1f}s — {verb}")})

        for j in range(1, len(near)):
            d = near[j] - near[j-1]
            direction = 1 if d > step_thr else (-1 if d < -step_thr else 0)
            if direction != 0 and run_dir == 0:
                run_dir, run_start, run_v0 = direction, j-1, near[j-1]
            elif run_dir != 0 and direction == -run_dir:
                _close_run(j-1)
                run_dir, run_start, run_v0 = direction, j-1, near[j-1]
            elif run_dir != 0 and direction == 0:
                _close_run(j-1)
                run_dir = 0
        if run_dir != 0:
            _close_run(len(near)-1)

        # --- Proximity / hyperstereo classification ---
        mean_frac = abs(spatial.get("hdisp_mean_px", 0)) / eye_w
        if mean_frac > PROXIMITY_HYPER_FRAC:
            proximity = {"class": "TOO_CLOSE_FOR_RIG",
                         "mean_disparity_frac_of_eye": round(mean_frac, 3),
                         "reason": ("Hyperstereo regime — subject so close that "
                                    "parallax is extreme. Depth numbers describe "
                                    "PROXIMITY, not room structure. Treat range/"
                                    "layer counts as proximity artifacts.")}
        elif mean_frac > PROXIMITY_CLOSE_FRAC:
            proximity = {"class": "CLOSE",
                         "mean_disparity_frac_of_eye": round(mean_frac, 3),
                         "reason": "Subject near the rig — strong parallax."}
        else:
            proximity = {"class": "NORMAL_RANGE",
                         "mean_disparity_frac_of_eye": round(mean_frac, 3),
                         "reason": "Subject at comfortable working distance."}

    events.sort(key=lambda e: e["t"])
    # Settle detection: long gaps with no events
    settles = []
    if events:
        prev_t = 0.0
        for e in events:
            if e["t"] - prev_t > 3.0:
                settles.append({"t": round(prev_t, 2), "type": "SETTLE",
                                "magnitude": round(e["t"] - prev_t, 1),
                                "detail": f"{e['t']-prev_t:.1f}s of settled presence"})
            prev_t = e["t"]
    events = sorted(events + settles, key=lambda e: e["t"])

    return {"events": events, "n_events": len(events), "proximity": proximity}


# ---------------------------------------------------------------------------
# Questioner State  (v1.44 — the primary output layer)
# ---------------------------------------------------------------------------

def build_questioner_state(temporal: Dict, spatial: Optional[Dict],
                           metadata: Dict) -> Dict:
    """
    Reinterpret the raw physics signals as a behavioral/spatial read of the
    person asking the question. Descriptive, bounded to evidence in hand.
    This block is what SCO consumes for Query Energy Assessment.
    """
    qs = {"available": False}
    if not temporal.get("success"):
        qs["reason"] = "temporal signal unavailable"
        return qs

    cov = temporal["delta_cov"]
    mean_delta = temporal["mean_delta"]

    # Behavioral energy from temporal signal.
    # mean_delta = how much motion; CoV = how varied that motion is.
    if mean_delta < 2.0:
        motion_level = "STILL"
    elif mean_delta < 6.0:
        motion_level = "MODERATE"
    else:
        motion_level = "ANIMATED"

    if cov < 0.35:
        energy_profile = "STEADY"      # uniform motion — settled delivery
    elif cov < 0.65:
        energy_profile = "DYNAMIC"     # varied motion — engaged, gesturing
    else:
        energy_profile = "BURSTY"      # spikes — emphatic peaks vs stillness

    qs.update({
        "available": True,
        "motion_level": motion_level,            # STILL / MODERATE / ANIMATED
        "energy_profile": energy_profile,        # STEADY / DYNAMIC / BURSTY
        "mean_motion_delta": mean_delta,
        "motion_variation_cov": cov,
        "duration_s": metadata.get("duration_s", 0),
    })

    # Spatial presence from depth fields (stereo captures only).
    if spatial and spatial.get("success"):
        sep = spatial.get("subject_bg_separation_px", 0)
        cons = spatial.get("disparity_consistency_std", 0)
        qs.update({
            "spatial_presence": "DISTINCT" if sep > 3.0 else "EMBEDDED",
            "subject_bg_separation_px": sep,
            "presence_stability": "SETTLED" if cons < 2.0 else "SHIFTING",
            "presence_consistency_std_px": cons,
            "depth_engagement_range_px": spatial.get("disparity_range_px", 0),
        })
    else:
        qs["spatial_presence"] = "UNAVAILABLE (monocular or no stereo signal)"

    # One-line synthesis for SCO.
    qs["sco_summary"] = (
        f"Subject is {motion_level.lower()} with a {energy_profile.lower()} "
        f"energy profile over {qs['duration_s']:.1f}s"
        + (f"; spatially {qs['spatial_presence'].lower()} and "
           f"{qs.get('presence_stability', '').lower()} in the scene."
           if spatial and spatial.get("success") else
           "; spatial presence unavailable (no stereo signal).")
    )
    return qs


# ---------------------------------------------------------------------------
# Room Spatial Reference  (v1.44 — the room is a constant across sessions)
# ---------------------------------------------------------------------------

def build_room_reference(cap: cv2.VideoCapture, spatial: Optional[Dict],
                         seam_x: Optional[int], metadata: Dict) -> Dict:
    """
    Spatial fingerprint of the capture room, stored per session for
    cross-session comparison. The room is constant; POV shifts slightly.
    Measured from the FIRST frame (most likely static, pre-action) plus
    the clip's depth statistics.
    """
    room = {
        "captured": time.strftime("%Y-%m-%d %H:%M:%S"),
        "resolution": f"{metadata.get('width')}x{metadata.get('height')}",
        "seam_x": seam_x,
    }

    # First-frame luminance fingerprint — lighting layout of the room.
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ret, frame = cap.read()
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    if ret:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        h, w = gray.shape
        # 3x3 luminance grid — coarse light map, robust to small POV shifts
        grid = []
        for r in range(3):
            row = []
            for c in range(3):
                cell = gray[r*h//3:(r+1)*h//3, c*w//3:(c+1)*w//3]
                row.append(round(float(cell.mean()), 1))
            grid.append(row)
        room["luminance_grid_3x3"] = grid
        room["scene_mean_luminance"] = round(float(gray.mean()), 1)
        room["scene_luminance_std"] = round(float(gray.std()), 1)
        # Brightest/darkest cells locate windows/lamps vs shadow corners
        flat = np.array(grid).flatten()
        room["brightest_cell"] = int(np.argmax(flat))   # 0-8, row-major
        room["darkest_cell"] = int(np.argmin(flat))

    # Depth fingerprint of the room (stereo only).
    if spatial and spatial.get("success"):
        room["depth_fingerprint"] = {
            "disparity_mean_px": spatial.get("hdisp_mean_px"),
            "disparity_range_px": spatial.get("disparity_range_px"),
            "depth_layers": spatial.get("depth_layers"),
            "note": ("Background depth plane stats. Compare across sessions: "
                     "the room's depth structure should hold within small POV "
                     "shifts; large changes indicate a different room or rig move.")
        }
    else:
        room["depth_fingerprint"] = None

    return room


# ---------------------------------------------------------------------------
# Report markdown
# ---------------------------------------------------------------------------

def build_report_md(video_name: str,
                    metadata: Dict,
                    temporal: Dict,
                    spatial: Optional[Dict],
                    is_stereo: bool,
                    run_time_s: float,
                    seam_x: Optional[int] = None,
                    force_stereo: bool = False,
                    questioner: Optional[Dict] = None,
                    room_ref: Optional[Dict] = None,
                    spacetime: Optional[Dict] = None) -> str:
    L = []
    L += [
        f"# ANA v{VERSION} Detective Briefing",
        "",
        f"**Analyst:** {AUTHOR}  ",
        f"**AI co-analyst:** {AI_COANALYST}  ",
        f"**File:** `{video_name}`  ",
        f"**Analysis date:** {time.strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Run time:** {run_time_s:.1f}s  ",
        f"**Module version:** ana_v145.py v{VERSION}  ",
        "",
        "---",
        "",
        "## SCO Operating Instructions (read first)",
        "",
        "You are a detective, not an authenticator. The video subject is the",
        "user. They may ask in words, gesture, or both. Your job:",
        "",
        "1. Take in everything — video, transcript, this briefing.",
        "2. Watch sequentially, in 3D. No look-ahead.",
        "3. Understand what the user is doing and what they want.",
        "4. **Answer them directly, as if on a FaceTime call.** Add visual",
        "   detail when applicable. Open with \"I see you are...\" only when",
        "   you have something specific to name.",
        "5. If information is missing, ask for it. That is good practice.",
        "6. **Review the Spacetime Event Timeline LAST.** Then check every",
        "   assumption made during frame-by-frame analysis against it. Did",
        "   you miss a gesture? An approach toward the lens? A withdrawal?",
        "",
        "---",
        "",
        "## Questioner State",
        "",
    ]

    if questioner and questioner.get("available"):
        prox = questioner.get("proximity", {})
        L += [
            f"> **{questioner['sco_summary']}**",
            "",
            f"| Dimension | Reading | Raw |",
            f"|-----------|---------|-----|",
            f"| Motion level | {questioner['motion_level']} | mean delta {questioner['mean_motion_delta']:.2f} |",
            f"| Energy profile | {questioner['energy_profile']} | CoV {questioner['motion_variation_cov']:.3f} |",
            f"| Proximity | {prox.get('class', 'UNKNOWN')} | mean disp {prox.get('mean_disparity_frac_of_eye', 'n/a')} of eye width |",
        ]
        if "subject_bg_separation_px" in questioner:
            L += [
                f"| Spatial presence | {questioner['spatial_presence']} | sep {questioner['subject_bg_separation_px']:.1f}px |",
                f"| Presence stability | {questioner['presence_stability']} | std {questioner['presence_consistency_std_px']:.2f}px |",
            ]
        if prox.get("class") in ("TOO_CLOSE_FOR_RIG", "CLOSE"):
            L += ["", f"> **Proximity note:** {prox.get('reason', '')}"]
        L += [
            "",
            "Reading guide: STEADY = settled delivery; DYNAMIC = engaged,",
            "gesturing; BURSTY = emphatic peaks against stillness. DISTINCT =",
            "subject occupies own depth plane; EMBEDDED = merged with scene.",
            "TOO_CLOSE_FOR_RIG = hyperstereo — depth numbers are proximity",
            "readings, not room structure.",
        ]
    else:
        L.append("> Questioner state unavailable (temporal signal failed).")

    # ---- Room reference ----
    L += ["", "---", "", "## Room Spatial Reference", ""]
    if room_ref:
        prox_class = (questioner or {}).get("proximity", {}).get("class", "")
        L += [
            "The room is a constant across sessions; POV shifts slightly.",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Resolution | {room_ref.get('resolution')} |",
            f"| Seam x | {room_ref.get('seam_x')} |",
            f"| Scene mean luminance | {room_ref.get('scene_mean_luminance')} |",
            f"| Scene luminance std | {room_ref.get('scene_luminance_std')} |",
            f"| Brightest cell (0-8) | {room_ref.get('brightest_cell')} |",
            f"| Darkest cell (0-8) | {room_ref.get('darkest_cell')} |",
        ]
        grid = room_ref.get("luminance_grid_3x3")
        if grid:
            L += ["", "Luminance grid (3x3, row-major):", "```"]
            L += [f"  {row}" for row in grid]
            L += ["```"]
        df = room_ref.get("depth_fingerprint")
        if df:
            caveat = (" **CAVEAT: subject proximity dominates this capture — "
                      "depth fingerprint is NOT a reliable room baseline this "
                      "session.**" if prox_class == "TOO_CLOSE_FOR_RIG" else "")
            L += ["",
                  f"Depth fingerprint: mean disparity {df['disparity_mean_px']}px, "
                  f"range {df['disparity_range_px']}px, {df['depth_layers']} layers.{caveat}"]
    else:
        L.append("> Room reference unavailable.")

    # ---- Raw measurements ----
    L += ["", "---", "", "## Raw Measurements (instrument layer — no classification)", ""]
    if temporal.get("success"):
        L += [
            f"**Temporal:** Delta CoV {temporal['delta_cov']:.4f} | "
            f"mean delta {temporal['mean_delta']:.4f} | "
            f"std {temporal['std_delta']:.4f} | {temporal['n_frames']} frames",
        ]
    if spatial and spatial.get("success"):
        L += [
            "",
            f"**Spatial:** H-disparity mean {spatial['hdisp_mean_px']}px, "
            f"spread {spatial['hdisp_spread_px']}px, range {spatial['disparity_range_px']}px | "
            f"{spatial['depth_layers']} depth layers | "
            f"subject/BG sep {spatial['subject_bg_separation_px']}px | "
            f"{spatial['n_matches']} matches over {spatial['n_keyframes']} keyframes | "
            f"seam x={spatial['seam_x']} "
            f"(eyes L={spatial['eye_width_left_px']}px / R={spatial['eye_width_right_px']}px)",
        ]
    elif is_stereo:
        L.append(f"**Spatial:** unavailable — {(spatial or {}).get('reason', 'unknown')}")
    else:
        L.append("**Spatial:** n/a (monocular)")

    # ---- Spacetime timeline — LAST, by protocol ----
    L += [
        "", "---", "",
        "## Spacetime Event Timeline (review LAST — assumption check)",
        "",
        "Sequential 3D record. After frame-by-frame analysis, walk this",
        "timeline and verify nothing was missed: gestures toward the lens,",
        "withdrawals, motion without depth change, depth change without motion.",
        "",
    ]
    if spacetime and spacetime.get("events"):
        L += ["| t (s) | Event | Magnitude | Detail |",
              "|-------|-------|-----------|--------|"]
        for e in spacetime["events"]:
            L.append(f"| {e['t']:.2f} | {e['type']} | {e['magnitude']} | {e['detail']} |")
        L += ["",
              "APPROACH_TOWARD_CAMERA = nearest-object disparity rising — a hand,",
              "an object, or the subject moving toward the lens. This is a",
              "directed act at the observer. Do not let it pass unaddressed."]
    else:
        L.append("> No discrete events detected — continuous settled presence.")

    L += [
        "",
        "---",
        "",
        "## Next Step: Run SCO",
        "",
        "```",
        f"Attach: {video_name}",
        f"        {Path(video_name).stem}_ana_v1.48.json",
        f"        {Path(video_name).stem}_ana_v1.48_report.md",
        f"        (optional) {Path(video_name).stem}.srt",
        "",
        "Ask: 'Run SCO on this data'",
        "```",
        "",
        "---",
        "",
        f"*The instrument states what it sees. The analyst ({AUTHOR}) has the final word.*  ",
        f"*ANA+SCO patent: US Provisional #64/056,727 — seeitwith.org*",
    ]
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def analyze(video_path: str,
            output_dir: Optional[str] = None,
            quiet: bool = False,
            seam_x: Optional[int] = None,
            force_stereo: bool = False) -> Dict:
    """
    Full analysis pipeline. Returns result dict.

    seam_x       : beam-splitter divider column supplied by DCI seam detector.
                   Passed through to compute_hdisp_spread and render_anaglyph.
                   Off-center values preserved; defaults to frame-center if None.
    force_stereo : bypass the aspect-ratio gate and run the spatial signal
                   regardless of resolution. Intended for standard 1920x1080
                   SBS captures where aspect ratio is 1.778 (fails > 2.5 gate).
    """
    t_start = time.time()

    video_path = str(Path(video_path).resolve())
    if not os.path.exists(video_path):
        return {"success": False, "error": f"File not found: {video_path}"}

    stem = Path(video_path).stem
    out_dir = Path(output_dir) if output_dir else Path(video_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    if not quiet:
        print(f"\n{'='*60}")
        print(f"ANA v{VERSION} — {stem}")
        print(f"{'='*60}")

    # Open video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"success": False, "error": "Cannot open video"}

    fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Stereo determination: DCI override takes priority over aspect-ratio gate
    stereo = force_stereo or is_stereo_sbs(cap)
    stereo_source = ("dci_force_stereo" if force_stereo
                     else ("aspect_ratio" if is_stereo_sbs(cap) else "monocular"))

    metadata = {
        "path": video_path,
        "duration_s": round(total / fps, 3),
        "fps": round(fps, 3),
        "width": w,
        "height": h,
        "frame_count": total,
        "is_stereo": stereo,
        "stereo_source": stereo_source,
        "seam_x": seam_x,
    }

    if not quiet:
        stereo_label = "STEREO SBS" if stereo else "monocular"
        source_label = f" [forced by DCI, seam x={seam_x}]" if force_stereo else ""
        print(f"  {w}x{h} @ {fps:.1f}fps  |  {total/fps:.1f}s  |  "
              f"{stereo_label}{source_label}")

    # Signal 1 — Delta CoV
    if not quiet:
        print("  [1/2] Delta CoV (temporal)...")
    diffs, _, _ = compute_frame_diffs(cap, DELTA_COV_MAX_FRAMES)
    temporal = compute_delta_cov(diffs)

    if not quiet:
        if temporal.get("success"):
            print(f"        CoV={temporal['delta_cov']:.4f}")
        else:
            print(f"        UNAVAILABLE: {temporal.get('reason')}")

    # Signal 2 — H-disparity (stereo only)
    spatial = None
    anaglyph_path = None
    if stereo:
        if not quiet:
            print("  [2/2] H-disparity spread (spatial)...")
            if seam_x is not None:
                print(f"        seam x={seam_x} (DCI-supplied)")
        spatial = compute_hdisp_spread(cap, seam_x=seam_x)

        if not quiet:
            if spatial.get("success"):
                print(f"        spread={spatial['hdisp_spread_px']:.2f}px  "
                      f"mean={spatial['hdisp_mean_px']:.1f}px")
            else:
                print(f"        UNAVAILABLE: {spatial.get('reason')}")

        # Render anaglyph
        anaglyph_out = str(out_dir / f"{stem}_ana_v1.48_anaglyph.mp4")
        if not quiet:
            print("  Rendering anaglyph...")
        if render_anaglyph(video_path, anaglyph_out, seam_x=seam_x):
            anaglyph_path = anaglyph_out
            if not quiet:
                print(f"  Anaglyph: {Path(anaglyph_out).name}")
    else:
        if not quiet:
            print("  [2/2] Spatial signal: N/A (monocular)")

    # Questioner State + Room Reference (needs cap still open)
    questioner = build_questioner_state(temporal, spatial, metadata)
    room_ref = build_room_reference(cap, spatial, seam_x, metadata)

    cap.release()

    # Spacetime event timeline (v1.45 — sequential 3D record)
    spacetime = build_spacetime_events(diffs, fps, total, spatial)
    # Proximity feeds the questioner read
    questioner["proximity"] = spacetime["proximity"]

    if not quiet:
        if questioner.get("available"):
            print(f"  Questioner: {questioner['sco_summary']}")
        print(f"  Proximity:  {spacetime['proximity']['class']}")
        print(f"  Spacetime:  {spacetime['n_events']} events")
        for e in spacetime["events"][:8]:
            print(f"    t={e['t']:>6.2f}s  {e['type']:<24} {e['detail']}")

    # Orient PNG
    orient_path = str(out_dir / f"{stem}_ana_v1.48_orient.png")
    profile = (questioner.get("energy_profile", "n/a")
               if questioner.get("available") else "n/a")
    save_orient_png(diffs, fps, total, orient_path,
                    Path(video_path).name,
                    temporal.get("delta_cov", 0),
                    f"{profile} / {spacetime['proximity']['class']}")

    # Build result
    run_time = round(time.time() - t_start, 2)
    result = {
        "success": True,
        "version": VERSION,
        "revision_date": REVISION_DATE,
        "author": AUTHOR,
        "ai_coanalyst": AI_COANALYST,
        "metadata": metadata,
        "questioner_state": questioner,
        "spacetime_events": spacetime,
        "room_spatial_reference": room_ref,
        "temporal_signal": temporal,
        "spatial_signal": spatial,
        "run_time_s": run_time,
        "outputs": {
            "json": str(out_dir / f"{stem}_ana_v1.48.json"),
            "report_md": str(out_dir / f"{stem}_ana_v1.48_report.md"),
            "orient_png": orient_path,
            "anaglyph_mp4": anaglyph_path
        }
    }

    # Write JSON
    json_out = out_dir / f"{stem}_ana_v1.48.json"
    with open(json_out, 'w') as f:
        json.dump(result, f, indent=2)

    # Write report MD
    md_out = out_dir / f"{stem}_ana_v1.48_report.md"
    report = build_report_md(
        Path(video_path).name, metadata,
        temporal, spatial,
        stereo, run_time,
        seam_x=seam_x, force_stereo=force_stereo,
        questioner=questioner, room_ref=room_ref,
        spacetime=spacetime
    )
    with open(md_out, 'w') as f:
        f.write(report)

    if not quiet:
        print(f"\n  Run time: {run_time}s")
        print(f"  JSON:     {json_out.name}")
        print(f"  Report:   {md_out.name}")
        print(f"  Orient:   {Path(orient_path).name}")
        if anaglyph_path:
            print(f"  Anaglyph: {Path(anaglyph_path).name}")
        print(f"{'='*60}\n")

    return result


def main():
    parser = argparse.ArgumentParser(
        description=f"ANA v{VERSION} — Lean Two-Signal Forensic Analyzer"
    )
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("--output-dir",
                        help="Output directory (default: video's folder)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress console output")
    parser.add_argument("--seam-x", type=int, default=None,
                        help="Beam-splitter seam column (supplied by DCI). "
                             "Passed to H-disparity and anaglyph render. "
                             "Preserves off-center rigs. Defaults to frame-center.")
    parser.add_argument("--force-stereo", action="store_true",
                        help="Bypass aspect-ratio gate and treat video as stereo SBS. "
                             "Use with --seam-x for standard 1920x1080 beam-splitter "
                             "captures where aspect ratio is 1.778 (fails >2.5 gate).")
    args = parser.parse_args()

    result = analyze(
        video_path=args.video,
        output_dir=args.output_dir,
        quiet=args.quiet,
        seam_x=args.seam_x,
        force_stereo=args.force_stereo,
    )

    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
