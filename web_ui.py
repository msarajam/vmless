# web_ui.py
from flask import Flask, Response, render_template_string
import io
import contextlib
import os
import subprocess
import random
from typing import List, Dict

# ---------------- CONFIG ----------------
REPO_URL = "https://github.com/Epodonios/v2ray-configs.git"
BRANCH = "main"
LOCAL_REPO_PATH = "./vpn_repo"
TARGET_SUBDIR = "Splitted-By-Protocol"
FILENAME = "vmess.txt"
SCHEME = "vmess://"
# ----------------------------------------

app = Flask(__name__)

def run_command(command, cwd=None):
    result = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        capture_output=True,
        text=True
    )
    print(command, cwd)
    print("Output:", result.stdout)
    if result.returncode != 0:
        print("Error:", result.stderr)
        raise Exception(f"Command failed ({command}): {result.stderr.strip()}")
    return result.stdout.strip()

def clone_or_pull_repo():
    if not os.path.exists(LOCAL_REPO_PATH):
        print("Cloning repository...")
        run_command(f"git clone --depth 1 -b {BRANCH} {REPO_URL} {LOCAL_REPO_PATH}")
    else:
        print("Pulling latest changes...")
        run_command("git fetch", cwd=LOCAL_REPO_PATH)
        run_command(f"git checkout {BRANCH}", cwd=LOCAL_REPO_PATH)
        run_command("git pull", cwd=LOCAL_REPO_PATH)

def list_files_in_repo():
    target_path = os.path.join(LOCAL_REPO_PATH, TARGET_SUBDIR)
    file_path = os.path.join(target_path, FILENAME)

    if os.path.isfile(file_path):
        print(f"{FILENAME} exists at: {file_path}")
    else:
        print(f"{FILENAME} not found in {target_path}")

def read_lines(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]

def group_by_first_4_after_scheme(lines: List[str]) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for line in lines:
        if line.lower().startswith(SCHEME):
            body = line[len(SCHEME):]
        else:
            body = line

        key = body[:4] if len(body) >= 4 else body
        groups.setdefault(key, []).append(line)

    return groups

def pick_random_unique_groups(count: int = 15):
    file_path = os.path.join(LOCAL_REPO_PATH, TARGET_SUBDIR, FILENAME)

    if not os.path.isfile(file_path):
        raise Exception(f"File not found: {file_path}")

    lines = read_lines(file_path)
    groups = group_by_first_4_after_scheme(lines)

    selected = []

    group_keys = list(groups.keys())
    random.shuffle(group_keys)

    for key in group_keys:
        if len(selected) >= count:
            break
        selected.append(random.choice(groups[key]))

    return selected

# Simple HTML template — print captured output and the selected lines
HTML = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Momo for Babak</title>
    <style>
      body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial; margin: 20px; }
      pre { background: #f6f8fa; padding: 12px; border-radius: 6px; overflow: auto; }
      .error { color: darkred; font-weight: bold; }
    </style>
  </head>
  <body>
    <h1>List of vmess</h1>
    {% if error %}
      <div class="error">Error: {{ error }}</div>
    {% endif %}

<pre><code>
{% for line in selected -%}
{{ loop.index }}. {{ line | e }}
{% endfor -%}
</code></pre>
  </body>
</html>
"""

@app.route("/")
def index():
    buf = io.StringIO()
    selected = []
    error_msg = None

    # capture all prints from the functions so they show up in the web UI
    try:
        with contextlib.redirect_stdout(buf):
            clone_or_pull_repo()
            list_files_in_repo()
            selected = pick_random_unique_groups(15)
    except Exception as e:
        # capture exception info in stdout as well
        with contextlib.redirect_stdout(buf):
            print("Exception while running:", e)
        error_msg = str(e)

    stdout_contents = buf.getvalue()
    return render_template_string(HTML, stdout=stdout_contents, selected=selected, error=error_msg)

if __name__ == "__main__":
    # run on 0.0.0.0 so you can access it from other devices if needed; set debug=False for production
    app.run(host="0.0.0.0", port=9090, debug=True)
