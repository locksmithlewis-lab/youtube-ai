#!/usr/bin/env python3
"""Create a YouTube OAuth refresh token locally for Rolixa.

Uses only Python's standard library. Requires a Google OAuth client of type
"Desktop app" in the Google Cloud project where YouTube Data API v3 is enabled.
The token is saved outside the repository with owner-only file permissions.
"""
import getpass
import json
import os
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
REDIRECT_URI = f"http://{HOST}:{PORT}/"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
CALLBACK_TIMEOUT = 300


class CallbackHandler(BaseHTTPRequestHandler):
    auth_code = None
    auth_error = None
    expected_state = None
    completed = threading.Event()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if parsed.path != "/":
            self.send_error(404)
            return
        state = params.get("state", [""])[0]
        if state != self.expected_state:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"State check failed. You can close this tab.")
            return
        if params.get("error"):
            self.auth_error = params["error"][0]
        else:
            self.auth_code = params.get("code", [None])[0]
        self.completed.set()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<!doctype html><title>Rolixa authorization</title>"
            b"<h2>Authorization received.</h2>"
            b"<p>You can close this tab and return to the terminal.</p>"
        )

    def log_message(self, *_args):
        pass


def post_form(url, values):
    body = urllib.parse.urlencode(values).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Google token exchange failed ({exc.code}): {detail[:700]}") from exc


def main():
    print("\nRolixa — create a YouTube refresh token locally\n")
    print("Use a Google OAuth client whose application type is Desktop app.")
    client_id = input("Google OAuth Client ID: ").strip()
    client_secret = getpass.getpass("Google OAuth Client Secret (hidden): ").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Client ID and client secret are both required.")

    state = secrets.token_urlsafe(32)
    CallbackHandler.auth_code = None
    CallbackHandler.auth_error = None
    CallbackHandler.expected_state = state
    CallbackHandler.completed.clear()

    try:
        server = HTTPServer((HOST, PORT), CallbackHandler)
    except OSError as exc:
        raise RuntimeError(f"Could not start local callback on {HOST}:{PORT}. Close any app using that port and retry.") from exc
    server.timeout = 1
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    print("\nOpening Google sign-in. Choose the account for the YouTube channel Rolixa should publish to.")
    print("If a browser does not open, copy this URL into your browser:\n")
    print(url + "\n")
    webbrowser.open(url)

    try:
        if not CallbackHandler.completed.wait(CALLBACK_TIMEOUT):
            raise RuntimeError("Timed out waiting for Google authorization. Run the helper again.")
    finally:
        server.shutdown()
        server.server_close()

    if CallbackHandler.auth_error:
        raise RuntimeError("Google authorization was not completed: " + CallbackHandler.auth_error)
    if not CallbackHandler.auth_code:
        raise RuntimeError("Google returned no authorization code. Run the helper again.")

    tokens = post_form(TOKEN_URL, {
        "code": CallbackHandler.auth_code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    })
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "Google did not return a refresh token. Check that you used a Desktop app OAuth client, "
            "enabled YouTube Data API v3, and approved the requested access. "
            "Google response fields: " + ", ".join(sorted(tokens.keys()))
        )

    output = Path.home() / ".rolixa" / "youtube_refresh_token.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(refresh_token + "\n", encoding="utf-8")
    try:
        os.chmod(output, 0o600)
    except OSError:
        pass
    print("\nSUCCESS: refresh token saved locally.")
    print(f"File: {output}")
    print("\nNext: copy the file's contents into GitHub repository secret YOUTUBE_REFRESH_TOKEN.")
    print("Do not commit the token or paste it into chat. Keep the file private.")
    print("If Google shows an unverified-app warning, continue only if you recognize your own OAuth project.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyboardInterrupt) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
