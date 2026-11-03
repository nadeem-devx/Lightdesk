# Lightdesk

A desktop application for controlling a WiZ smart bulb over your local network.

## Features

- Turn the bulb on and off
- Adjust brightness
- Choose colours using the colour controls
- Use the available scene presets
- Pick a colour from the screen with the eyedropper
- Change the bulb's local IP address from the app; the setting is saved for future launches

## Requirements

- Windows (the app uses PySide6)
- Python 3.10 or newer
- A compatible WiZ smart bulb connected to the same local network as your computer

## Setup

1. Install Python.
2. Download or clone this repository.
3. Open a terminal in the project folder.
4. (Optional but recommended) Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

5. Install the dependency:

   ```powershell
   pip install -r requirements.txt
   ```

## Run

```powershell
python lightdesk_app.py
```

When the app opens, enter your bulb's current local IP address in the IP field and apply it. Your computer and bulb must be on the same local network. The app communicates with the bulb using UDP on port `38899`.

## Notes

- The bulb's IP address can change when your router assigns a new address. Update it in the app when needed.
- This project controls the bulb locally; it does not require a cloud account or a paid API for the UDP control used by the app.
- This project is an independent community project and is not affiliated with or endorsed by WiZ or Signify.

## Project structure

```text
Lightdesk/
├── lightdesk_app.py
├── requirements.txt
├── .gitignore
├── LICENSE
└── README.md
```
