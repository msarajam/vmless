# web_ui.py
from flask import Flask, Response, render_template_string
from typing import List, Dict
import io
import contextlib
import os
import subprocess
import random
import sys
import base64, json, urllib.parse

# ---------------- CONFIG ----------------
REPO_URL = "https://github.com/Epodonios/v2ray-configs.git"
BRANCH = "main"
LOCAL_REPO_PATH = "./vpn_repo"
TARGET_SUBDIR = "Splitted-By-Protocol"
FILENAME = "vmess.txt"
SCHEME = "vmess://"
# ----------------------------------------

app = Flask(__name__)

class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


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

def decode_vmess(uri: str) -> dict:
    try:
        assert uri.startswith("vmess://")
        b64 = uri[len("vmess://"):]
        # some implementations use URL-safe base64 or omit padding
        b64 = b64.replace('-', '+').replace('_', '/')
        # pad
        padding = (-len(b64)) % 4
        b64 += "=" * padding
        raw = base64.b64decode(b64)
        try:
            j = json.loads(raw.decode('utf-8'))
            return j
        except Exception:
            return None
    except Exception as e:   
        return None

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
        group_size = len(groups[key])
        
        if group_size < 5:
            continue
        thresholds = [
            (10, 1),
            (50, 2),
            (100, 3),
            (300, 5),
        ]
        
        num_to_add = sum(amount for limit, amount in thresholds if group_size > limit)
        
        for _ in range(num_to_add):
            if len(selected) >= count:
                break
            checkLine = random.choice(groups[key])
            dLine = decode_vmess(checkLine)
            if dLine == None:
                continue
            selected.append(checkLine)

        
    return selected

# Simple HTML template — print captured output and the selected lines
HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Momo for Babak</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />

  <style>
    :root{
      --bg:#f6f8fa;
      --muted:#6b7280;
      --accent:#0ea5a4;
      --success-bg:#dcfce7;
      --success-text:#166534;
    }

    body {
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial;
      margin: 20px;
      color:#111827;
    }

    header {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      margin-bottom:16px;
    }

    h1{ font-size:1.25rem; margin:0; }

    .meta{
      color:var(--muted);
      font-size:0.95rem;
    }

    .error {
      color: darkred;
      font-weight: 600;
      margin-bottom:12px;
    }

    .list-box {
      background:var(--bg);
      padding:12px;
      border-radius:8px;
      font-family: monospace;
    }

    .line-row {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
      padding:6px 8px;
      border-radius:6px;
      margin-bottom:4px;
      transition: background 0.3s ease;
    }

    .line-row:nth-child(odd){
      background:rgba(0,0,0,0.02);
    }

    /* Highlight copied line */
    .line-row.copied {
      background: var(--success-bg);
      color: var(--success-text);
    }

    .line-text {
      flex:1;
      word-break:break-all;
    }

    button {
      background:var(--accent);
      color:white;
      border:0;
      padding:6px 10px;
      border-radius:6px;
      cursor:pointer;
      font-weight:600;
      font-size:0.85rem;
    }

    button.copied-btn {
      background: var(--success-text);
    }

    @media (max-width:520px){
      body{margin:12px}
      header{flex-direction:column;align-items:flex-start}
    }
  </style>
</head>

<body>

<header>
  <div>
    <h1>List of vmess</h1>
    <div class="meta">
      Selected: <strong>{{ selected|length }}</strong> lines
    </div>
  </div>
</header>

{% if error %}
  <div class="error">Error: {{ error }}</div>
{% endif %}

<h2 style="margin:12px 0 8px 0; font-size:1rem;">Selected lines</h2>

<div class="list-box" id="selectedBox">
  {% for line in selected -%}
  <div class="line-row">
    <span class="line-text">{{ line | e }}</span>
    <button class="copy-btn">Copy</button>
  </div>
  {% endfor -%}
</div>

<script>
  document.getElementById('selectedBox').addEventListener('click', async function(e) {

    if (!e.target.classList.contains('copy-btn')) return;

    const row = e.target.closest('.line-row');
    const text = row.querySelector('.line-text').innerText.trim();

    try {
      await navigator.clipboard.writeText(text);

      // Change button text permanently
      e.target.textContent = "Copied ✓";
      e.target.classList.add("copied-btn");

      // Highlight copied line
      row.classList.add("copied");

    } catch (err) {
      alert("Clipboard copy failed. Use HTTPS or localhost.");
    }

  });
</script>

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
        tee = Tee(sys.stdout, buf)
        with contextlib.redirect_stdout(tee):
            clone_or_pull_repo()
            list_files_in_repo()
            selected = pick_random_unique_groups(15)
    except Exception as e:
        tee = Tee(sys.stdout, buf)
        with contextlib.redirect_stdout(tee):
            print("Exception while running:", e)
        error_msg = str(e)

    stdout_contents = buf.getvalue()
    return render_template_string(HTML, stdout=stdout_contents, selected=selected, error=error_msg)

if __name__ == "__main__":
    # run on 0.0.0.0 so you can access it from other devices if needed; set debug=False for production
    app.run(host="0.0.0.0", port=9090, debug=True)
