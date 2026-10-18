# Summary format (backend -> glasses)

The glasses app polls `GET <SUMMARY_URL>` every 2 seconds and shows the latest summary.

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
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `id` | recommended | Change it for every new summary. |
| `timestamp` | recommended | ISO 8601, when the summary was generated. Shown as HH:MM. |
| `priority` | recommended | `critical`, `warning` or `info`. Anything else is treated as `info`. |
| `headline` | **yes** | One short line, max ~40 characters. |
| `instructions` | no | Up to 5 short lines, max ~40 characters each, most important first. |

Return `204 No Content` if nothing has been published yet.

## Requirements

- **CORS:** send `Access-Control-Allow-Origin: *` (the glasses app runs on a different origin).
- **Keep it short:** the display is 576×288 px, about 9 lines of ~44 characters. Longer lines get cut off with `…`.
- **Prompt the LLM for this shape:** imperative, short, distances and directions in every line.

## Testing without the real backend

```sh
npm run mock   # fake server on http://localhost:8787/latest
curl -X POST localhost:8787/latest -H 'Content-Type: application/json' \
  -d '{"priority":"critical","headline":"Test alert","instructions":["Line one","Line two"]}'
```
