"""
Optional Supabase Storage upload — gives salespeople a shareable public link.

Configured entirely via st.secrets (see .streamlit/secrets.toml.example):
    supabase_url    = "https://xxxx.supabase.co"
    supabase_key    = "service-role or anon key with storage write access"
    supabase_bucket = "aoi-toolbox"        # optional, this is the default

If secrets are absent the app silently offers local download only — cloud
save is a graceful add-on, never a hard dependency. Uses the Storage REST
API directly so no supabase SDK is needed.
"""
import re
import datetime

import requests
import streamlit as st

DEFAULT_BUCKET = "aoi-toolbox"


def config():
    """Returns (url, key, bucket) or None when not configured."""
    try:
        url = st.secrets.get("supabase_url")
        key = st.secrets.get("supabase_key")
        bucket = st.secrets.get("supabase_bucket", DEFAULT_BUCKET)
    except Exception:
        return None
    if not url or not key:
        return None
    return url.rstrip("/"), key, bucket


def upload(data: bytes, filename: str, content_type="application/vnd.google-earth.kmz"):
    """Upload bytes to the public bucket; returns the shareable public URL.
    Raises RuntimeError with a user-safe message on failure."""
    cfg = config()
    if not cfg:
        raise RuntimeError("Cloud storage is not configured.")
    url, key, bucket = cfg
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9._\-]+", "_", filename)
    path = f"{stamp}_{safe}"
    try:
        r = requests.post(
            f"{url}/storage/v1/object/{bucket}/{path}",
            headers={"Authorization": f"Bearer {key}", "apikey": key,
                     "Content-Type": content_type, "x-upsert": "true"},
            data=data, timeout=60)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Cloud save failed ({r.status_code}): {r.text[:200]}")
    except requests.RequestException as e:
        raise RuntimeError(f"Cloud save failed — storage unreachable ({e.__class__.__name__}).")
    return f"{url}/storage/v1/object/public/{bucket}/{path}"
