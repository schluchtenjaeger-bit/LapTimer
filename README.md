# LapTimer
A lightweight system for recording and displaying lap times in RC car racing.

# RC Car Lap Timer

A lightweight system for recording and displaying lap times in RC car racing.  
Built to be simple, flexible, and easy to set up for hobby use.

## Features
- Records lap times with infrared (IR) sensors
- Displays results on a web interface
- Supports multiple drivers
- Works in standalone mode (no internet connection required)
- Battery status monitoring

## Requirements
- Raspberry Pi Zero 2 W (or similar)
- IR receiver module
- Python 3
- Flask
- pigpio library

## Installation
1. Clone this repository:
   ```bash
   git clone https://github.com/your-username/your-repo.git
   cd your-repo
Install dependencies:

bash
Code kopieren
sudo apt update
sudo apt install python3-flask python3-pigpio
Start the lap timer:

bash
Code kopieren
python3 lt.py
Open your browser and go to:

cpp
Code kopieren
http://<raspberrypi-ip>:5000
