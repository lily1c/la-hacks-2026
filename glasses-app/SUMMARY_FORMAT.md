# Backend API for the glasses app

The glasses app talks to one backend:

- `GET <SUMMARY_URL>`: polled every 2 seconds for the latest summary (and optional map).
- `POST /report` on the same host: voice reports recorded on the glasses.

# Summary (backend -> glasses)

## Response

`200 OK` with `Content-Type: application/json`:

```json
{
  "id": "1792277038391",
  "timestamp": "2026-10-17T22:42:10Z",
  "priority": "critical",
  "headline": "Fire ahead - move right now",
  "instructions": [
    "Take the down-right path to creek",
    "Do NOT go back 50m - spot fire",
    "Crew 2 is 200m south of you"
  ],
  "map_url": "/map.png?v=1792277038391"
}
```

| Field | Required | Notes |
|---|---|---|
| `id` | recommended | Change it for every new summary. |
| `timestamp` | recommended | ISO 8601, when the summary was generated. Shown as HH:MM. |
| `priority` | recommended | `critical`, `warning` or `info`. Anything else is treated as `info`. |
| `headline` | **yes** | One short line, max ~40 characters. |
| `instructions` | no | Up to 5 short lines, max ~40 characters each, most important first. With a map, only the first 4 are shown. |
| `map_url` | no | URL of a map image. Absolute, or relative to the summary URL. **Change the URL whenever the map changes** (e.g. add `?v=<id>`); the app only re-downloads when the URL changes. Omit it for a text-only layout. |

Return `204 No Content` if nothing has been published yet.

## Requirements

- **CORS:** send `Access-Control-Allow-Origin: *` (the glasses app runs on a different origin).
- **Keep it short:** the display is 576×288 px, about 9 lines of ~44 characters. Longer lines get cut off with `…`.
- **Prompt the LLM for this shape:** imperative, short, distances and directions in every line.

## Map image

When `map_url` is set, the display splits: headline top-left, map top-right, instructions along the bottom.

- **Size:** exactly **288×144 px** (the largest image the glasses support).
- **Format:** PNG, greyscale. The glasses show 16 shades of green.
- **Black means off.** The display is transparent, so black pixels are see-through. Draw the fire, the wearer, routes and safe zones in bright values on a black background.
- **Keep it simple:** thick lines and big shapes. Fine detail and text are unreadable at this size.
- Images are slow over Bluetooth (a second or two), so update the map only when something meaningful changes, not every poll.

`npm run mock` serves an example at `http://localhost:8787/map.png?fire=40`.

# Voice report (glasses -> backend)

The wearer holds a temple to record and releases to send (max 30 s). The app sends:

```
POST /report
Content-Type: audio/wav

<WAV bytes: 16 kHz, 16-bit, mono PCM>
```

Respond `200 OK` (any body) once it's received. Anything else shows "Report FAILED" on the glasses.

CORS must allow `POST` and the `Content-Type` header (preflight `OPTIONS` -> `204`).

## Testing without the real backend

```sh
npm run mock   # fake server on http://localhost:8787 (summaries, map, saves reports to ./reports/)
curl -X POST localhost:8787/latest -H 'Content-Type: application/json' \
  -d '{"priority":"critical","headline":"Test alert","instructions":["Line one","Line two"]}'
```
