# web_ui.py
from flask import Flask, Response, render_template
from typing import List, Dict
import io
import contextlib
import os
import subprocess
import random
import sys
import base64, json, urllib.parse
import glob
import base64
import json
import re
import uuid
import ipaddress
import time
import threading
from urllib.parse import urlparse, parse_qs, unquote

# ---------------- CONFIG ----------------
REPO_URL = "https://github.com/Epodonios/v2ray-configs.git"
BRANCH = "main"
LOCAL_REPO_PATH = "./vpn_repo"
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$"
)
_cooldown_seconds = 60  # change to whatever
_lock = threading.Lock()
_last_clone = 0.0

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
    if result.returncode != 0:
        raise Exception(f"Command failed ({command}): {result.stderr.strip()}")
    return result.stdout.strip()

def combineAll():
    pattern = LOCAL_REPO_PATH+"/Sub*.txt"
    output_file = "SubAll.txt"
    files = glob.glob(pattern)
    files = [f for f in files if os.path.basename(f) != output_file]
    files.sort()
    
    with open(output_file, "w", encoding="utf-8") as outfile:
        for filename in files:
            with open(filename, "r", encoding="utf-8") as infile:
                outfile.write(infile.read())
                outfile.write("\n")  # Optional: add newline between files

def remove_duplicates():
    # check if SubDone.txt exists, if not create it
    if not os.path.exists("SubDone.txt"):
        open("SubDone.txt", "w", encoding="utf-8").close() 
        return
    # Read FileBB into a set (fast lookup)
    with open("SubDone.txt", "r", encoding="utf-8") as f:
        bb_lines = set(line.strip() for line in f)
    
    # Keep only lines not in FileBB
    if not os.path.exists("SubAll.txt"):
        print("SubAll.txt not found, skipping duplicate removal.")
        return
    with open("SubAll.txt", "r", encoding="utf-8") as f:
        aa_lines = f.readlines()
    
    print(f"MOMO \n\tbb {len(bb_lines)}\n\taa {len(aa_lines)}\n\ta2 {len(aa_lines)/20}")

    if len(bb_lines)>(len(aa_lines)/20):
        os.remove("SubDone.txt")
        print("\tRemoved temp file")
        return

    filtered_lines = [
        line for line in aa_lines
        if line.strip() not in bb_lines
    ]
    print(f"\tRemoved {len(aa_lines) - len(filtered_lines)} duplicates, {len(filtered_lines)} lines remain.")
    # Overwrite FileAA
    with open("SubAll.txt", "w", encoding="utf-8") as f:
        f.writelines(filtered_lines)


def can_clone():
    global _last_clone
    with _lock:
        now = time.time()
        if now - _last_clone >= _cooldown_seconds:
            _last_clone = now
            return True
        return False

def clone_or_pull_repo():
    if not can_clone():
        print("Rate limited. Try again later.")
        return {"status": "error", "message": f"Rate limited. Try again in {int(_cooldown_seconds - (time.time()-_last_clone))}s"}
    # validate repo_url carefully before running git clone (see notes)
    if not os.path.exists(LOCAL_REPO_PATH):
        run_command(f"git clone --depth 1 -b {BRANCH} {REPO_URL} {LOCAL_REPO_PATH}")
        #remove SubAll.txt if exist
        sub_all_path = os.path.join( "SubAll.txt")
        if os.path.exists(sub_all_path):
            os.remove(sub_all_path)
    else:
        run_command("git fetch", cwd=LOCAL_REPO_PATH)
        run_command(f"git checkout {BRANCH}", cwd=LOCAL_REPO_PATH)
        run_command("git pull", cwd=LOCAL_REPO_PATH)
    combineAll()

def read_lines(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]

def group_by_first_4_after_scheme(lines: List[str],scheme: str="") -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for line in lines:
        if line.lower().startswith(scheme):
            body = line[len(scheme):]
        else:
            continue
        key = body[:6] if len(body) >= 6 else body
        groups.setdefault(key, []).append(line)

    return groups


def is_valid_uuid(val: str) -> bool:
    try:
        uuid.UUID(val)
        return True
    except Exception:
        return False

def is_valid_host(host: str) -> bool:
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except Exception:
        pass
    if host.startswith('[') and host.endswith(']'):
        try:
            ipaddress.ip_address(host[1:-1])
            return True
        except Exception:
            pass
    return bool(DOMAIN_RE.match(host))

def is_valid_port(port_str: str) -> bool:
    try:
        p = int(port_str)
        return 1 <= p <= 65535
    except Exception:
        return False

def decode_base64_padded(data: str) -> bytes:
    data = data.strip()
    data = data.replace('-', '+').replace('_', '/')
    padding = len(data) % 4
    if padding:
        data += '=' * (4 - padding)
    return base64.b64decode(data)

def validate_vmess(uri: str):
    parsed = urlparse(uri)
    payload = uri[len("vmess://"):] if uri.startswith("vmess://") else parsed.path
    payload = payload.split('#', 1)[0]
    payload = payload.strip()
    if not payload:
        return False, "empty vmess payload"
    try:
        raw = decode_base64_padded(payload)
    except Exception as e:
        return False, f"base64 decode failed: {e}"
    try:
        j = json.loads(raw.decode('utf-8', errors='replace'))
    except Exception as e:
        return False, f"json parse failed: {e}"
    if not isinstance(j, dict):
        return False, "decoded vmess payload not an object"
    required = ['add', 'port', 'id']
    missing = [k for k in required if k not in j or j[k] in (None, '')]
    if missing:
        return False, f"missing fields: {', '.join(missing)}"
    if not is_valid_host(str(j['add'])):
        return False, f"invalid host in 'add': {j['add']}"
    if not is_valid_port(str(j['port'])):
        return False, f"invalid port in 'port': {j['port']}"
    if not is_valid_uuid(str(j['id'])):
        return False, f"'id' is not a valid UUID: {j['id']}"
    return True, "ok"

def validate_vless(uri: str):
    parsed = urlparse(uri)
    if parsed.scheme.lower() != 'vless':
        return False, "scheme not vless"
    user = parsed.username  # uuid
    host = parsed.hostname
    port = parsed.port
    if not user or not is_valid_uuid(user):
        return False, "missing or invalid UUID (username part)"
    if not host or not is_valid_host(host):
        return False, "missing or invalid host"
    if port is None:
        return False, "missing port"
    if not is_valid_port(str(port)):
        return False, "invalid port"
    return True, "ok"

def validate_trojan(uri: str):
    # trojan://password@host:port?params#name
    parsed = urlparse(uri)
    if parsed.scheme.lower() != 'trojan':
        return False, "scheme not trojan"
    pwd = parsed.username  # password/token is placed as username in many trojan URIs
    host = parsed.hostname
    port = parsed.port
    if not pwd:
        return False, "missing password/token (username part)"
    if not host or not is_valid_host(host):
        return False, "missing or invalid host"
    if port is None:
        return False, "missing port"
    if not is_valid_port(str(port)):
        return False, "invalid port"
    return True, "ok"

def pick_random_unique_groups(filename: str ="",scheme: str ="",  count: int = 15):
    if not os.path.isfile(filename):
        raise Exception(f"File not found: {filename}")
    lines = read_lines(filename)
    groups = group_by_first_4_after_scheme(lines,scheme)
    selected = []
    group_keys = list(groups.keys())
    random.shuffle(group_keys)
    for key in group_keys:
        group_size = len(groups[key])
        thresholds = [
            (2, 1),
            (10, 2),
            (100, 3),
            (300, 5),
        ]
        num_to_add = sum(amount for limit, amount in thresholds if group_size > limit)
        try:
            for _ in range(num_to_add):
                if len(selected) >= count:
                    break
                msg=""
                checkLine = random.choice(groups[key])
                if scheme == "vmess://":
                    valid, msg = validate_vmess(checkLine)
                    if not valid:
                        continue
                elif scheme == "vless://":
                    valid, msg = validate_vless(checkLine)
                    if not valid:
                        continue
                elif scheme == "trojan://":
                    valid, msg = validate_trojan(checkLine)
                    if not valid:
                        continue
                selected.append(checkLine)
        except Exception as e:
            print(f"MOMO some Error \n{checkLine}\n{msg}\n{e}")
            continue
    return selected

@app.route("/")
def index():
    clone_or_pull_repo()   
    remove_duplicates()
    buf = io.StringIO()
    vmess = []
    vless = []
    trojan = []
    
    error_msg = None

    # vmess
    try:
        tee = Tee(sys.stdout, buf)
        with contextlib.redirect_stdout(tee):
            file_path = os.path.join( "./", "SubAll.txt")
            vmess = pick_random_unique_groups(file_path,"vmess://",15)
    except Exception as e:
        tee = Tee(sys.stdout, buf)
        with contextlib.redirect_stdout(tee):
            print("Exception while running vmess:", e)
        error_msg = str(e)
    
    # vless
    try:
        tee = Tee(sys.stdout, buf)
        with contextlib.redirect_stdout(tee):
            file_path = os.path.join( "./", "SubAll.txt")
            vless = pick_random_unique_groups(file_path,"vless://",15)
    except Exception as e:
        tee = Tee(sys.stdout, buf)
        with contextlib.redirect_stdout(tee):
            print("Exception while running: vless", e)
        error_msg = str(e)

    # trojan
    try:
        tee = Tee(sys.stdout, buf)
        with contextlib.redirect_stdout(tee):
            file_path = os.path.join( "./", "SubAll.txt")
            trojan = pick_random_unique_groups(file_path,"trojan://",15)
    except Exception as e:
        tee = Tee(sys.stdout, buf)
        with contextlib.redirect_stdout(tee):
            print("Exception while running trojan:", e)
        error_msg = str(e)

    stdout_contents = buf.getvalue()



    # create a file and add all of these to it
    output_file = "SubDone.txt"
    outfile = os.path.join("./", output_file)
    outfile = [f for f in outfile if os.path.basename(f) != output_file]
    with open(output_file, "a", encoding="utf-8") as outfile:
        for line in vmess + vless + trojan:
            outfile.write(line + "\n")

    return render_template("index.html", stdout=stdout_contents, vmess=vmess , vless=vless, trojan=trojan, error=error_msg)

if __name__ == "__main__":
    clone_or_pull_repo()   
    app.run(host="0.0.0.0", port=9090, debug=True)