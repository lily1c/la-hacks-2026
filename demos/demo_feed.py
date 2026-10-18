"""Publish random demo alerts to the FireSight API so the dashboard and glasses update live.

    python demos/demo_feed.py                      # local API on :8790
    python demos/demo_feed.py --url https://...    # another backend
    INGEST_TOKEN=... python demos/demo_feed.py     # backend with PUBLIC_DEPLOYMENT=true

Each alert is re-sent every few seconds with a fresh timestamp (alerts expire quickly
by design) and a new random alert is picked every --change seconds. Demo data only.
"""
import argparse
import json
import os
import random
import time
import urllib.request

ALERTS = [
    ("critical", "Fire ahead - move right now", [
        "Take the down-right path to creek", "Do NOT go back 50m - spot fire", "Crew 2 is 200m south of you"]),
    ("critical", "Fire expanding further ahead", [
        "Move down-right along this path", "Do NOT go 50m back", "Regroup at creek crossing"]),
    ("warning", "Fire spreading NE, 400m ahead", [
        "Hold position at ridge trail", "Wind shifting east, 15 km/h", "Next update in 30s"]),
    ("warning", "Spot fire reported on east ridge", [
        "Stay west of the access road", "Keep escape route clear", "Water drop expected in 5 min"]),
    ("warning", "Smoke thickening to the north", [
        "Visibility under 100m ahead", "Follow the dashed route on map", "Check in with crew lead"]),
    ("info", "Area behind you is clear", [
        "Safe zone: parking lot B", "Fire front stable for 5 min"]),
    ("info", "Wind easing, fire front stable", [
        "Continue to safe zone", "Next update in 30s"]),
]


def publish(url, token, alert):
    request = urllib.request.Request(
        url, data=json.dumps(alert).encode(), method="POST",
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8790", help="backend base URL")
    parser.add_argument("--change", type=float, default=12, help="seconds between new alerts")
    parser.add_argument("--refresh", type=float, default=4, help="seconds between timestamp refreshes")
    args = parser.parse_args()
    endpoint = args.url.rstrip("/") + "/latest"
    token = os.getenv("INGEST_TOKEN", "")

    current, changed_at, last = None, 0.0, None
    while True:
        if current is None or time.time() - changed_at >= args.change:
            choice = random.choice([a for a in ALERTS if a is not last] or ALERTS)
            last, changed_at = choice, time.time()
            priority, headline, instructions = choice
            current = {"id": str(time.time_ns() // 1_000_000), "priority": priority,
                       "headline": headline, "instructions": instructions}
            print(f"[{priority}] {headline}", flush=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            publish(endpoint, token, {**current, "timestamp": stamp})
        except Exception as error:  # keep feeding through backend restarts
            print(f"  publish failed: {error}", flush=True)
        time.sleep(args.refresh)


if __name__ == "__main__":
    main()
