"""Create two screenshot builds and submit them to the artifact pipeline."""

from __future__ import annotations

import json
import os
import time
from io import BytesIO
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageDraw

BASE_URL = os.getenv("TRACEHARBOR_URL", "http://127.0.0.1:8080")
API_KEY = os.getenv("TRACEHARBOR_API_KEY", "dev-key")
PROJECT = "snapshot-demo"


def screenshot(label: str, accent: str) -> bytes:
    image = Image.new("RGB", (640, 360), "#10141b")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((44, 44, 596, 316), radius=20, fill="#1c2430", outline="#394657")
    draw.text((78, 82), "TraceHarbor Snapshot", fill="#eef4fb")
    draw.text((78, 126), label, fill="#9eabb9")
    draw.rounded_rectangle((78, 238, 250, 282), radius=10, fill=accent)
    draw.text((110, 252), "Continue", fill="#071b14")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def archive(version: int) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as bundle:
        if version == 1:
            bundle.writestr("ios/home.png", screenshot("Baseline checkout", "#7af0ba"))
            bundle.writestr("ios/cart.png", screenshot("Cart with two items", "#7af0ba"))
        else:
            bundle.writestr("ios/home.png", screenshot("Updated checkout", "#f6c85f"))
            bundle.writestr("ios/profile.png", screenshot("New profile screen", "#7af0ba"))
    return output.getvalue()


def request_json(path: str) -> dict:
    with urlopen(BASE_URL + path, timeout=5) as response:
        return json.loads(response.read())


def upload(payload: bytes, key: str) -> dict:
    request = Request(
        f"{BASE_URL}/api/artifacts/snapshots?project={PROJECT}",
        data=payload,
        headers={
            "Content-Type": "application/zip",
            "X-API-Key": API_KEY,
            "X-Idempotency-Key": key,
        },
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def wait_for(job_id: str) -> dict:
    for _ in range(100):
        job = request_json(f"/api/jobs/{job_id}")
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.1)
    raise TimeoutError("analysis did not finish in time")


def main() -> None:
    baseline = upload(archive(1), "snapshot-demo-baseline-v1")
    wait_for(baseline["job_id"])
    changed = upload(archive(2), "snapshot-demo-change-v2")
    job = wait_for(changed["job_id"])
    build = request_json(f"/api/builds/{changed['build_id']}")
    print(json.dumps({"job": job, "summary": build["summary"], "diffs": build["diffs"]}, indent=2))
    print(f"Open {BASE_URL} and select project '{PROJECT}'.")


if __name__ == "__main__":
    main()
