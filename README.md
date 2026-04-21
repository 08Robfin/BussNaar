# 🚌 BussNaar?
> BussNår? - Når er bussen?

A lightweight, background-running Windows app that sits in your system tray and tells you exactly when your next bus is leaving. Built with Python, using the official Entur API.

Perfect for students or commuters who just want to check the bus without opening a slow browser or a clunky mobile app.

## ✨ Features
* **System Tray Integration:** Runs silently in the background. 
* **Instant Departure Board:** Left-click the tray icon to pop up a clean window showing the next 5 departures with exact times.
* **Smart Setup Wizard:** First time running? A modern UI wizard guides you through searching for your stop and selecting your specific bus line.
* **Client-Side Filtering:** Handles busy bus stops by fetching up to 150 departures and locally filtering out only the exact route you care about.
* **Live Map Link:** Trust issues? Click the map button in the app to open the Entur Live Map for your stop in your browser.
* **School-Network Proof:** Ignores pesky SSL-inspection blockers common on school/corporate WiFi networks.

## 🛠️ Tech Stack
* **Python 3**
* **CustomTkinter** - For the modern dark/light mode setup wizard and departure UI.
* **Pystray** - For the system tray icon integration.
* **Requests** - For talking to the Entur GraphQL and Geocoder APIs.
* **Pillow** - For generating the dynamic tray icon image with real-time minutes.

## 🚀 How to Run

1. Make sure you have [Python](https://www.python.org/downloads/) installed.
2. Clone this repository:
   ```bash
   git clone [https://github.com/YOUR_USERNAME/BussNaar.git](https://github.com/YOUR_USERNAME/BussNaar.git)
   ```
3. Go to the folder and run the script.
   
*(Note: The app will automatically install required packages like `customtkinter` and `pystray` on its first run if you don't have them).*

## ⚙️ Configuration
The app saves your chosen route locally in `%userprofile%\BussNaar\config.json`. 

If you ever want to change your route or stop, just **right-click** the tray icon and select "Endre rute / Innstillinger" to open the wizard again. Or simply delete the `config.json` file for a hard reset to factory settings.

## 📡 API Credits
Data is fetched via the open **[Entur API](https://developer.entur.org/)** (National Access Point for public transport data in Norway). No API key is required to run this app, as it complies with Entur's open data guidelines using standard client headers.

---
*Created for personal use & learning.*
