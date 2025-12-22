# Installation Guide

## Requirements
- Python 3.11 or higher
- `pip` (Python Package Installer)
- A Discord Bot Token
- (Optional) Twitch API Credentials

## Steps

1. **Clone the Repository**
   ```bash
   git clone https://github.com/YourUser/L8teBot.git
   cd L8teBot
   ```

2. **Install Dependencies**
   It is recommended to use a virtual environment.
   ```bash
   python -m venv venv
   # Windows
   .\venv\Scripts\activate
   # Linux/Mac
   source venv/bin/activate
   
   pip install -r requirements.txt
   ```

3. **Start the Bot**
   ```bash
   python main.py
   ```

4. **First Run Setup**
   - On the first start, the bot will detect missing configuration.
   - It will launch a local web server at `http://localhost:5000`.
   - Open this URL in your browser.
   - Enter your `Discord Bot Token`, `Client ID`, `Client Secret`, and `Redirect URI`.
   - (Optional) Enter Twitch credentials if you want to use Twitch features.
   - Click "Save & Start".
   - The bot will restart automatically with your new configuration.
