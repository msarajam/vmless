# web_ui.py (refactored & shorter)
from flask import Flask, render_template
from typing import List, Dict, Tuple, Optional
import io, contextlib, os, subprocess, random, sys, base64, json, glob, re, uuid, ipaddress, time, threading, signal, traceback
from urllib.parse import urlparse

# --------------- CONFIG ---------------
REPO_URL = "https://github.com/Epodonios/v2ray-configs.git"
BRANCH = "main"
LOCAL_REPO_PATH = "./vpn_repo"
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$")
_COOLDOWN = 600
_lock = threading.Lock()
_last_clone = 0.0

INTERVAL_SECONDS = 3600
_scheduler_thread: Optional[threading.Thread] = None
_scheduler_stop = threading.Event()
_scheduler_started = False
# ---------------------------------------

app = Flask(__name__)

class Tee:
    def __init__(self, *streams): self.streams = streams
    def write(self, data):
        for s in self.streams: s.write(data); s.flush()
    def flush(self): 
        for s in self.streams: s.flush()

def run_command(cmd: str, cwd: Optional[str] = None) -> str:
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
    if r.returncode: raise RuntimeError(f"Command failed: {r.stderr.strip()}")
    return r.stdout.strip()

def combine_all(pattern: str = LOCAL_REPO_PATH + "/Sub*.txt", out: str = "SubAll.txt"):
    files = sorted(f for f in glob.glob(pattern) if os.path.basename(f) != out)
    with open(out, "w", encoding="utf-8") as o:
        for p in files:
            with open(p, "r", encoding="utf-8") as inf: o.write(inf.read() + "\n")

def remove_duplicates(all_path: str = "SubAll.txt", done_path: str = "SubDone.txt"):
    if not os.path.exists(done_path): open(done_path, "w", encoding="utf-8").close(); return
    if not os.path.exists(all_path): return
    with open(done_path, "r", encoding="utf-8") as f: done = {l.strip() for l in f}
    with open(all_path, "r", encoding="utf-8") as f: all_lines = f.readlines()
    if len(done) > (len(all_lines) / 20):
        os.remove(done_path)
        return
    filtered = [ln for ln in all_lines if ln.strip() not in done]
    with open(all_path, "w", encoding="utf-8") as f: f.writelines(filtered)

def can_clone() -> bool:
    global _last_clone
    with _lock:
        now = time.time()
        if now - _last_clone >= _COOLDOWN:
            _last_clone = now
            return True
        return False

def clone_or_pull_repo() -> Dict[str,str]:
    try:
        if not can_clone(): 
            return {"status":"error","message":"Rate limited"}
        if not os.path.exists(LOCAL_REPO_PATH):
            run_command(f"git clone --depth 1 -b {BRANCH} {REPO_URL} {LOCAL_REPO_PATH}")
            if os.path.exists("SubAll.txt"): os.remove("SubAll.txt")
        else:
            run_command("git fetch", cwd=LOCAL_REPO_PATH)
            run_command(f"git checkout {BRANCH}", cwd=LOCAL_REPO_PATH)
            run_command("git pull", cwd=LOCAL_REPO_PATH)
        combine_all()
        return {"status":"ok"}
    except Exception as e:
        traceback.print_exc()
        return {"status":"error","message": str(e)}

def _scheduler_loop(interval:int, stop_event: threading.Event):
    try:
        print("Scheduler initial run:", clone_or_pull_repo())
    except Exception:
        traceback.print_exc()
    while not stop_event.wait(interval):
        try:
            print("Scheduled run:", clone_or_pull_repo())
        except Exception:
            traceback.print_exc()
    print("Scheduler stopped.")

def start_scheduler(interval: int = INTERVAL_SECONDS):
    global _scheduler_thread, _scheduler_started
    if _scheduler_started: return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, args=(interval,_scheduler_stop), daemon=True)
    _scheduler_thread.start(); _scheduler_started = True

def stop_scheduler():
    global _scheduler_started
    _scheduler_stop.set(); _scheduler_started = False
    if _scheduler_thread:
        _scheduler_thread.join(timeout=3)
        print("Scheduler thread join attempted.")

# ---------- helpers & validators ----------
def read_lines(path: str) -> List[str]:
    with open(path,"r",encoding="utf-8") as f: return [ln.strip() for ln in f if ln.strip()]

def group_by_key(lines: List[str], scheme: str="") -> Dict[str,List[str]]:
    g: Dict[str,List[str]] = {}
    for ln in lines:
        if not ln.lower().startswith(scheme): continue
        body = ln[len(scheme):]
        key = body[:6] if len(body) >= 6 else body
        g.setdefault(key,[]).append(ln)
    return g

def is_uuid(v: str) -> bool:
    try: uuid.UUID(v); return True
    except: return False

def is_host_valid(h: str) -> bool:
    if not h: return False
    try: ipaddress.ip_address(h); return True
    except: pass
    if h.startswith('[') and h.endswith(']'):
        try: ipaddress.ip_address(h[1:-1]); return True
        except: pass
    return bool(DOMAIN_RE.match(h))

def is_port_valid(p: str) -> bool:
    try: n = int(p); return 1 <= n <= 65535
    except: return False

def decode_b64_padded(s: str) -> bytes:
    s = s.strip().replace('-','+').replace('_','/')
    if m := len(s) % 4: s += '=' * (4 - m)
    return base64.b64decode(s)

def validate_vmess(uri: str) -> Tuple[bool,str]:
    payload = (uri[len("vmess://"): ] if uri.startswith("vmess://") else urlparse(uri).path).split('#',1)[0].strip()
    if not payload: return False, "empty"
    try: raw = decode_b64_padded(payload)
    except Exception as e: return False, f"b64: {e}"
    try: j = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as e: return False, f"json: {e}"
    if not isinstance(j, dict): return False, "not object"
    for k in ("add","port","id"):
        if k not in j or j[k] in (None,""): return False, f"missing {k}"
    if not is_host_valid(str(j["add"])): return False, "invalid host"
    if not is_port_valid(str(j["port"])): return False, "invalid port"
    if not is_uuid(str(j["id"])): return False, "invalid uuid"
    return True, "ok"

def validate_scheme_based(uri: str, scheme: str) -> Tuple[bool,str]:
    p = urlparse(uri)
    if p.scheme.lower() != scheme: return False, f"scheme not {scheme}"
    user, host, port = p.username, p.hostname, p.port
    if scheme == "vless" and (not user or not is_uuid(user) or not host or not is_host_valid(host) or port is None or not is_port_valid(str(port))):
        return False, "invalid vless"
    if scheme == "trojan" and (not user or not host or not is_host_valid(host) or port is None or not is_port_valid(str(port))):
        return False, "invalid trojan"
    return True, "ok"

def pick_random_unique_groups(fn: str, scheme: str, count: int = 15) -> List[str]:
    if not os.path.isfile(fn): raise FileNotFoundError(fn)
    lines = read_lines(fn)
    groups = group_by_key(lines, scheme)
    keys = list(groups.keys()); random.shuffle(keys)
    sel: List[str] = []
    for k in keys:
        if len(sel) >= count: break
        size = len(groups[k])
        thresholds = [(2,1),(10,2),(100,3),(300,5)]
        to_add = sum(a for lim,a in thresholds if size > lim)
        for _ in range(to_add):
            if len(sel) >= count: break
            choice = random.choice(groups[k])
            valid, _ = (validate_vmess(choice) if scheme=="vmess" or scheme=="vmess://" else validate_scheme_based(choice, scheme.rstrip(":/")))
            if not valid: continue
            sel.append(choice)
    return sel

# -------------------- Flask route --------------------
@app.route("/")
def index():
    remove_duplicates()
    buf = io.StringIO()
    vmess = vless = []
    error: Optional[str] = None
    for scheme in ("vmess://", "vless://"):
        try:
            tee = Tee(sys.stdout, buf)
            with contextlib.redirect_stdout(tee):
                file_path = os.path.join("./", "SubAll.txt")
                if scheme.startswith("vmess"):
                    vmess = pick_random_unique_groups(file_path, "vmess://", 15)
                else:
                    vless = pick_random_unique_groups(file_path, "vless://", 15)
        except Exception as e:
            with contextlib.redirect_stdout(Tee(sys.stdout, buf)): print(f"Exception for {scheme}:", e)
            error = str(e)
    stdout_contents = buf.getvalue()
    with open("SubDone.txt", "a", encoding="utf-8") as out:
        for ln in vmess + vless: out.write(ln + "\n")
    return render_template("index.html", stdout=stdout_contents, vmess=vmess, vless=vless, error=error)

def _handle_exit(signum, frame):
    print("Signal received, stopping scheduler...")
    stop_scheduler()

signal.signal(signal.SIGINT, _handle_exit)
signal.signal(signal.SIGTERM, _handle_exit)

if __name__ == "__main__":
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_scheduler()
    app.run(host="0.0.0.0", port=9090, debug=True)