from flask import Flask, render_template, redirect, url_for, send_from_directory, Response
import threading
import motion
import config
import time
import sys
import signal

app = Flask(__name__)

def shutdown_handler(sig, frame):
    print("Shutting down...")
    motion.STOP_PROGRAM = True
    try:
        motion.picam.stop()
    except:
        pass
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

@app.route("/video_feed")
def video_feed():
    return Response(motion.gen_frames(),mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/clips/<filename>")
def serve_clip(filename):
    return send_from_directory("clips",filename)

@app.route("/toggle")
def toggle():
    config.MOTION_ENABLED = not config.MOTION_ENABLED
    return redirect(url_for("index"))

@app.route("/toggle_stream", methods=["POST"])
def toggle_stream():
    config.STREAM_ENABLED = not config.STREAM_ENABLED
    return redirect("/")

@app.route("/")
def index():
    return render_template(
        "index.html",
        enabled=config.MOTION_ENABLED,
        stream_enabled=config.STREAM_ENABLED
    )

if __name__ == "__main__":
    threading.Thread(target=motion.camera_loop, daemon=True).start()
    threading.Thread(target=motion.detect_motion, daemon=True).start()
    threading.Thread(target=motion.alert_worker, daemon=True).start()
    threading.Thread(target=motion.camera_watchdog, daemon=True).start()
    print("Starting Flask Server")
    app.run(host="0.0.0.0", port=5000,debug=False, use_reloader=False)
