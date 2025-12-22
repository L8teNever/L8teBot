from flask import Flask, render_template_string, request, redirect, url_for
import json
import os
import webbrowser
import threading
import time

setup_app = Flask(__name__)

from utils.config import BOT_CONFIG_FILE, DATA_DIR

# Ensure data dir exists
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

CONFIG_FILE = BOT_CONFIG_FILE

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>L8teBot Setup</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #121212; color: #ffffff; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .container { background-color: #1e1e1e; padding: 2rem; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); width: 100%; max-width: 500px; }
        h1 { text-align: center; color: #7289da; margin-bottom: 1.5rem; }
        .form-group { margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.5rem; color: #b9bbbe; }
        input[type="text"], input[type="password"] { width: 100%; padding: 0.75rem; border-radius: 5px; border: 1px solid #40444b; background-color: #2f3136; color: white; box-sizing: border-box; }
        input:focus { outline: none; border-color: #7289da; }
        button { width: 100%; padding: 0.75rem; background-color: #7289da; color: white; border: none; border-radius: 5px; font-size: 1rem; cursor: pointer; transition: background 0.2s; margin-top: 1rem; }
        button:hover { background-color: #5b6eae; }
        .note { font-size: 0.8rem; color: #72767d; margin-top: 0.5rem; }
    </style>
</head>
<body>
    <div class="container">
        <h1>L8teBot Setup</h1>
        <p style="text-align: center; margin-bottom: 2rem;">Welcome! Please configure your bot to get started.</p>
        <form method="POST">
            <div class="form-group">
                <label for="token">Discord Bot Token</label>
                <input type="password" id="token" name="token" required placeholder="OT... (from Discord Developer Portal)">
            </div>
            
            <div class="form-group">
                <label for="client_id">Discord Client ID</label>
                <input type="text" id="client_id" name="client_id" required placeholder="1234...">
            </div>

            <div class="form-group">
                <label for="client_secret">Discord Client Secret</label>
                <input type="password" id="client_secret" name="client_secret" required>
            </div>

            <div class="form-group">
                <label for="redirect_uri">Discord Redirect URI</label>
                <input type="text" id="redirect_uri" name="redirect_uri" value="http://localhost:5000/callback" required>
                <div class="note">Must match the Redirect URI in Discord Developer Portal.</div>
            </div>

            <div class="form-group">
                <label for="twitch_id">Twitch Client ID (Optional)</label>
                <input type="text" id="twitch_id" name="twitch_id">
            </div>

            <div class="form-group">
                <label for="twitch_secret">Twitch Client Secret (Optional)</label>
                <input type="password" id="twitch_secret" name="twitch_secret">
            </div>

            <button type="submit">Save & Start Bot</button>
        </form>
    </div>
</body>
</html>
"""

SUCCESS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta http-equiv="refresh" content="5;url=/" />
<style>
body { font-family: sans-serif; background: #121212; color: #43b581; display:flex; height:100vh; justify-content:center; align-items:center; text-align:center;}
</style>
</head>
<body>
<div>
    <h1>Configuration Saved!</h1>
    <p>The bot is restarting with the new configuration...</p>
    <p>You can close this tab.</p>
</div>
</body>
</html>
"""

@setup_app.route('/', methods=['GET', 'POST'])
def setup():
    if request.method == 'POST':
        config_data = {
            "token": request.form.get('token'),
            "DISCORD_CLIENT_ID": request.form.get('client_id'),
            "DISCORD_CLIENT_SECRET": request.form.get('client_secret'),
            "DISCORD_REDIRECT_URI": request.form.get('redirect_uri'),
            "TWITCH_CLIENT_ID": request.form.get('twitch_id', ''),
            "TWITCH_CLIENT_SECRET": request.form.get('twitch_secret', '')
        }
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=4)
        
        # Determine the trigger to stop server
        shutdown_server()
        return SUCCESS_TEMPLATE
    
    return render_template_string(HTML_TEMPLATE)

def shutdown_server():
    """Stop the Flask server and exit the process to trigger a container restart."""
    def killer():
        time.sleep(2)
        print("Stopping setup server and restarting container...")
        os._exit(0)
    
    threading.Thread(target=killer).start()

def run_setup_server():
    print("Starting Setup Server on http://0.0.0.0:5000")
    # Open browser after a short delay
    # threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5000")).start()
    setup_app.run(host="0.0.0.0", port=5000, debug=False)

if __name__ == "__main__":
    run_setup_server()
