# Motion Doorbell Camera

Made using Raspberry Pi 2 Model B and a 7" Touch Screen using Flask. Will detect motion in a ROI and send an email, text (only tested Verizon and AT&T - AT&T did not work), and discord notification.
There also is a livestream that should remain local.

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes. See deployment for notes on how to deploy the project on a live system.

### Prerequisites

* Raspberry Pi - this project was created with 2 Model B
* Screen/Monitor - this project used the 7" Touch Screen Module for RPi
* Camera - used the RPI Camera module
* Discord (if you want to use the webhook option - create a Webhook in Edit Channel --> Integrations)
* Email (Google if want to save clips via Google Drive, Phone optional)


### Installing

#### Base Setup

Once you have your RPi set up,

Install necessary packages

```
sudo apt update
sudo apt install python3-opencv python3-flask python3-picamera2 mailutils rclone
pip install imutils
```

Download this repository and make sure your files are organized the same way this repository is.
Connect your pi to Google Drive:

```
rclone config
```

Then fill in the following:

```
1. n
2. name: gdrive (i used pidrive)
3. 18 (make sure it aligns with Google Drive)
4. Enter (or create a Client ID and Secret using Google Cloud Platform - recommended)
5. Scope: 1
6. Enter
7. Edit Advanced Config? n
8. Use auto config? y
```

(and don't make it a Team Drive in most cases)
Inside Google Drive, create a folder to hold your clips. I called mine RaspberryPiClips.


To test if it is working, cd inside the main folder and run:

```
python3 app.py
```

Open one of the links to view the page. You should see two toggle buttons on the left and a livestream area on the right.

#### Desktop App

If you want a desktop-based app instead of a web-based one:

```
sudo apt install nodejs npm
mkdir ~/project_name_desktop
cd ~/project_name_destop
npm init -y
npm install electron
```

Once you verify start.sh is correct:

```
chmod +x start.sh
```

#### Autostart

If you want it to start on boot:

```
mkdir -p ~/.config autostart
nano ~/.config/autostart/chosenname.desktop
```

Once inside the file:

```
[Desktop Entry]
Type=Application
Name=Motion Camera
Exec=/path/to/start.sh
X-GNOME-Autostart-enabled=true
```

Then navigate to:

```
sudo nano /etc/systemd/system/projectname.service
```

Once inside the file:

```
[Unit]
Description=Motion Camera Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /path/to/app.py
WorkingDirectory=/path/to/project_folder (not desktop)
Restart=on-failure
RestartSec=5
User=username
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Then run:

```
sudo systemctl daemon-reload
sudo systemctl enable project_folder
sudo systemctl start project_folder
```


To start:

```
~/project_name_desktop/start.sh
```

## Notes

* This was made just to test things out, I wouldn't expose any of the camera feed in a non-local way.

## Improvements

* The clip recording starts too late and is too short, fixing that next.

