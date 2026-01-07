#!/bin/bash

# Paths
FLASK_APP_DIR="/path/to/project_folder"
ELECTRON_APP_DIR="/home/username/project_name_desktop"

echo "Starting Flask backend..."
cd "$FLASK_APP_DIR"
python3 app.py &
FLASK_PID=$!

sleep 5
echo "Starting Electron UI..."
cd "$ELECTRON_APP_DIR"
npm start &
ELECTRON_PID=$!

echo "Motion Cam system running"
echo "Flask PID: $FLASK_PID"
echo "Electron PID: $ELECTRON_PID"

wait $FLASK_PID
