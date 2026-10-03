# Create Rolixa's YouTube refresh token

This helper authorizes YouTube locally, so you do not need the Google OAuth Playground or Supabase. It does not upload videos itself and never sends the token to Rolixa's repository.

## 1. Configure Google OAuth once

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Select the Google Cloud project used for Rolixa, or create a project.
3. In **APIs & Services → Library**, enable **YouTube Data API v3**.
4. Configure the Google Auth Platform / OAuth consent screen. If the app is in **Testing**, add the Google account that owns/manages the target YouTube channel as a test user.
5. In **APIs & Services → Credentials**, create an OAuth client ID with application type **Desktop app**.
6. Copy the client ID and client secret. Do not add either to source code.

Google may show an app warning if the consent screen is not verified. Continue only if the OAuth project is yours and the permissions shown are expected.

## 2. Run the helper on your computer

Python 3 is required. Download `scripts/get_youtube_refresh_token.py` from this repository, then run it in Terminal (macOS/Linux) or PowerShell (Windows):

```sh
python3 get_youtube_refresh_token.py
```

On Windows, if `python3` is not recognized, use:

```powershell
py get_youtube_refresh_token.py
```

Enter the Desktop app client ID and client secret when prompted. The helper opens Google sign-in; choose the correct YouTube account and approve the requested YouTube upload permission. A local callback receives the authorization response. No web server is exposed to the internet.

The refresh token is saved to:
- macOS/Linux: `~/.rolixa/youtube_refresh_token.txt`
- Windows: `%USERPROFILE%\.rolixa\youtube_refresh_token.txt`

Keep this file private. If the local callback port 8765 is busy, close the conflicting app and retry.

## 3. Add it to GitHub Actions

In the repository, open **Settings → Secrets and variables → Actions → New repository secret**.

- Name: `YOUTUBE_REFRESH_TOKEN`
- Value: the full contents of `youtube_refresh_token.txt`

Save it. Do not commit the token or paste it into chat.

## 4. Publish existing videos

Open **Actions → Publish Existing R2 Batch → Run workflow**. Inspect the run logs and confirm each of the five entries says `VERIFIED_PUBLIC`. Do not rerun a partially successful batch until the publisher's existing-upload/idempotency behavior has been checked, to avoid duplicate uploads.

## Troubleshooting

- **redirect URI / OAuth client error:** make sure the client type is **Desktop app**, not Web application.
- **YouTube API disabled:** enable YouTube Data API v3 in the same Google Cloud project.
- **Access blocked while app is in Testing:** add the target Google account as a test user on the OAuth consent screen.
- **No refresh token returned:** rerun authorization and approve consent; use the correct Desktop app client.
- **Channel/account mismatch:** repeat authorization and select the Google account that manages the intended YouTube channel.
