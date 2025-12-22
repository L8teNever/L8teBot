# Configuration

The L8teBot uses a `config.json` file stored in the `data/` directory.

## First Run
The bot includes a Setup Wizard. If `config.json` is missing or invalid, the bot starts a web interface to help you generate it.

## Manual Configuration
You can also manually edit `data/config.json`:

```json
{
  "token": "YOUR_DISCORD_BOT_TOKEN",
  "DISCORD_CLIENT_ID": "YOUR_CLIENT_ID",
  "DISCORD_CLIENT_SECRET": "YOUR_CLIENT_SECRET",
  "DISCORD_REDIRECT_URI": "http://your-domain.com/callback",
  "TWITCH_CLIENT_ID": "OPTIONAL_TWITCH_ID",
  "TWITCH_CLIENT_SECRET": "OPTIONAL_TWITCH_SECRET"
}
```

## Security
- **NEVER** commit `config.json` to GitHub.
- The `.gitignore` file is pre-configured to exclude `data/` and `config.json`.
