# FireSight end-to-end demo: drone frames → AI analysis → G2 glasses

This guide shows you how to run the whole FireSight loop on your own machine and see it on **Even Realities G2** smart glasses (or the G2 simulator if you don't have glasses):

```
 Drone frames ──POST /frame──► FireSight backend ──GET /latest──► Glasses app ──Bluetooth──► G2 display
 (6 sample images,             analyzes each frame               (Even phone app)            alert + map
  one every few seconds)       → alert JSON + map image
```

Every few seconds a new frame is analyzed and the glasses update with what the analysis found. A screen on the glasses looks like this:

```
!! CRITICAL   09:52 PM                ┌────────────────────┐
FIRE SPREADING AHEAD AND RIGHT        │ ▲          ████    │
                                      │          ██████    │
- Move down-right to creek trail      │      ◎             │
- Do NOT go back - spot fire 50m      │    ╱               │
- Crew 2 is 200m to your left         │  □                 │
                                      └────────────────────┘
```

## What's real and what's demo data

| Part | Real or demo? |
|---|---|
| **Frames** | Demo. Six variations (crops, mirror images, a black-and-white "smoke only" copy) of one real wildfire photo, so the fire lands in different parts of the frame. You can use your own images instead. |
| **Analysis** | **Real.** Each frame goes through the detector: OpenCV fire-color detection by default, or Gemini if you add an API key. |
| **Instructions** | **Real output of the analysis.** OpenCV can only say *where* fire is ("Check upper-left frame sector"). Gemini mode writes action instructions using the image plus a scenario file. |
| **Field data** for Gemini (wind, escape route, safe zone, crews) | Demo. Invented in [`demo_scenario.json`](demo_scenario.json). In a real deployment this would come from GPS, weather and command. |
| **Map** | Demo placeholder. The wearer (◎), escape route and safe zone (□) are drawn, not measured. **The fire is placed in the part of the frame the analysis reported**, so the map matches the instructions. |

Nothing in this demo is real evacuation guidance.

---

## 1. What you need

| | Needed for |
|---|---|
| macOS or Linux, with git | everything |
| **Python 3.10 or newer** (`python3 --version`; on macOS, `brew install python@3.11` if yours is older) | the backend |
| **Node.js 20 or newer** with npm (`node --version`) | the glasses app |
| **Even Hub tools**: `npm install -g @evenrealities/evenhub-cli @evenrealities/evenhub-simulator` | packaging and the simulator |
| **G2 glasses** paired with the **Even Realities app**, with **Developer Mode** on, plus access to the **Even Hub developer portal** | real glasses only (§3B) |
| **cloudflared** (`brew install cloudflared`) | real glasses only: lets your phone reach your laptop |
| A **Gemini API key** from [Google AI Studio](https://aistudio.google.com/app/apikey) | optional: AI-written instructions (§4) |

## 2. One-time setup

```sh
git clone https://github.com/lily1c/la-hacks-2026.git
cd la-hacks-2026
git switch demo/map-feed

# Backend (Python)
python3 -m venv .venv          # use python3.11 -m venv .venv if python3 is older than 3.10
.venv/bin/python -m pip install -e .

# Glasses app (Node)
cd glasses-app
npm ci
cd ..
```

Check that it worked:

```sh
.venv/bin/python -c "import firesight.api, cv2; print('backend OK')"
```

All commands below are run from the `la-hacks-2026` folder unless they say otherwise.

---

## 3A. Run it without glasses (simulator)

This is the quickest way to see the whole loop. Use **4 terminal windows**.

**Terminal 1: backend**
```sh
FIRESIGHT_DEMO_MAP=true FIRESIGHT_DETECTOR=opencv .venv/bin/uvicorn firesight.api:app --port 8790
```
Wait for `Uvicorn running on http://127.0.0.1:8790`.

**Terminal 2: frame feeder**
```sh
.venv/bin/python scripts/frame_feed.py
```
Every 6 seconds you'll see the analysis of the next frame:
```
wide view, fire upper            -> [warning] Fire detected - use caution | Check upper frame sector; ...
smoke only, no flames            -> [info] No fire detected in frame |
close pass, fire upper-left      -> [critical] Fire detected - use caution | Check upper-left frame sector; ...
```

**Terminal 3: glasses app**
```sh
cd glasses-app
VITE_SUMMARY_URL=http://127.0.0.1:8790/latest npx vite --port 5173
```

**Terminal 4: simulator**
```sh
evenhub-simulator http://localhost:5173
```

✅ The simulator window shows the same alert as Terminal 2's latest line, with the map. It changes every 6 seconds, and the map's fire moves to match each analysis.

---

## 3B. Run it on real G2 glasses

Your phone can't reach `localhost` on your laptop, so a **tunnel** gives the backend a temporary public `https://` address. The glasses app is then packaged with that address and installed through Even Hub.

**Terminals 1 and 2:** start the backend and frame feeder exactly as in §3A.

**Terminal 3: tunnel** (leave this running for the whole test)
```sh
cloudflared tunnel --protocol http2 --url http://localhost:8790
```
Copy the address it prints, e.g. `https://random-words-here.trycloudflare.com`.

> ⚠️ Every time you restart `cloudflared`, you get a **new address**, and you have to repeat the build and upload below. Keep it running.

Check that it works: open `https://<your-address>/latest` in your **phone's** browser. You should see JSON with an alert.

**Terminal 4: build the glasses app for that address**
```sh
cd glasses-app
npm run use-backend -- https://<your-address>.trycloudflare.com
```
This writes the address into `.env.local` and the network whitelist in `app.json`. These must match, or the glasses app won't be allowed to fetch.

Now open `glasses-app/app.json` and **increase `"version"`** (e.g. `0.3.5` → `0.3.6`). Then run:
```sh
npm run pack
```
This creates `glasses-app/firesight.ehpk`.

> ⚠️ **Always increase the version before uploading.** If the portal says it will *replace* an existing version, your phone won't download the new build and will keep using the old one, with its old address.

**On your phone:**
1. Upload `glasses-app/firesight.ehpk` in the Even Hub developer portal. Check that it shows the new version.
2. In the Even app, update FireSight and check that it shows the new version.
3. **Restart fully:** double-tap the glasses to exit FireSight (confirm the dialog), force-quit the Even app, reopen it and launch FireSight.

✅ The glasses show the same alert as Terminal 2's latest line, with the map, and update with every new frame.

**Glasses controls:** tap = fetch now · double-tap = exit.

---

## 4. Optional: AI-written instructions with Gemini

OpenCV only reports *where* fire is. Gemini looks at the image, combines it with the field data in [`demo_scenario.json`](demo_scenario.json) and writes instructions a firefighter could act on:

```
[critical] Fire spreading ahead and right | Move down-right toward creek trail; Do NOT go back - spot fire behind; Reach creek safe zone 300m down-right
```

**Terminal 1:** stop the backend (Ctrl+C), then run these as **two separate commands**:
```sh
export GEMINI_API_KEY='your-key-here'
```
```sh
FIRESIGHT_DEMO_MAP=true FIRESIGHT_DETECTOR=gemini FIRESIGHT_SCENARIO=demo_scenario.json FIRESIGHT_GEMINI_FALLBACK=opencv .venv/bin/uvicorn firesight.api:app --port 8790
```

**Terminal 2:** restart the feeder with a longer interval:
```sh
.venv/bin/python scripts/frame_feed.py --interval 10
```

There's no need to rebuild or upload the glasses app. It just reads whatever the backend publishes.

**Things to know:**
- **Quota.** Gemini's free plan allows only about **20 requests per day** for this model. The backend **analyzes each image only once** and reuses the result when the same image comes round again, so the 6-frame loop costs 6 requests. That cache is cleared when the backend restarts. For a presentation, start the backend shortly beforehand.
- **Fallback.** With `FIRESIGHT_GEMINI_FALLBACK=opencv`, a frame Gemini can't analyze (e.g. quota used up) is analyzed with OpenCV instead, so the glasses never go blank. Those frames show the simpler "Check … frame sector" text.
- **Your own story.** Edit `demo_scenario.json` to change the wind, route, safe zone, hazards or crews, then restart the backend. Gemini is told to use **only** distances and routes from this file, never invented ones.
- **Keep the key out of the repo.** Use `export` in your terminal as shown. Don't put it in any file in the repo or paste it into chats. If you do, delete it in AI Studio and create a new one.

## 5. Optional: use your own images

Put JPEG or PNG frames in a folder and point the feeder at it:
```sh
.venv/bin/python scripts/frame_feed.py --dir ~/path/to/frames --interval 10
```
Frames are sent in filename order and loop forever.

---

## Reference

### Backend settings (environment variables for Terminal 1)

| Variable | Effect |
|---|---|
| `FIRESIGHT_DETECTOR` | `opencv` (local, free), `gemini` (needs `GEMINI_API_KEY`) or `auto` (Gemini if a key is set) |
| `FIRESIGHT_DEMO_MAP=true` | Adds the placeholder map: `map_url` in `/latest`, image at `/view.png`. Off by default. |
| `FIRESIGHT_SCENARIO=demo_scenario.json` | Gemini only: use the field-data file and write actionable instructions. Without it, Gemini only describes where fire is visible. |
| `FIRESIGHT_GEMINI_FALLBACK=opencv` | Gemini only: fall back to OpenCV for a frame when Gemini fails |
| `GEMINI_API_KEY` | Your Gemini key |
| `GEMINI_MODEL` | Optional model override |

### Frame feeder options (`scripts/frame_feed.py`)

| Option | Default | Effect |
|---|---|---|
| `--url` | `http://127.0.0.1:8790` | Backend to send frames to |
| `--interval` | `6` | Seconds between frames. Use 10 or more with Gemini. |
| `--dir` | (built-in dummy frames) | Folder of your own JPEG/PNG frames |

If the backend runs with `PUBLIC_DEPLOYMENT=true` (as on Render), set `INGEST_TOKEN=...` before running the feeder.

### Backend endpoints used in this demo

| Endpoint | Used by |
|---|---|
| `POST /frame` | Feeder: send one JPEG/PNG; it's analyzed and becomes the latest alert |
| `GET /latest` | Glasses app: polled every 2 s. Returns the alert JSON, or `204` if there's no recent alert (alerts expire after 30 s). |
| `GET /view.png?v=…&dir=…` | Glasses app: the 288×144 map image |
| `GET /health` | Quick check that the backend is up |

The alert JSON format is documented in [`glasses-app/SUMMARY_FORMAT.md`](glasses-app/SUMMARY_FORMAT.md).

---

## Troubleshooting

| What you see | Cause | Fix |
|---|---|---|
| Glasses: **"Connecting to command..."** and nothing else | The app has never reached its backend. Usually the phone is running an **older build** with an old tunnel address. | Check the version in the Even app matches what you just uploaded. If the portal said "replace", increase `version`, `npm run pack` and upload again. Then fully restart (§3B). |
| Glasses: **"NO SIGNAL - last update Xs ago"** | It was connected, then lost the backend: tunnel or backend stopped, or the phone lost internet | Check Terminals 1 and 3 are still running. If you restarted the tunnel, you have a new address: rebuild and upload. |
| Glasses: **"Waiting for first update..."** | Connected, but the backend has no recent alert | Check Terminal 2. Frames are probably failing (see below). Alerts expire, so the feeder must keep running. |
| Feeder: `failed: HTTP Error 502` | Gemini rejected the frame | Look at Terminal 1. `429 RESOURCE_EXHAUSTED` means your daily free quota is used up: add `FIRESIGHT_GEMINI_FALLBACK=opencv`, wait for the reset, or enable billing on the key's Google Cloud project. |
| Feeder: `Connection refused` | Backend isn't running | Start Terminal 1 |
| Phone browser can't open the tunnel address | A brand-new tunnel can take a minute to become reachable, and the phone may remember a failed lookup | Wait a minute, toggle Wi-Fi or airplane mode, try again |
| Terminal shows `quote>` | A command is missing its closing `'` (usually the `export` line) | Press Ctrl+C and run the command again with the closing quote |
| `npm run pack` says the entrypoint was not found | The build failed | Run `npm run build` in `glasses-app` and fix the error it shows |
| Simulator shows nothing | Dev server not running, or wrong port | Check Terminal 3 in §3A and that the simulator URL matches its port |

## When you're done

- Stop everything with Ctrl+C in each terminal.
- **Don't commit the tunnel address.** `npm run use-backend` edits `glasses-app/app.json`. Undo it before committing:
  ```sh
  git checkout -- glasses-app/app.json
  ```
  To point the glasses app back at the hosted backend instead, run:
  ```sh
  cd glasses-app && npm run use-backend -- https://firesight-dashboard.onrender.com/
  ```

## Files added for this demo

| File | What it does |
|---|---|
| [`scripts/frame_feed.py`](scripts/frame_feed.py) | Sends dummy (or your own) frames to `POST /frame` on a loop and prints each analysis |
| [`src/firesight/mapview.py`](src/firesight/mapview.py) | Draws the placeholder 288×144 map, with the fire placed in the reported part of the frame |
| [`demo_scenario.json`](demo_scenario.json) | Invented field data used by the Gemini prompt |
| [`scripts/demo_feed.py`](scripts/demo_feed.py) | Alternative feeder that publishes random pre-written alerts, with no image analysis |
| Changes in [`src/firesight/api.py`](src/firesight/api.py) | `FIRESIGHT_DEMO_MAP`: adds `map_url` and serves `/view.png` |
| Changes in [`src/firesight/gemini.py`](src/firesight/gemini.py) | Scenario prompt, `fire_sector`, per-image result cache, fix for a schema field Gemini rejected |
| Changes in [`src/firesight/frame.py`](src/firesight/frame.py) | Optional OpenCV fallback when Gemini fails |
