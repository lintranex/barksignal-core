#!/usr/bin/env python3

import os
import subprocess
import configparser
from pathlib import Path

import requests
from flask import Flask, request, redirect, session, render_template_string, Response

app = Flask(__name__)
app.secret_key = os.environ.get("PORTAL_SECRET", "barksignal-portal-change-me")

CONFIG_PATH = Path("/home/barksignal/barksignal/config.ini")
FLAG_WIFI = Path("/home/barksignal/barksignal/.wifi_configured")
FLAG_DOG  = Path("/home/barksignal/barksignal/.dog_configured")

CSS = """
body{font-family:system-ui,Arial,sans-serif;max-width:860px;margin:22px auto;padding:0 14px}
h1{margin:0 0 6px}
.card{border:1px solid #e5e5e5;border-radius:14px;padding:14px;margin:12px 0}
label{display:block;margin-top:10px;font-weight:700}
input,select{width:100%;padding:10px;margin-top:6px}
button{margin-top:14px;padding:10px 12px;font-weight:800;cursor:pointer}
.small{color:#555;font-size:13px;line-height:1.45}
.err{background:#ffe8e8;border:1px solid #ffb3b3;padding:10px;border-radius:12px;margin-top:10px}
.ok{background:#eefbe8;border:1px solid #b6f0a2;padding:10px;border-radius:12px;margin-top:10px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:900px){.row{grid-template-columns:1fr}}
code{background:#f3f3f3;padding:2px 6px;border-radius:8px}
"""

TPL = """
<!doctype html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>BarkSignal Setup</title><style>{{css}}</style></head><body>
<h1>BarkSignal Setup</h1>

<div class="card">
  <h2>1) WLAN konfigurieren</h2>
  <p class="small">SSID wählen oder manuell eingeben. Danach rebootet der Pi und verbindet sich ins WLAN.</p>
  {% if wifi_msg %}<div class="ok">{{wifi_msg}}</div>{% endif %}
  {% if wifi_err %}<div class="err">{{wifi_err}}</div>{% endif %}

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
</div>

<div class="card">
  <h2>2) BarkSignal Login (Sanctum Token)</h2>
  <p class="small">Login funktioniert erst, wenn der Pi Internet hat.</p>

  {% if login_err %}<div class="err">{{login_err}}</div>{% endif %}
  {% if token_ok %}<div class="ok">{{token_ok}}</div>{% endif %}

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
</div>

{% if token %}
<div class="card">
  <h2>3) Hund auswählen oder anlegen</h2>
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

<p class="small">Tipp: Wenn Captive Portal nicht automatisch aufgeht, öffne z.B. <code>http://10.42.0.1</code></p>
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
    if not ssid:
        session["wifi_err"] = "Bitte SSID auswählen oder eingeben."
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
    session["wifi_msg"] = f"WLAN gespeichert ✅ (SSID: {ssid}). Reboot in 5 Sekunden…"

    subprocess.Popen(["bash","-lc","sleep 5; reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return redirect("/")

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
