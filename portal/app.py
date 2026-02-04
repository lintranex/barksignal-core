#!/usr/bin/env python3

import os
import subprocess
import configparser
from pathlib import Path

import requests
from flask import Flask, request, redirect, session, render_template_string, Response, send_file

app = Flask(__name__)
app.secret_key = os.environ.get("PORTAL_SECRET", "barksignal-portal-change-me")

CONFIG_PATH = Path("/home/barksignal/barksignal/config.ini")
FLAG_WIFI = Path("/home/barksignal/barksignal/.wifi_configured")
FLAG_DOG  = Path("/home/barksignal/barksignal/.dog_configured")

CSS = """
:root{
  --skyTop:#0b1a2b;
  --skyBottom:#07121f;
  --accent:#ffcc00;
  --card-bg:rgba(8,12,22,.58);
  --card-border:rgba(255,255,255,.12);
  --text:#ffffff;
  --text-dim:rgba(255,255,255,.72);
  --ok:#40d17a;
  --warn:#ffcc00;
  --err:#ff6a6a;
}
*{box-sizing:border-box}
html{
  background: radial-gradient(900px 600px at 70% 18%, rgba(255, 255, 255, .08), transparent 58%),
              radial-gradient(900px 600px at 25% 10%, rgba(255, 90, 60, .06), transparent 55%),
              linear-gradient(180deg, var(--skyTop), var(--skyBottom));
  background-attachment: fixed;
}
body{
  color:var(--text);
  font-family:ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  max-width:980px;
  margin:22px auto;
  padding:0 18px 48px;
}
h1,h2,h3{margin:0}
a{color:var(--accent)}
.card{
  background:var(--card-bg);
  border:1px solid var(--card-border);
  border-radius:18px;
  padding:18px;
  margin:14px 0;
  box-shadow:0 20px 60px rgba(0,0,0,.22);
  backdrop-filter: blur(4px);
}
.step-head{
  display:flex;
  align-items:center;
  gap:12px;
  margin-bottom:8px;
}
.step-num{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:30px;height:30px;
  border-radius:999px;
  background:rgba(255,255,255,.1);
  border:1px solid var(--card-border);
  font-weight:800;
}
.status{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding:4px 10px;
  border-radius:999px;
  font-size:12px;
  font-weight:800;
  border:1px solid transparent;
}
.status.ok{color:#0b1a2b;background:var(--ok);border-color:rgba(255,255,255,.2)}
.status.warn{color:#2a1c00;background:var(--warn);border-color:rgba(255,255,255,.2)}
.status.muted{color:var(--text-dim);background:rgba(255,255,255,.08);border-color:var(--card-border)}
.small{color:var(--text-dim);font-size:13px;line-height:1.45}
.err{
  background:rgba(255,80,80,.14);
  border:1px solid rgba(255,106,106,.45);
  padding:10px;border-radius:12px;margin-top:10px
}
.ok{
  background:rgba(64,209,122,.14);
  border:1px solid rgba(64,209,122,.45);
  padding:10px;border-radius:12px;margin-top:10px
}
.warnbox{
  background:rgba(255,204,0,.14);
  border:1px solid rgba(255,204,0,.45);
  padding:10px;border-radius:12px;margin-top:10px
}
label{display:block;margin-top:10px;font-weight:700}
input,select{
  width:100%;
  padding:10px;
  margin-top:6px;
  color:var(--text);
  background:rgba(255,255,255,.08);
  border:1px solid var(--card-border);
  border-radius:10px;
}
button{
  margin-top:14px;
  padding:10px 14px;
  font-weight:900;
  cursor:pointer;
  border-radius:10px;
  border:1px solid rgba(0,0,0,.15);
  background:var(--accent);
  color:#2a1c00;
}
button.secondary{
  background:rgba(255,255,255,.1);
  color:var(--text);
  border:1px solid var(--card-border);
}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:900px){.row{grid-template-columns:1fr}}
code{background:rgba(255,255,255,.12);padding:2px 6px;border-radius:8px}
.brand{display:flex;justify-content:center}
header{margin-bottom:3em;margin-top:2em;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:12px}
.countdown{font-weight:900;color:var(--accent)}
.muted{color:var(--text-dim)}
"""

TPL = """
<!doctype html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>BarkSignal Setup</title>
<link rel="icon" type="image/png" href="/images/barksignal.png">
<style>{{css}}</style></head><body>
<header>
  <div></div>
  <div class="brand">
    <div>
      <img src="/images/barksignal.png" width="200" alt="BarkSignal">
    </div>
  </div>
  <div></div>
</header>

<div class="card">
  <div class="step-head">
    <span class="step-num">1</span>
    <div>
      <h2>{% if wifi_configured %}WLAN Status{% else %}WLAN konfigurieren{% endif %}</h2>
      <div class="small">Gerät ins Heimnetz bringen</div>
    </div>
    <div style="margin-left:auto">
      {% if wifi_configured and internet_ok %}
        <span class="status ok">✓ WLAN konfiguriert · Internet ok</span>
      {% elif wifi_configured and not internet_ok %}
        <span class="status warn">! WLAN ok · kein Internet</span>
      {% else %}
        <span class="status muted">offen</span>
      {% endif %}
    </div>
  </div>

  {% if wifi_msg %}<div class="ok">{{wifi_msg}}</div>{% endif %}
  {% if wifi_err %}<div class="err">{{wifi_err}}</div>{% endif %}
  {% if wifi_countdown %}
    <div class="warnbox">
      Bitte WLAN wechseln. Weiterleitung zu <code>http://barksignal.local:8080</code> in
      <span class="countdown" id="countdown">{{wifi_countdown}}</span> Sekunden.
    </div>
  {% endif %}

  {% if not wifi_configured %}
    <p class="small">SSID wählen oder manuell eingeben. Danach rebootet der Pi und verbindet sich ins WLAN.</p>
    <form method="post" action="/wifi">
      <label>SSID (Dropdown)</label>
      <select name="ssid_select">
        <option value="">— auswählen —</option>
        {% for s in ssids %}<option value="{{s}}">{{s}}</option>{% endfor %}
      </select>

      <label>SSID (manuell)</label>
      <input name="ssid_manual" placeholder="Dein WLAN Name">

      <label>WLAN Passwort</label>
      <input name="psk" type="password" required>

      <button type="submit">WLAN speichern</button>
    </form>
    <p class="small">Nach dem Reboot: im selben WLAN <code>http://barksignal.local:8080</code> öffnen (oder IP).</p>
  {% else %}
    {% if not internet_ok %}
      <div class="warnbox">WLAN ist gespeichert, aber Internet wurde nicht gefunden. Bitte Router/WLAN prüfen.</div>
    {% endif %}
    <form method="post" action="/reset-wifi">
      <button type="submit" class="secondary">WLAN‑Konfiguration löschen</button>
    </form>
  {% endif %}
</div>

<div class="card">
  <div class="step-head">
    <span class="step-num">2</span>
    <div>
      <h2>BarkSignal Login</h2>
      <div class="small">Account prüfen und Token holen</div>
    </div>
    <div style="margin-left:auto">
      {% if token %}
        <span class="status ok">✓ angemeldet</span>
      {% elif wifi_configured and internet_ok %}
        <span class="status muted">bereit</span>
      {% else %}
        <span class="status warn">wartet auf Internet</span>
      {% endif %}
    </div>
  </div>
  <p class="small">Login funktioniert erst, wenn der Pi Internet hat.</p>

  {% if login_err %}<div class="err">{{login_err}}</div>{% endif %}
  {% if token_ok %}<div class="ok">{{token_ok}}</div>{% endif %}

  {% if not wifi_configured %}
    <div class="warnbox">Bitte zuerst WLAN konfigurieren.</div>
  {% elif not internet_ok %}
    <div class="warnbox">WLAN ist konfiguriert, aber kein Internet. Login ist derzeit nicht möglich.</div>
  {% else %}
    {% if not token %}
      <form method="post" action="/login">
        <div class="row">
          <div>
            <label>E-Mail</label>
            <input name="email" required>
          </div>
          <div>
            <label>Passwort</label>
            <input name="password" type="password" required>
          </div>
        </div>
        <button type="submit">Anmelden</button>
      </form>
    {% else %}
      <form method="post" action="/logout"><button type="submit">Abmelden</button></form>
    {% endif %}
  {% endif %}
</div>

{% if token %}
<div class="card">
  <div class="step-head">
    <span class="step-num">3</span>
    <div>
      <h2>Hund auswählen oder anlegen</h2>
      <div class="small">DOG_ID konfigurieren</div>
    </div>
    <div style="margin-left:auto">
      <span class="status muted">optional</span>
    </div>
  </div>
  {% if dog_err %}<div class="err">{{dog_err}}</div>{% endif %}
  {% if dog_ok %}<div class="ok">{{dog_ok}}</div>{% endif %}

  <form method="post" action="/select-dog">
    <label>Hund auswählen</label>
    <select name="dog_id" required>
      {% for d in dogs %}
        <option value="{{d['id']}}">{{d.get('name','(ohne Name)')}} — {{d['id']}}</option>
      {% endfor %}
    </select>
    <button type="submit">DOG_ID setzen</button>
  </form>

  <hr>

  <form method="post" action="/create-dog">
    <label>Neuen Hund anlegen (Name optional)</label>
    <input name="name" placeholder="z.B. Dorli">
    <button type="submit">Hund anlegen</button>
  </form>

  <p class="small">Webhook-Base ist fix. Es wird nur <code>dog_id</code> gesetzt.</p>
</div>
{% endif %}

<p class="small">Tipp: Wenn Captive Portal nicht automatisch aufgeht, öffne <code>http://10.42.0.1</code></p>

{% if wifi_countdown %}
<script>
  (function(){
    var el = document.getElementById("countdown");
    if (!el) return;
    var remaining = parseInt(el.textContent, 10) || 0;
    var target = "http://barksignal.local:8080";
    var tick = function(){
      remaining -= 1;
      if (remaining <= 0){
        el.textContent = "0";
        window.location.href = target;
        return;
      }
      el.textContent = String(remaining);
      setTimeout(tick, 1000);
    };
    setTimeout(tick, 1000);
  })();
</script>
{% endif %}
</body></html>
"""

def read_cfg():
    cp = configparser.ConfigParser()
    cp.read(CONFIG_PATH)
    def g(s,k,default=""):
        return cp.get(s,k,fallback=default)
    return {
        "api_base": g("barksignal","api_base","https://www.barksignal.com"),
        "login_path": g("barksignal","api_login_path","/api/login"),
        "dogs_path": g("barksignal","api_dogs_path","/api/dogs"),
        "create_path": g("barksignal","api_dog_create_path","/api/dogs"),
    }

def write_dog_id(dog_id: str):
    cp = configparser.ConfigParser()
    cp.read(CONFIG_PATH)
    if "barksignal" not in cp: cp["barksignal"] = {}
    cp["barksignal"]["dog_id"] = dog_id
    with open(CONFIG_PATH, "w") as f:
        cp.write(f)

def scan_ssids():
    try:
        out = subprocess.check_output(["nmcli","-t","-f","SSID","dev","wifi","list"], text=True)
        ssids = sorted({x.strip() for x in out.splitlines() if x.strip()})
        return ssids[:80] if ssids else []
    except Exception:
        return []

def scan_wifi_details():
    try:
        out = subprocess.check_output(["nmcli","-t","-f","SSID,FREQ,SECURITY","dev","wifi","list"], text=True)
    except Exception:
        return {}
    details = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split(":")
        if len(parts) < 3:
            continue
        ssid = parts[0].strip()
        if not ssid:
            continue
        try:
            freq = int(parts[1])
        except Exception:
            freq = None
        sec = parts[2].strip()
        d = details.setdefault(ssid, {"freqs": [], "secs": []})
        if freq:
            d["freqs"].append(freq)
        if sec:
            d["secs"].append(sec)
    return details

def has_internet(api_base: str) -> bool:
    try:
        r = requests.get(api_base, timeout=2)
        return r.status_code < 500
    except Exception:
        return False

def get_wifi_caps():
    caps = {"supports_5ghz": None, "supports_wpa3": None}
    try:
        out = subprocess.check_output(["iw","list"], text=True)
    except Exception:
        return caps
    freqs = []
    for line in out.splitlines():
        if "MHz" not in line:
            continue
        parts = line.strip().split()
        for p in parts:
            if p.isdigit():
                try:
                    freqs.append(int(p))
                except Exception:
                    pass
                break
    if freqs:
        caps["supports_5ghz"] = any(f >= 5000 for f in freqs)
    caps["supports_wpa3"] = ("SAE" in out) or ("WPA3" in out)
    return caps

def preflight_wifi(ssid: str, psk: str):
    if not ssid:
        return "Bitte SSID auswählen oder eingeben."
    if len(psk or "") < 8:
        return "WLAN Passwort muss mindestens 8 Zeichen lang sein."

    details = scan_wifi_details()
    if ssid not in details:
        return f"SSID '{ssid}' wurde beim Scan nicht gefunden. Bitte SSID prüfen und erneut versuchen."

    freqs = details[ssid].get("freqs", [])
    secs = details[ssid].get("secs", [])
    sec_all = " ".join(secs).upper()

    caps = get_wifi_caps()
    supports_5ghz = caps.get("supports_5ghz")
    supports_wpa3 = caps.get("supports_wpa3")

    if freqs:
        only_5ghz = all(f >= 5000 for f in freqs)
        if only_5ghz and supports_5ghz is False:
            return "SSID scheint nur 5 GHz zu unterstützen, dieses Gerät kann aber kein 5 GHz. Bitte 2.4 GHz aktivieren."

    if sec_all:
        has_wpa3 = ("WPA3" in sec_all) or ("SAE" in sec_all)
        has_wpa2 = ("WPA2" in sec_all) or ("WPA" in sec_all)
        if has_wpa3 and not has_wpa2:
            if supports_wpa3 is False:
                return "SSID nutzt offenbar WPA3-only. Dieses Gerät unterstützt WPA3 nicht. Bitte WPA2/WPA2-Mixed aktivieren."
            if supports_wpa3 is None:
                return "SSID wirkt wie WPA3-only. Gerät-Fähigkeit ist unklar. Bitte WPA2/WPA2-Mixed aktivieren."

    return None

def api_login(api_base: str, login_path: str, email: str, password: str) -> str:
    url = api_base.rstrip("/") + login_path
    r = requests.post(url, json={"email": email, "password": password}, timeout=10)
    r.raise_for_status()
    data = r.json()
    token = data.get("token") or data.get("plainTextToken")
    if not token:
        raise RuntimeError(f"Login response has no token. Keys: {list(data.keys())}")
    return token

def api_get_dogs(api_base: str, dogs_path: str, token: str):
    url = api_base.rstrip("/") + dogs_path
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        return data["data"]
    if isinstance(data, list):
        return data
    raise RuntimeError("Unexpected dogs response")

def api_create_dog(api_base: str, create_path: str, token: str, name: str|None):
    url = api_base.rstrip("/") + create_path
    payload = {}
    if name: payload["name"] = name
    r = requests.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    return r.json()

@app.route("/", methods=["GET"])
def index():
    ssids = scan_ssids()
    cfg = read_cfg()
    wifi_configured = FLAG_WIFI.exists()
    internet_ok = has_internet(cfg["api_base"]) if wifi_configured else False

    token = session.get("token")
    dogs = []
    dog_err = None
    if token:
        try:
            dogs = api_get_dogs(cfg["api_base"], cfg["dogs_path"], token)
        except Exception as e:
            dog_err = str(e)

    return render_template_string(
        TPL,
        css=CSS,
        ssids=ssids,
        wifi_msg=session.pop("wifi_msg", None),
        wifi_err=session.pop("wifi_err", None),
        wifi_countdown=session.pop("wifi_countdown", None),
        wifi_configured=wifi_configured,
        internet_ok=internet_ok,
        login_err=session.pop("login_err", None),
        token_ok=session.pop("token_ok", None),
        dog_ok=session.pop("dog_ok", None),
        dog_err=dog_err,
        token=token,
        dogs=dogs,
    )

@app.route("/wifi", methods=["POST"])
def wifi():
    ssid = (request.form.get("ssid_select","").strip() or request.form.get("ssid_manual","").strip())
    psk = request.form.get("psk","").strip()
    err = preflight_wifi(ssid, psk)
    if err:
        session["wifi_err"] = err
        return redirect("/")

    con = "barksignal-wifi"
    subprocess.run(["nmcli","con","delete",con], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    r1 = subprocess.run(["nmcli","con","add","type","wifi","ifname","wlan0","con-name",con,"ssid",ssid], capture_output=True, text=True)
    if r1.returncode != 0:
        session["wifi_err"] = r1.stderr or r1.stdout or "nmcli failed"
        return redirect("/")
    r2 = subprocess.run(["nmcli","con","modify",con,"wifi-sec.key-mgmt","wpa-psk","wifi-sec.psk",psk], capture_output=True, text=True)
    if r2.returncode != 0:
        session["wifi_err"] = r2.stderr or r2.stdout or "nmcli modify failed"
        return redirect("/")

    subprocess.run(["nmcli","con","modify",con,"connection.autoconnect","yes"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    FLAG_WIFI.write_text("ok")
    session["wifi_msg"] = f"WLAN gespeichert (SSID: {ssid}). Der Pi startet neu."
    session["wifi_countdown"] = 90

    subprocess.Popen(
        ["bash", "-lc", "sleep 5; systemctl reboot || sudo -n /usr/local/sbin/barksignal-reboot.sh"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return redirect("/")

@app.route("/reset-wifi", methods=["POST"])
def reset_wifi():
    try:
        subprocess.run(["nmcli","con","delete","barksignal-wifi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    try:
        if FLAG_WIFI.exists():
            FLAG_WIFI.unlink()
    except Exception:
        pass
    session["wifi_msg"] = "WLAN-Konfiguration gelöscht. Hotspot wird wieder aktiv."
    return redirect("/")

@app.route("/images/barksignal.png")
def brand_image():
    img = Path(__file__).parent / "barksignal.png"
    if not img.exists():
        return Response(status=404)
    return send_file(img, mimetype="image/png")

@app.route("/favicon.ico")
def favicon():
    img = Path(__file__).parent / "barksignal.png"
    if not img.exists():
        return Response(status=404)
    return send_file(img, mimetype="image/png")

@app.route("/login", methods=["POST"])
def login():
    cfg = read_cfg()
    email = request.form.get("email","").strip()
    password = request.form.get("password","").strip()
    try:
        token = api_login(cfg["api_base"], cfg["login_path"], email, password)
        session["token"] = token
        session["token_ok"] = "Login ok ✅"
    except Exception as e:
        session["login_err"] = str(e)
    return redirect("/")

@app.route("/logout", methods=["POST"])
def logout():
    session.pop("token", None)
    return redirect("/")

@app.route("/select-dog", methods=["POST"])
def select_dog():
    dog_id = request.form.get("dog_id","").strip()
    write_dog_id(dog_id)
    FLAG_DOG.write_text("ok")
    session["dog_ok"] = f"DOG_ID gesetzt ✅ ({dog_id}). Detector startet automatisch."
    return redirect("/")

@app.route("/create-dog", methods=["POST"])
def create_dog():
    cfg = read_cfg()
    token = session.get("token")
    if not token:
        session["login_err"] = "Bitte zuerst anmelden."
        return redirect("/")

    name = request.form.get("name","").strip() or None
    try:
        dog = api_create_dog(cfg["api_base"], cfg["create_path"], token, name)
        dog_id = None
        if isinstance(dog, dict):
            dog_id = dog.get("id") or (dog.get("data") or {}).get("id")
        if not dog_id:
            session["login_err"] = "Hund angelegt, aber keine ID im Response gefunden."
            return redirect("/")
        write_dog_id(dog_id)
        FLAG_DOG.write_text("ok")
        session["dog_ok"] = f"Hund angelegt ✅ DOG_ID={dog_id}"
    except Exception as e:
        session["login_err"] = str(e)
    return redirect("/")

# Captive portal probes
@app.route("/generate_204")
@app.route("/hotspot-detect.html")
@app.route("/library/test/success.html")
@app.route("/ncsi.txt")
@app.route("/connecttest.txt")
def captive_probe():
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
