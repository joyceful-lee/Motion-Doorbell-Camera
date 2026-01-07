from email.message import EmailMessage
from picamera2 import Picamera2
from datetime import datetime
from collections import deque
import cv2
import time
import os
import smtplib
import config
import requests
import threading
import subprocess

# ----------------------------
# GLOBALS
# ----------------------------
camera_lock = threading.Lock()
last_frame_time = time.time()
STOP_PROGRAM = False
FPS = 20
PRE_ROLL_SECONDS = 5
POST_ROLL_SECONDS = 3

ROI_X = 160
ROI_Y = 120
ROI_W = 320
ROI_H = 240

latest_frame = None
frame_buffer = deque(maxlen=FPS * PRE_ROLL_SECONDS)

# Day/night detection
LAST_LIGHT_STATE = "day"

# Background subtractor for motion
bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=40, detectShadows=False)

# Ensure save path exists
os.makedirs(config.SAVE_PATH, exist_ok=True)

# ----------------------------
# CAMERA SETUP
# ----------------------------
picam = Picamera2()
camera_config = picam.create_video_configuration(
    main={"size": (640, 480), "format": "RGB888"}
)
picam.configure(camera_config)
picam.start()
time.sleep(0.5)
print("Camera initialized")

def camera_loop():
    """ Continuously capture frames and update latest_frame """
    global latest_frame, last_frame_time
    while not STOP_PROGRAM:
        try:
            frame = picam.capture_array()
            last_frame_time = time.time()
            latest_frame = frame.copy()
            frame_buffer.append(latest_frame.copy())
        except Exception as e:
            print("Camera loop error:", e)
            time.sleep(1)

# ----------------------------
# DAY/NIGHT FUNCTIONS
# ----------------------------
def is_night(frame):
    """ Return True if ROI indicates night """
    global LAST_LIGHT_STATE
    roi = frame[ROI_Y:ROI_Y+ROI_H, ROI_X:ROI_X+ROI_W]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    mean = gray.mean()

    if LAST_LIGHT_STATE == "day" and mean < 55:
        LAST_LIGHT_STATE = "night"
    elif LAST_LIGHT_STATE == "night" and mean > 70:
        LAST_LIGHT_STATE = "day"
    return LAST_LIGHT_STATE == "night"

def apply_day_settings():
    with camera_lock:
        picam.set_controls({
            "AeEnable": True,
            "AwbEnable": True,
            "Brightness": 0.0,
            "Contrast": 1.0
        })

def apply_night_settings():
    with camera_lock:
        picam.set_controls({
            "AeEnable": True,
            "AwbEnable": True,
            "Brightness": 0.2,
            "Contrast": 1.3,
            "NoiseReductionMode": 2
        })

# ----------------------------
# UTILITY FUNCTIONS
# ----------------------------

# saves clips in year/month/day/clip.avi
def get_date_folder():
    now = datetime.now()
    return f"{now.year}/{now.month:02d}/{now.day:02d}"

# creates file with name yearmonthday-time
def filename_creator():
    now = datetime.now()
    return f"{now.year}{now.month:02d}{now.day:02d}-{int(time.time())}"

# ----------------------------
# ALERTS
# ----------------------------
def send_discord_alert(image_path, drive_link=None):
    if not config.DISCORD_ENABLED:
        return
    try:
        if drive_link:  # send clip link
            requests.post(config.DISCORD_WEBHOOK_URL, data={"content": f"Clip: {drive_link}"}, timeout=5)
        else:  # send initial message with photo
            with open(image_path, "rb") as f:
                requests.post(config.DISCORD_WEBHOOK_URL, data={"content": "Motion detected!"}, files={"file": f}, timeout=5)
                os.remove(image_path)
    except Exception as e:
        print("Discord alert failed:", e)

def send_alert():
    if not config.EMAIL_ENABLED:
        return
    try:
        msg = EmailMessage()
        msg.set_content("Motion detected at front door!")
        msg["From"] = config.EMAIL_USER
        msg["To"] = ",".join(config.EMAIL_TO)

        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.EMAIL_USER, config.EMAIL_PASS)
            server.send_message(msg)
    except Exception as e:
        print("Email failed:", e)

# ----------------------------
# DRIVE UPLOAD
# ----------------------------
def upload_clip_to_drive(filename):
    date_folder = get_date_folder()
    local_path = os.path.join(config.SAVE_PATH, filename)
    remote_dir = f"pidrive:RaspberryPiClips/{date_folder}"  # change pidrive and RaspberryPiClips to correct names
    remote_path = f"{remote_dir}/{filename}"

    if not os.path.exists(local_path):
        print("Local file does not exist:", local_path)
        return None

    try:
        subprocess.run(["rclone","mkdir",remote_dir], check=True)
        subprocess.run(["rclone","copy",local_path,remote_dir], check=True)
        print("Uploaded to Google Drive:", filename)

        result = subprocess.run(["rclone", "link", remote_path], capture_output=True, text=True, check=True)
        drive_link = result.stdout.strip()
        print("Drive link:", drive_link)

        os.remove(local_path)
        print("Local clip deleted:", drive_link)

        return drive_link
    except Exception as e:
        print("Drive upload failed:", e)
        return None

# ----------------------------
# SNAPSHOT
# ----------------------------
def take_snapshot():
    if latest_frame is None:
        time.sleep(0.05)
        return None
    frame = latest_frame.copy()
    filename = f"snapshot_{filename_creator()}.jpg"
    cv2.imwrite(filename, frame)
    return filename

# ----------------------------
# RECORD CLIP
# ----------------------------
def record_clip():
    filename = f"motion_{filename_creator()}.avi"
    path = os.path.join(config.SAVE_PATH, filename)
    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    out = cv2.VideoWriter(path, fourcc, FPS, (640, 480))

    # Write pre-roll
    for f in list(frame_buffer):
        out.write(f)
    print(f"Pre-roll written ({len(frame_buffer)} frames)")

    last_motion_time = time.time()
    while True:
        if latest_frame is None:
            time.sleep(0.05)
            continue

        frame = latest_frame.copy()
        out.write(frame)

        mask = bg_subtractor.apply(frame[ROI_Y:ROI_Y+ROI_H, ROI_X:ROI_X+ROI_W])
        motion_pixels = cv2.countNonZero(mask)

        if motion_pixels > 5000:
            last_motion_time = time.time()

        if time.time() - last_motion_time > POST_ROLL_SECONDS:
            break

        time.sleep(1 / FPS)

    out.release()
    print("Recording complete:", path)
    return filename

# ----------------------------
# MOTION DETECTION
# ----------------------------
def detect_motion():
    COOLDOWN_SECONDS = 15
    WARMUP_SECONDS = 2.0
    MIN_MOTION_FRAMES = 3
    MOTION_RATIO_THRESHOLD = 0.07

    last_trigger_time = 0
    motion_frames = 0
    motion_enabled_time = None

    print("Motion thread started")

    while not STOP_PROGRAM:
        if not config.MOTION_ENABLED:
            motion_enabled_time = None
            motion_frames = 0
            time.sleep(0.3)
            continue

        if motion_enabled_time is None:
            # Motion warmup
            motion_enabled_time = time.time()
            print("Motion warmup start")
            time.sleep(WARMUP_SECONDS)
            print("Motion warmup complete")
            continue

        if latest_frame is None:
            time.sleep(0.05)
            continue

        frame = latest_frame.copy()
        roi = frame[ROI_Y:ROI_Y+ROI_H, ROI_X:ROI_X+ROI_W]
        mask = bg_subtractor.apply(roi)
        _, thresh = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        motion_pixels = cv2.countNonZero(thresh)
        motion_ratio = motion_pixels / (ROI_W * ROI_H)

        if motion_ratio > MOTION_RATIO_THRESHOLD:
            motion_frames += 1
        else:
            motion_frames = max(0, motion_frames - 1)

        now = time.time()
        if motion_frames >= MIN_MOTION_FRAMES and (now - last_trigger_time) > COOLDOWN_SECONDS:
            last_trigger_time = now
            motion_frames = 0
            print(f"Door motion detected ({motion_ratio:.1%})")
            try:
                snapshot = take_snapshot()
                send_discord_alert(snapshot, None)
                clip = record_clip()
                drive_link = upload_clip_to_drive(clip)
                send_alert()
                send_discord_alert(snapshot, drive_link)
            except Exception as e:
                print("Motion handling error:", e)

        # Adjust day/night
        if int(time.time()) % 5 == 0:
            if is_night(frame):
                apply_night_settings()
            else:
                apply_day_settings()

        time.sleep(0.05)

# ----------------------------
# LIVE STREAM
# ----------------------------
def gen_frames():
    while True:
        if not config.STREAM_ENABLED:
            time.sleep(0.2)
            continue

        if latest_frame is None:
            time.sleep(0.05)
            continue

        frame = latest_frame.copy()
        last_frame_time = time.time()

        if config.SHOW_MOTION_ROI:
            cv2.rectangle(frame, (ROI_X, ROI_Y), (ROI_X+ROI_W, ROI_Y+ROI_H), (0,255,0), 2)
            cv2.putText(frame, "Motion ROI", (ROI_X+5, ROI_Y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

        _, buffer = cv2.imencode(".jpg", frame)
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
