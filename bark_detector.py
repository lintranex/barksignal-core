#!/usr/bin/env python3

import argparse
import configparser
import io
import csv
import time
import uuid
import urllib.request
import socket
import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
import requests
from tflite_runtime.interpreter import Interpreter

LABELS_URL_DEFAULT = "https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv"

@dataclass
class Cfg:
    model_path: str
    dog_id: str
    webhook_url_template: str

    input_device: int
    mic_gain: float

    target_sr: int
    frame_len: int
    block_sec: float

    thresh: float
    debounce_k: int
    debounce_n: int

    heartbeat_sec: float
    bark_end_sec: float
    status_heartbeat_sec: float

    http_timeout: float
    user_agent: str

    labels_url: str
    send_session_fields: bool
    print_only_hits: bool
    heartbeat_url_template: str
    api_token: str
    heartbeat_state_path: str

def load_config(path: str) -> Cfg:
    p = Path(path).expanduser()
    cp = configparser.ConfigParser()
    cp.read(p)

    def req(section: str, key: str) -> str:
        if section not in cp or key not in cp[section]:
            raise KeyError(f"Missing [{section}] {key} in {p}")
        return cp[section][key]

    model_path = req("barksignal", "model_path")
    dog_id = req("barksignal", "dog_id")
    webhook_url_template = req("barksignal", "webhook_url_template")

    input_device = int(cp.get("audio", "input_device", fallback="1"))
    mic_gain = float(cp.get("audio", "mic_gain", fallback="1.0"))
    target_sr = int(cp.get("audio", "target_sr", fallback="16000"))
    frame_len = int(cp.get("audio", "frame_len", fallback="15600"))
    block_sec = float(cp.get("audio", "block_sec", fallback="0.25"))

    thresh = float(cp.get("detect", "thresh", fallback="0.30"))
    debounce_k = int(cp.get("detect", "debounce_k", fallback="2"))
    debounce_n = int(cp.get("detect", "debounce_n", fallback="3"))

    heartbeat_sec = float(cp.get("session", "heartbeat_sec", fallback="20.0"))
    bark_end_sec = float(cp.get("session", "bark_end_sec", fallback="3.0"))
    status_heartbeat_sec = float(cp.get("heartbeat", "interval_sec", fallback="60.0"))

    http_timeout = float(cp.get("http", "timeout_sec", fallback="3.0"))
    user_agent = cp.get("http", "user_agent", fallback="BarkSignal-YAMNet-RPi/1.0")

    labels_url = cp.get("yamnet", "labels_url", fallback=LABELS_URL_DEFAULT)

    send_session_fields = cp.getboolean("barksignal", "send_session_fields", fallback=False)
    print_only_hits = cp.getboolean("debug", "print_only_hits", fallback=False)
    heartbeat_url_template = cp.get(
        "heartbeat",
        "url",
        fallback="https://www.barksignal.com/api/heartbeat",
    ).strip()
    api_token = cp.get("barksignal", "api_token", fallback="").strip()
    heartbeat_state_path = cp.get(
        "heartbeat",
        "state_path",
        fallback="/home/barksignal/barksignal-data/last_heartbeat.json",
    ).strip()

    return Cfg(
        model_path=model_path,
        dog_id=dog_id,
        webhook_url_template=webhook_url_template,
        input_device=input_device,
        mic_gain=mic_gain,
        target_sr=target_sr,
        frame_len=frame_len,
        block_sec=block_sec,
        thresh=thresh,
        debounce_k=debounce_k,
        debounce_n=debounce_n,
        heartbeat_sec=heartbeat_sec,
        bark_end_sec=bark_end_sec,
        status_heartbeat_sec=status_heartbeat_sec,
        http_timeout=http_timeout,
        user_agent=user_agent,
        labels_url=labels_url,
        send_session_fields=send_session_fields,
        print_only_hits=print_only_hits,
        heartbeat_url_template=heartbeat_url_template,
        api_token=api_token,
        heartbeat_state_path=heartbeat_state_path,
    )

def load_labels(labels_url: str):
    with urllib.request.urlopen(labels_url) as r:
        text = r.read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    labels = [row["display_name"] for row in rows]
    if len(labels) != 521:
        raise RuntimeError(f"Expected 521 labels, got {len(labels)}")
    return labels

def clamp01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))

def score_to_intensity(score: float) -> int:
    s = clamp01(score)
    return min(10, max(1, int(round(s * 10))))

def webhook_url(cfg: Cfg) -> str:
    return cfg.webhook_url_template.format(dog_id=cfg.dog_id)

def heartbeat_url(cfg: Cfg) -> str:
    return cfg.heartbeat_url_template.format(dog_id=cfg.dog_id)

def auth_headers(cfg: Cfg) -> dict:
    headers = {
        "User-Agent": cfg.user_agent,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if cfg.api_token:
        headers["Authorization"] = f"Bearer {cfg.api_token}"
    return headers

def send_event(cfg: Cfg, intensity: int, *, session_id: Optional[str]=None, event_type: Optional[str]=None, debug: bool=False) -> bool:
    url = webhook_url(cfg)
    payload = {
        "dog_id": cfg.dog_id,
        "intensity": int(intensity),
        "triggered_at": datetime.now(timezone.utc).isoformat(),
    }
    if cfg.send_session_fields:
        if session_id: payload["session_id"] = session_id
        if event_type: payload["type"] = event_type

    try:
        r = requests.post(
            url,
            json=payload,
            timeout=cfg.http_timeout,
            headers=auth_headers(cfg),
        )
        ok = 200 <= r.status_code < 300
        if debug:
            print(f"  -> POST {url} status={r.status_code} ok={ok} payload={payload}")
        return ok
    except Exception as e:
        if debug:
            print(f"  -> POST ERROR: {e} payload={payload}")
        return False

def send_heartbeat(cfg: Cfg, *, session_active: bool, debug: bool=False) -> bool:
    url = heartbeat_url(cfg)
    if not url:
        return False
    sent_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "dog_id": cfg.dog_id,
        "armed": True,
        "session_active": bool(session_active),
        "hostname": socket.gethostname(),
        "sent_at": sent_at,
    }
    try:
        r = requests.post(
            url,
            json=payload,
            timeout=cfg.http_timeout,
            headers=auth_headers(cfg),
        )
        ok = 200 <= r.status_code < 300
        if ok:
            record_heartbeat_state(cfg, sent_at, session_active)
        if debug:
            print(f"  -> POST {url} status={r.status_code} ok={ok} payload={payload}")
        return ok
    except Exception as e:
        if debug:
            print(f"  -> POST ERROR: {e} payload={payload}")
        return False

def record_heartbeat_state(cfg: Cfg, sent_at: str, session_active: bool) -> None:
    if not cfg.heartbeat_state_path:
        return
    try:
        p = Path(cfg.heartbeat_state_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "last_ok_at": sent_at,
            "dog_id": cfg.dog_id,
            "session_active": bool(session_active),
        }))
    except Exception:
        pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.ini")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    debug = bool(args.debug)

    cfg = load_config(args.config)
    if cfg.dog_id.upper() == "DEMO":
        # Still run (useful for tuning), but won't send events
        pass

    labels = load_labels(cfg.labels_url)
    idx_bark = labels.index("Bark")
    idx_dog  = labels.index("Dog")
    idx_pets = labels.index("Domestic animals, pets")
    idx_anml = labels.index("Animal")

    itp = Interpreter(model_path=str(Path(cfg.model_path).expanduser()))
    itp.allocate_tensors()
    inp = itp.get_input_details()[0]
    out = itp.get_output_details()[0]
    in_shape = tuple(inp["shape"])
    if in_shape not in [(cfg.frame_len,), (1, cfg.frame_len)]:
        raise RuntimeError(f"Unexpected input shape {inp['shape']}")

    if debug:
        print("✅ Detector started")
        print(f"dog_id={cfg.dog_id}")
        print(f"webhook={webhook_url(cfg)}")
        print(f"Input: {inp['shape']} Output: {out['shape']}")
        print(f"THRESH={cfg.thresh} debounce={cfg.debounce_k}/{cfg.debounce_n} heartbeat={cfg.heartbeat_sec}s end={cfg.bark_end_sec}s")
        print(f"STATUS_HEARTBEAT={cfg.status_heartbeat_sec}s heartbeat_url={heartbeat_url(cfg)}")
        print(f"INPUT_DEVICE={cfg.input_device} MIC_GAIN={cfg.mic_gain}")

    info = sd.query_devices(cfg.input_device, "input")
    in_sr = int(info["default_samplerate"])
    ring = np.zeros(cfg.frame_len, dtype=np.float32)
    hits = deque(maxlen=cfg.debounce_n)

    in_session = False
    session_id = None
    last_hit_ts = 0.0
    last_send_ts = 0.0
    last_status_ts = 0.0
    window_peak = 0.0
    window_cnt = 0

    block_in = max(1, int(in_sr * cfg.block_sec))

    def update_ring(new_16k: np.ndarray):
        nonlocal ring
        n = len(new_16k)
        if n >= cfg.frame_len:
            ring = new_16k[-cfg.frame_len:].astype(np.float32)
        else:
            ring = np.roll(ring, -n)
            ring[-n:] = new_16k.astype(np.float32)

    with sd.InputStream(device=cfg.input_device, samplerate=in_sr, channels=1, dtype="float32") as stream:
        while True:
            audio, _ = stream.read(block_in)
            audio = audio.reshape(-1)
            if cfg.mic_gain != 1.0:
                audio = np.clip(audio * cfg.mic_gain, -1.0, 1.0)

            if in_sr != cfg.target_sr:
                audio_16k = resample_poly(audio, cfg.target_sr, in_sr).astype(np.float32)
            else:
                audio_16k = audio.astype(np.float32)

            update_ring(audio_16k)

            x = ring.astype(np.float32)
            if in_shape == (1, cfg.frame_len):
                x = x.reshape(1, cfg.frame_len)

            itp.set_tensor(inp["index"], x)
            itp.invoke()
            scores = itp.get_tensor(out["index"])[0]

            s_bark = float(scores[idx_bark])
            s_dog  = float(scores[idx_dog])
            s_pets = float(scores[idx_pets])
            s_anml = float(scores[idx_anml])

            signal = max(
                s_bark,
                0.90 * s_dog,
                0.60 * s_pets,
                0.40 * s_anml,
            )
            intensity = score_to_intensity(signal)

            top_i = int(np.argmax(scores))
            top_name = labels[top_i]
            top_val = float(scores[top_i])

            is_hit = (signal >= cfg.thresh) and (top_name != "Silence")
            hits.append(1 if is_hit else 0)
            hit_count = sum(hits)
            debounced = hit_count >= cfg.debounce_k
            now = time.time()

            if debug:
                if (not cfg.print_only_hits) or debounced or in_session:
                    print(f"{time.strftime('%H:%M:%S')} bark={s_bark:.3f} dog={s_dog:.3f} pets={s_pets:.3f} anml={s_anml:.3f} sig={signal:.3f} int={intensity:2d} top={top_name}({top_val:.3f}) hits={hit_count}/{cfg.debounce_n}")

            if debounced:
                last_hit_ts = now
                window_peak = max(window_peak, signal)
                window_cnt += 1

            if not in_session:
                if debounced and cfg.dog_id.upper() != "DEMO":
                    in_session = True
                    session_id = str(uuid.uuid4())
                    start_int = score_to_intensity(window_peak)
                    send_event(cfg, start_int, session_id=session_id, event_type="start", debug=debug)
                    last_send_ts = now
                    window_peak = 0.0
                    window_cnt = 0
            else:
                if debounced and (now - last_send_ts) >= cfg.heartbeat_sec:
                    hb_int = score_to_intensity(window_peak)
                    send_event(cfg, hb_int, session_id=session_id, event_type="heartbeat", debug=debug)
                    last_send_ts = now
                    window_peak = 0.0
                    window_cnt = 0

                if (now - last_hit_ts) >= cfg.bark_end_sec:
                    end_int = score_to_intensity(window_peak) if window_cnt > 0 else 1
                    send_event(cfg, end_int, session_id=session_id, event_type="end", debug=debug)
                    in_session = False
                    session_id = None
                    hits.clear()
                    window_peak = 0.0
                    window_cnt = 0

            if cfg.status_heartbeat_sec > 0 and cfg.dog_id.upper() != "DEMO":
                if (now - last_status_ts) >= cfg.status_heartbeat_sec:
                    send_heartbeat(cfg, session_active=in_session, debug=debug)
                    last_status_ts = now

if __name__ == "__main__":
    main()
