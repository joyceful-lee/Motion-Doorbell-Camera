from email.message import EmailMessage
from picamera2 import Picamera2
from datetime import datetime
import cv2
import time
import os
import smtplib
import config
import requests
import threading
import subprocess

### GLOBAL VARIABLES
picam = None
camera_lock = threading.Lock()
last_frame_time = time.time()
STOP_PROGRAM = False
CAMERA_RESTART_REQUESTED = False

### CAMERA INIT
def init_camera():
    global picam

    if picam is None:
        picam = Picamera2()

    with camera_lock:
        try:
            picam.stop()
        except:
            pass

        picam.preview_configuration.main.size = (640, 480)
        picam.preview_configuration.main.format = "RGB888"
        picam.configure("preview")
        picam.start()
        print("Camera initialized")
        time.sleep(0.5)

### WATCHDOG THREAD
def camera_watchdog():
    global last_frame_time, STOP_PROGRAM, CAMERA_RESTART_REQUESTED
    while not STOP_PROGRAM:
        if (config.MOTION_ENABLED or config.STREAM_ENABLED):
            if time.time() - last_frame_time > 10:
                print("Camera seems frozen. Restarting...")
                CAMERA_RESTART_REQUESTED = True
        time.sleep(5)

def safe_capture():
    global CAMERA_RESTART_REQUESTED
    with camera_lock:
        if CAMERA_RESTART_REQUESTED:
            print("Restarting camera safely")
            try:
                picam.stop()
            except:
                pass
            init_camera()
            CAMERA_RESTART_REQUESTED = False

        return picam.capture_array()

### UTILITY FUNCTIONS
def get_date_folder():
    now = datetime.now()
    return f"{now.year}/{now.month:02d}/{now.day:02d}"  # organizes by year, month, then day.

def filename_creator():
    now = datetime.now()
    return f"{now.year}{now.month:02d}{now.day:02d}-{int(time.time())}" # file name is yearmonthday-time

os.makedirs(config.SAVE_PATH, exist_ok=True)

bg_subtractor = cv2.createBackgroundSubtractorMOG2()

### DRIVE UPLOAD
def upload_clip_to_drive(filename):
    date_folder = get_date_folder()
    local_path = os.path.join(config.SAVE_PATH, filename)
    remote_dir = f"pidrive:RaspberryPiClips/{date_folder}"  # used google drive api to allow edit access to save clips on drive in "RaspberryPiClips" rather than locally
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

        os.remove(local_path)  # deletes local file to save space (I don't have a lot of space on my pi)
        print("Local clip deleted:", drive_link)

        return drive_link
    except Exception as e:
        print("Drive upload failed:", e)
        return None

### ALERTS

# sends first discord webhook with a snapshot of motion followed by a second with a link to the google drive clip.
def send_discord_alert(image_path, drive_link=None):
    if not config.DISCORD_ENABLED:
        return
    try:
        if drive_link:
            requests.post(config.DISCORD_WEBHOOK_URL, data={"content": f"Clip: {drive_link}"}, timeout=5)
        else:
            with open(image_path, "rb") as f:
                requests.post(config.DISCORD_WEBHOOK_URL, data={"content": "Motion detected!"}, files={"file": f}, timeout=5)
                os.remove(image_path)
    except Exception as e:
        print("Discord alert failed:", e)

# sends an email and text (works well with Verizon as of 1/2026, but not with AT&T)
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

### SNAPSHOT
def take_snapshot():
    filename = f"snapshot_{filename_creator()}.jpg"
    try:
        frame = picam.capture_array()
    except Exception as e:
        print("Camera error, restarting:", e)
        init_camera()
        time.sleep(1)
        frame = safe_capture()
        last_frame_time = time.time()
    cv2.imwrite(filename, frame)
    return filename

### RECORD CLIP
def record_clip():
    filename = f"motion_{filename_creator()}.avi"
    path = os.path.join(config.SAVE_PATH, filename)
    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    out = cv2.VideoWriter(path, fourcc, 20.0, (640, 480))

    start = time.time()
    while time.time() - start < config.VIDEO_DURATION:
        try:
            frame = safe_capture()
            last_frame_time = time.time()
        except Exception as e:
            print("Camera error, restarting:", e)
            init_camera()
            time.sleep(1)
            continue
        out.write(frame)
    out.release()
    print("Saved:", path)
    return filename

### MOTION DETECTION
def detect_motion():
    global last_frame_time, STOP_PROGRAM, bg_subtractor

    motion_enabled_time = None   # None = motion currently disabled
    COOLDOWN_SECONDS = 10
    last_trigger_time = 0

    bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=50)

    while not STOP_PROGRAM:
        if not config.MOTION_ENABLED:
            motion_enabled_time = None
            time.sleep(0.3)
            continue

        if motion_enabled_time is None:
            print("Motion enabled → warming up background model")

            motion_enabled_time = time.time()
            bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=50)

            for _ in range(8):
                try:
                    frame = safe_capture()
                    last_frame_time = time.time()
                    bg_subtractor.apply(frame)
                    time.sleep(0.1)
                except Exception as e:
                    print("Camera error during warm-up:", e)
                    init_camera()
                    time.sleep(0.5)

            print("Motion warm-up complete")
            continue   # to prevent camera errors

        if time.time() - motion_enabled_time < 2.0:
            time.sleep(0.1)
            continue
        
        try:
            frame = safe_capture()
            last_frame_time = time.time()
        except Exception as e:
            print("Camera error, restarting:", e)
            init_camera()
            time.sleep(1)
            continue

        mask = bg_subtractor.apply(frame)
        _, thresh = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        motion_pixels = cv2.countNonZero(thresh)

        now = time.time()
        if motion_pixels > 5000 and (now - last_trigger_time) > COOLDOWN_SECONDS:
            last_trigger_time = now
            print(f"Motion detected ({motion_pixels} pixels)")

            send_alert()
            snapshot = take_snapshot()
            send_discord_alert(snapshot, None)  # snapshot webhook

            clip = record_clip()  # recording after alert, so inital alert isn't delayed by recording time
            drive_link = upload_clip_to_drive(clip)

            send_discord_alert(snapshot, drive_link)  # recording clip webhook

        time.sleep(0.05)

### LIVE STREAM
def gen_frames():
    global last_frame_time
    while True:
        if not config.STREAM_ENABLED:
            time.sleep(0.2)
            continue
        try:
            frame = safe_capture()
            last_frame_time = time.time()
        except Exception as e:
            print("Camera error, restarting:", e)
            init_camera()
            time.sleep(1)
            continue

        _, buffer = cv2.imencode(".jpg", frame)
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" +
               buffer.tobytes() + b"\r\n")
