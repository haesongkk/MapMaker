"""Load this checkout's private deployment settings without logging credentials."""

import json
import os

from .runtime_paths import ROOT


def load_settings():
    settings = ROOT / ".runtime/runpod-settings.json"
    allowed = {
        "RUNPOD_ENDPOINT_ID", "MAPMAKER_S3_BUCKET", "MAPMAKER_S3_ENDPOINT",
        "AWS_DEFAULT_REGION", "MAPMAKER_JOB_TIMEOUT",
    }
    if settings.is_file():
        values = json.loads(settings.read_text(encoding="utf-8-sig"))
        for key in allowed:
            if key in values:
                os.environ.setdefault(key, str(values[key]))
    credentials = ROOT / ".runtime/runpod-s3.credentials"
    if credentials.is_file():
        os.environ.setdefault("AWS_SHARED_CREDENTIALS_FILE", str(credentials))
    api_key = ROOT / ".runtime/runpod-api.key"
    if "RUNPOD_API_KEY" not in os.environ and api_key.is_file():
        os.environ["RUNPOD_API_KEY"] = api_key.read_text(encoding="utf-8-sig").strip()
