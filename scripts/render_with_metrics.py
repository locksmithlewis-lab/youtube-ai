import subprocess

# render_video.py now atomically claims a queued job and records its own timing.
# Keep this wrapper so existing workflow entrypoints remain compatible.
subprocess.run(['python','scripts/render_video.py'],check=True)
