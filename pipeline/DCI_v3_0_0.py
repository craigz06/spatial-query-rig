#!/usr/bin/env python3
"""
Title: DCI - Direct Camera Interface
Frame Grabber, Audio-Muxed Recorder, Auto-Transcriber, Claude Object Tracker

Script Revision: v3.0.0
Date: July 27, 2026
Author: Craig C. Cline / seeitwith.org
AI co-author: Claude (Anthropic)
Patent: US Provisional #64/056,727

Revision Notes (v2.0.0 -> v3.0.0):
Version bump only, no functional changes. Numbered v3.0.0 instead of
continuing the v2.x line to avoid collision with an earlier, unrelated
local v2.11 series that predates this codebase's v2.0.0 clean-break
reset — that old v2.x numbering was never part of this repo's history,
but reusing it here risked ambiguity against local archives. All
content below carries forward unchanged from v2.0.0.

Revision Notes (v1.14.0 -> v2.0.0):
CLEAN BREAK. Dropped stereo seam detection, ANA physics invocation, the
SCO stub/upload-to-Claude-online workflow, and diagnostic cleanup — none
of that is used anymore.

New purpose: track known objects in the room and build a running story
of what moved, where, and when.

Kept from v1.14.0: camera capture, record/pause/stop workflow, audio
recording, whisper transcription to SRT.

New in v2.0.0:
- KNOWN_OBJECTS file (JSON) holds the current position of each tracked
  object, keyed by draw.io cell ID.
- On STOP & SAVE, DCI extracts three still frames from the saved clip
  (beginning / middle / end — SAMPLE_FRACTIONS below controls this and
  can be widened to more frames later without any other code changes).
- DCI calls the Claude API once, with the three frames, the known-object
  list, and the whisper transcript, and asks for two things only:
    1. objects_moved -- structured from/to positions (falsifiable claim)
    2. claude_narrative -- plain description of what appeared to happen,
       STRICTLY NO SPECULATION (see SYSTEM_PROMPT below). Speculation /
       surprise scoring is an intentionally deferred later phase.
- Result is appended to RUNNING_STORY_PATH (append-only event log) and
  used to update KNOWN_OBJECTS_PATH (current-state file).

Dependencies:
  pip3 install opencv-python numpy sounddevice imageio-ffmpeg openai-whisper anthropic
"""

# ----- CONFIGURATION -----
import os as _os
_DCI_DIR = _os.path.dirname(_os.path.abspath(__file__))

KNOWN_OBJECTS_PATH = _os.path.join(_DCI_DIR, "known_objects.json")
RUNNING_STORY_PATH = _os.path.join(_DCI_DIR, "running_story.json")

CLAUDE_MODEL = "claude-sonnet-5"
CLAUDE_MAX_TOKENS = 1024
CLAUDE_API_KEY_ENV = "ANTHROPIC_API_KEY"  # standard SDK env var

# Fractions of total frame count to sample as stills: beginning / middle / end.
# To sample more frames later, just add fractions here — nothing else changes.
SAMPLE_FRACTIONS = [0.0, 0.5, 1.0]
SAMPLE_LABELS = ["BEGINNING", "MIDDLE", "END"]

# ----- INPUT DEVICE SELECTION -----
AUDIO_DEVICE_HINT = "USB"
AUDIO_DEVICE_INDEX = None
CAMERA_INDEX_OVERRIDE = None
CAMERA_SCAN_RANGE = [0, 1, 2, 3]

import cv2
import time
import os
import threading
import queue
import wave
import json
import base64

try:
    import sounddevice as sd
    import numpy as np
    AUDIO_AVAILABLE = True
except (ImportError, OSError):
    try:
        import numpy as np
    except ImportError:
        pass
    AUDIO_AVAILABLE = False

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


# ===========================================================================
# CAMERA / AUDIO DEVICE SELECTION (unchanged from v1.14.0)
# ===========================================================================
def find_active_sensor():
    """Find a working camera. CAMERA_INDEX_OVERRIDE pins a specific index;
    otherwise scan CAMERA_SCAN_RANGE and take the first that delivers frames."""
    indices = ([CAMERA_INDEX_OVERRIDE] if CAMERA_INDEX_OVERRIDE is not None
               else CAMERA_SCAN_RANGE)
    for index in indices:
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                return cap, index
            cap.release()
        else:
            cap.release()
    return None, None


def select_audio_device():
    """Priority: AUDIO_DEVICE_INDEX (hard pin) > name matching AUDIO_DEVICE_HINT
    > system default. Returns (device_index_or_None, label)."""
    if not AUDIO_AVAILABLE:
        return None, "audio unavailable"
    try:
        devices = sd.query_devices()
    except Exception as e:
        print(f"[AUDIO] device query failed ({e}); using system default.")
        return None, "system default"

    if AUDIO_DEVICE_INDEX is not None:
        try:
            d = devices[AUDIO_DEVICE_INDEX]
            if d.get("max_input_channels", 0) > 0:
                return AUDIO_DEVICE_INDEX, f"pinned: {d['name']}"
            print(f"[AUDIO] pinned index {AUDIO_DEVICE_INDEX} has no inputs; "
                  f"falling back to hint/default.")
        except Exception:
            print(f"[AUDIO] pinned index {AUDIO_DEVICE_INDEX} invalid; "
                  f"falling back to hint/default.")

    hint = (AUDIO_DEVICE_HINT or "").lower()
    if hint:
        for i, d in enumerate(devices):
            if (d.get("max_input_channels", 0) > 0
                    and hint in d.get("name", "").lower()):
                return i, f"hint '{AUDIO_DEVICE_HINT}': {d['name']}"

    return None, "system default"


def audio_recorder_worker(filename, stop_event, shared_state, device=None):
    sample_rate = 44100
    channels = 1
    audio_queue = queue.Queue()

    def callback(indata, frames, time_info, status):
        audio_queue.put(indata.copy())

    try:
        with sd.InputStream(samplerate=sample_rate, channels=channels,
                             dtype='int16', callback=callback, device=device):
            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                while not stop_event.is_set() or not audio_queue.empty():
                    try:
                        data = audio_queue.get(block=False)
                        if not shared_state['paused']:
                            wf.writeframes(data.tobytes())
                    except queue.Empty:
                        time.sleep(0.01)
    except Exception as e:
        print(f"\n[AUDIO ERROR] {e}")


def merge_audio_video(video_path, audio_path, output_path):
    """Mux using imageio-ffmpeg bundled binary — no system ffmpeg required."""
    try:
        import imageio_ffmpeg
        import subprocess
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe, '-y',
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-shortest',
            output_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception as e:
        print(f"[MERGE ERROR] {e}")
        return False


def format_srt_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe_to_srt(audio_path, srt_path, model_name='base'):
    """Run whisper on audio file, save SRT with timestamps."""
    if not WHISPER_AVAILABLE:
        print("[TRANSCRIBE SKIP] whisper not installed (pip3 install openai-whisper)")
        return False
    try:
        print(f"  Loading whisper model '{model_name}'...")
        model = whisper.load_model(model_name)
        print(f"  Transcribing {os.path.basename(audio_path)}...")
        result = model.transcribe(audio_path, verbose=False)
        with open(srt_path, 'w') as f:
            for i, seg in enumerate(result['segments'], 1):
                f.write(f"{i}\n")
                f.write(f"{format_srt_timestamp(seg['start'])} --> {format_srt_timestamp(seg['end'])}\n")
                f.write(f"{seg['text'].strip()}\n\n")
        return True
    except Exception as e:
        print(f"[TRANSCRIBE ERROR] {e}")
        return False


def read_text_file(path):
    """Read a text file if it exists; return '' on any failure. Never raises."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


# ===========================================================================
# KNOWN OBJECTS (current-state file)
# ===========================================================================
def load_known_objects():
    """
    Load the current object list. Creates a starter file with one known
    object (the drafting stool) if none exists yet. Never raises.
    Shape:
      {"objects": [{"object_id": "...", "name": "...", "class": "...",
                    "position": {"x": .., "y": .., "z": ..}}, ...]}
    """
    if not os.path.exists(KNOWN_OBJECTS_PATH):
        starter = {
            "objects": [
                {
                    "object_id": "F2xKYfU6apGsXWulq0Ia-3",
                    "name": "drafting_stool",
                    "class": "movable",
                    "position": {"x": 84.0, "y": 51.0, "z": 0}
                }
            ]
        }
        try:
            with open(KNOWN_OBJECTS_PATH, "w", encoding="utf-8") as f:
                json.dump(starter, f, indent=2)
            print(f">> Created starter object list: {KNOWN_OBJECTS_PATH}")
        except Exception as e:
            print(f"[OBJECTS WARN] Could not create starter file: {e}")
        return starter

    try:
        with open(KNOWN_OBJECTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[OBJECTS WARN] Could not read {KNOWN_OBJECTS_PATH}: {e}")
        return {"objects": []}


def save_known_objects(data):
    """Write the object list back out. Never raises."""
    try:
        with open(KNOWN_OBJECTS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[OBJECTS WARN] Could not save {KNOWN_OBJECTS_PATH}: {e}")
        return False


def apply_moves(known_objects, objects_moved):
    """Update current positions in-place for objects Claude reported as moved.
    Unmatched object_ids are noted and skipped, never crash the pipeline."""
    by_id = {o["object_id"]: o for o in known_objects.get("objects", [])}
    for move in objects_moved:
        oid = move.get("object_id")
        if oid in by_id:
            by_id[oid]["position"] = move.get("to", by_id[oid]["position"])
        else:
            print(f"[OBJECTS NOTE] Claude reported movement for unknown "
                  f"object_id '{oid}' — not in known_objects.json, skipping.")
    return known_objects


# ===========================================================================
# FRAME EXTRACTION (beginning / middle / end stills)
# ===========================================================================
def extract_sample_frames(video_path, fractions=SAMPLE_FRACTIONS, labels=SAMPLE_LABELS):
    """
    Pull still frames from a saved clip at the given fractions of its length
    (0.0 = first frame, 1.0 = last frame). Returns a list of
    (label, base64_jpeg_str) tuples. Never raises — returns [] on failure.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[FRAMES ERROR] Could not open {video_path}")
        return []

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    results = []
    for frac, label in zip(fractions, labels):
        idx = min(total - 1, max(0, int(round(frac * (total - 1)))))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            print(f"[FRAMES WARN] Could not read frame at {label} (idx {idx})")
            continue
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            print(f"[FRAMES WARN] Could not encode frame at {label}")
            continue
        b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
        results.append((label, b64))

    cap.release()
    return results


# ===========================================================================
# CLAUDE OBJECT-COMPARISON CALL
# ===========================================================================
SYSTEM_PROMPT = """You are reviewing still frames from a fixed-camera clip \
of a room, taken at the beginning, middle, and end of a short recording.

You are given a list of known objects in the room, each with its position \
before this recording (in real-world inches, room coordinate system: \
origin at the NW interior corner, +x east, +y south).

Your job has two strict parts:

1. objects_moved — for each object from the known list that you can see \
has changed position between the frames, report its object_id and your \
best estimate of its new position in the same coordinate system. If you \
cannot confidently estimate real-world coordinates, use your best pixel- \
relative estimate and note low confidence. Only include objects you \
actually observed moving. An empty list is a valid and expected answer \
if nothing moved.

2. claude_narrative — a plain, strictly factual description of what \
appears to have happened, based only on what is visible in the frames \
and audible/readable in the transcript. Do NOT speculate about intent, \
cause, or anything not directly observable. Do not guess why something \
moved. Describe only what moved, in what order if determinable, and any \
directly relevant transcript content.

Respond with ONLY a JSON object, no other text, in this exact shape:
{
  "objects_moved": [
    {"object_id": "...", "name": "...", "to": {"x": 0.0, "y": 0.0}, "confidence": "HIGH|MEDIUM|LOW"}
  ],
  "claude_narrative": "..."
}
"""


def call_claude_object_comparison(frames, known_objects, transcript_text):
    """
    Send the sampled frames + known object list + transcript to Claude and
    return the parsed dict {"objects_moved": [...], "claude_narrative": "..."}.
    Returns None on any failure (missing key, no SDK, API error, bad JSON) —
    never raises. Caller must handle None gracefully.
    """
    if not ANTHROPIC_AVAILABLE:
        print("[CLAUDE SKIP] anthropic package not installed (pip3 install anthropic)")
        return None
    if not os.environ.get(CLAUDE_API_KEY_ENV):
        print(f"[CLAUDE SKIP] {CLAUDE_API_KEY_ENV} not set in environment.")
        return None
    if not frames:
        print("[CLAUDE SKIP] No frames extracted; nothing to send.")
        return None

    objects_text = json.dumps(known_objects, indent=2)
    transcript_block = transcript_text.strip() or "(no speech detected)"

    content = [
        {"type": "text", "text": (
            f"KNOWN OBJECTS (positions before this recording):\n{objects_text}\n\n"
            f"TRANSCRIPT of this recording:\n{transcript_block}\n\n"
            f"Below are {len(frames)} still frames sampled from the clip, "
            f"in order."
        )}
    ]
    for label, b64 in frames:
        content.append({"type": "text", "text": f"Frame: {label}"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}
        })
    content.append({"type": "text", "text": "Respond with the JSON object described in your instructions, and nothing else."})

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
    except Exception as e:
        print(f"[CLAUDE ERROR] API call failed: {e}")
        return None

    # Strip markdown code fences if Claude wraps the JSON despite instructions.
    cleaned = raw_text
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
        if "objects_moved" not in parsed or "claude_narrative" not in parsed:
            print("[CLAUDE WARN] Response missing expected keys.")
            return None
        return parsed
    except Exception as e:
        print(f"[CLAUDE ERROR] Could not parse JSON response: {e}")
        print(f"  Raw response was: {raw_text[:500]}")
        return None


# ===========================================================================
# RUNNING STORY (append-only event log)
# ===========================================================================
def append_running_story(video_basename, objects_moved, claude_narrative):
    """
    Append one event to RUNNING_STORY_PATH. Never raises.
    Returns the event dict written, or None on failure.
    """
    entry = {
        "event_id": f"evt_{time.strftime('%Y%m%d_%H%M%S')}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "capture": video_basename,
        "objects_moved": objects_moved,
        "claude_narrative": claude_narrative,
        "narrative_type": "observation",
    }

    story = []
    if os.path.exists(RUNNING_STORY_PATH):
        try:
            with open(RUNNING_STORY_PATH, "r", encoding="utf-8") as f:
                story = json.load(f)
                if not isinstance(story, list):
                    story = []
        except Exception as e:
            print(f"[STORY WARN] Could not read existing log ({e}); starting fresh.")
            story = []

    story.append(entry)
    try:
        with open(RUNNING_STORY_PATH, "w", encoding="utf-8") as f:
            json.dump(story, f, indent=2)
        print(f">> Running story updated: {RUNNING_STORY_PATH} ({len(story)} events)")
    except Exception as e:
        print(f"[STORY WARN] Could not write {RUNNING_STORY_PATH}: {e}")
        return None

    return entry


# ===========================================================================
# AUDIO CUES
# ===========================================================================
def beep(times=1, freq=880, dur_ms=120, gap_ms=90):
    """Single beep = record start, double = stop & save. Never raises."""
    try:
        if AUDIO_AVAILABLE:
            fs = 44100
            t = np.linspace(0, dur_ms / 1000.0, int(fs * dur_ms / 1000.0), False)
            tone = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
            for i in range(times):
                sd.play(tone, fs, blocking=True)
                if i < times - 1:
                    time.sleep(gap_ms / 1000.0)
            return
    except Exception:
        pass
    for i in range(times):
        print("\a", end="", flush=True)
        if i < times - 1:
            time.sleep(gap_ms / 1000.0)


# ===========================================================================
# DASHBOARD
# ===========================================================================
def draw_unified_dashboard(frame, status_text, status_color, timestamp,
                            is_recording, display_filename, active_index):
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 115), (0, 0, 0), -1)
    cv2.putText(frame, "[R] START/RESUME REC | [P] PAUSE REC | [S] STOP & SAVE",
                (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
    audio_tag = "AUDIO" if AUDIO_AVAILABLE else "audio-off"
    whisper_tag = "WHISPER" if WHISPER_AVAILABLE else "whisper-off"
    claude_tag = "CLAUDE" if ANTHROPIC_AVAILABLE else "claude-off"
    cv2.putText(frame, f"[SPACE] SNAPSHOT | [Q] QUIT | {audio_tag} {whisper_tag} {claude_tag}",
                (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(frame, f"{status_text} | Bus: {active_index} | {timestamp}",
                (20, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.65, status_color, 2, cv2.LINE_AA)


# ===========================================================================
# MAIN PIPELINE
# ===========================================================================
def run_camera_pipeline():
    os.system('clear')
    frame_width = 1920
    frame_height = 1080
    encoder_fps = 30.0
    cache_video_filename = "dci_working_cache.mp4"
    cache_audio_filename = "dci_working_cache.wav"
    window_name = "Grounded Observer - Live Stream Monitor"

    print("=================================================================")
    print("DCI v2.0.0 — Direct Camera Interface")
    print("  record + transcribe + Claude object tracking")
    print("=================================================================")

    if not AUDIO_AVAILABLE:
        print("[WARNING] Run: pip3 install sounddevice")
    if not WHISPER_AVAILABLE:
        print("[INFO] Whisper not installed. Auto-transcription disabled.")
        print("       pip3 install openai-whisper")
    if not ANTHROPIC_AVAILABLE:
        print("[INFO] anthropic package not installed. Object tracking disabled.")
        print("       pip3 install anthropic")
    elif not os.environ.get(CLAUDE_API_KEY_ENV):
        print(f"[INFO] {CLAUDE_API_KEY_ENV} not set. Object tracking will be skipped.")
    else:
        print(f"[OK] Claude object tracking ready (model: {CLAUDE_MODEL})")

    known_objects = load_known_objects()
    print(f"[OK] Tracking {len(known_objects.get('objects', []))} known object(s).")

    audio_device, audio_label = select_audio_device()
    if AUDIO_AVAILABLE:
        print(f"[AUDIO] Input device: {audio_label}")

    print(f"Scanning for camera (indices "
          f"{CAMERA_SCAN_RANGE if CAMERA_INDEX_OVERRIDE is None else [CAMERA_INDEX_OVERRIDE]})...")
    cap, active_index = find_active_sensor()
    if cap is None:
        print("[CRITICAL] No camera found. Check USB and macOS Privacy > Camera.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    video_writer = None
    audio_thread = None
    audio_stop_event = threading.Event()
    audio_shared_state = {'paused': False}
    is_recording = False
    is_paused = False
    frame_count = 0

    print(f"Sensor locked: Index {active_index} at {actual_width}x{actual_height}")
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[ERROR] Frame drop.")
                break
            frame_count += 1
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

            if is_recording and not is_paused and video_writer is not None:
                video_writer.write(frame)

            display_frame = frame.copy()
            if not is_recording:
                status_text = "IDLE"
                status_color = (150, 150, 150)
            elif is_paused:
                status_text = "PAUSED"
                status_color = (0, 255, 255)
            else:
                indicator = " *" if (frame_count // 15) % 2 == 0 else ""
                status_text = f"RECORDING{indicator}"
                status_color = (0, 0, 255)

            draw_unified_dashboard(display_frame, status_text, status_color,
                                    timestamp, is_recording, "DCI_CACHE", active_index)
            cv2.imshow(window_name, display_frame)
            key = cv2.waitKey(1) & 0xFF

            if key == ord('r') or key == ord('R'):
                if not is_recording:
                    fourcc = cv2.VideoWriter_fourcc(*'avc1')
                    video_writer = cv2.VideoWriter(cache_video_filename, fourcc, encoder_fps,
                                                    (actual_width, actual_height))
                    if not video_writer.isOpened():
                        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                        video_writer = cv2.VideoWriter(cache_video_filename, fourcc, encoder_fps,
                                                        (actual_width, actual_height))
                    if AUDIO_AVAILABLE:
                        audio_stop_event.clear()
                        audio_shared_state['paused'] = False
                        audio_thread = threading.Thread(
                            target=audio_recorder_worker,
                            args=(cache_audio_filename, audio_stop_event,
                                  audio_shared_state, audio_device))
                        audio_thread.start()
                    is_recording = True
                    is_paused = False
                    print(f"[{timestamp}] Recording started.")
                    beep(times=1)
                elif is_paused:
                    is_paused = False
                    audio_shared_state['paused'] = False
                    print(f"[{timestamp}] Resumed.")

            elif key == ord('p') or key == ord('P'):
                if is_recording and not is_paused:
                    is_paused = True
                    audio_shared_state['paused'] = True
                    print(f"[{timestamp}] Paused.")

            elif key == ord('s') or key == ord('S'):
                if is_recording:
                    beep(times=2)
                    if video_writer:
                        video_writer.release()
                        video_writer = None
                    if AUDIO_AVAILABLE and audio_thread:
                        audio_stop_event.set()
                        audio_thread.join()
                        audio_thread = None
                    cv2.destroyAllWindows()
                    for _ in range(15):
                        cv2.waitKey(1)

                    os.system('clear')
                    print("=" * 50)
                    user_given_name = input("Filename (ENTER for default): ").strip() or "dci_sequence"
                    user_given_name = user_given_name.replace(" ", "_")
                    time_suffix = time.strftime("%Y%m%d_%H%M%S")
                    final_video_name = f"{user_given_name}_{time_suffix}.mp4"
                    final_audio_name = f"{user_given_name}_{time_suffix}.wav"
                    final_srt_name = f"{user_given_name}_{time_suffix}.srt"

                    if os.path.exists(cache_video_filename):
                        if AUDIO_AVAILABLE and os.path.exists(cache_audio_filename):
                            import shutil
                            shutil.copy(cache_audio_filename, final_audio_name)
                            print(f">> Audio saved: {final_audio_name}")

                            print("Merging audio + video (imageio-ffmpeg)...")
                            if merge_audio_video(cache_video_filename, cache_audio_filename, final_video_name):
                                print(f">> Video+audio merged: {final_video_name}")
                            else:
                                os.rename(cache_video_filename, final_video_name)
                                print(f">> Merge failed. Video saved silent: {final_video_name}")

                            if WHISPER_AVAILABLE:
                                print("Transcribing...")
                                if transcribe_to_srt(final_audio_name, final_srt_name):
                                    print(f">> Transcript saved: {final_srt_name}")
                                else:
                                    print(">> Transcription failed.")
                            else:
                                print(">> Skipping transcript (whisper not installed)")

                            for f in [cache_video_filename, cache_audio_filename]:
                                try:
                                    os.remove(f)
                                except Exception:
                                    pass
                        else:
                            os.rename(cache_video_filename, final_video_name)
                            print(f">> Video only: {final_video_name}")

                        # ---- Extract sample frames ----
                        print()
                        print("Extracting sample frames (beginning / middle / end)...")
                        frames = extract_sample_frames(final_video_name)
                        print(f">> {len(frames)} frame(s) extracted.")

                        # ---- Claude object comparison ----
                        transcript_text = read_text_file(final_srt_name)
                        print("Asking Claude what moved...")
                        result = call_claude_object_comparison(frames, known_objects, transcript_text)

                        if result is not None:
                            objects_moved = result.get("objects_moved", [])
                            narrative = result.get("claude_narrative", "")
                            print(f">> Objects moved: {len(objects_moved)}")
                            if narrative:
                                print(f">> Narrative: {narrative}")

                            append_running_story(final_video_name, objects_moved, narrative)
                            known_objects = apply_moves(known_objects, objects_moved)
                            save_known_objects(known_objects)
                        else:
                            print(">> No object-comparison result (see messages above).")

                    print()
                    print("=" * 60)
                    print(f"COMPLETE BUNDLE: {user_given_name}_{time_suffix}")
                    print("=" * 60)
                    print(f"  DCI media : .mp4 / .wav / .srt")
                    print(f"  Story log : {RUNNING_STORY_PATH}")
                    print(f"  Objects   : {KNOWN_OBJECTS_PATH}")
                    print()

                    is_recording = False
                    is_paused = False
                    print("Resuming live monitor...")
                    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

            elif key == ord(' '):
                snap_time = time.strftime("%Y%m%d_%H%M%S")
                snap_filename = f"dci_frame_{snap_time}.png"
                cv2.imwrite(snap_filename, frame, [int(cv2.IMWRITE_PNG_COMPRESSION), 0])
                print(f"Snapshot: {snap_filename}")

            elif key == ord('q') or key == ord('Q'):
                break

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        if video_writer:
            video_writer.release()
        if AUDIO_AVAILABLE and audio_thread:
            audio_stop_event.set()
            audio_thread.join()
        for f in [cache_video_filename, cache_audio_filename]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        cap.release()
        cv2.destroyAllWindows()
        for _ in range(5):
            cv2.waitKey(1)
        print("Pipeline closed.")


if __name__ == "__main__":
    run_camera_pipeline()
