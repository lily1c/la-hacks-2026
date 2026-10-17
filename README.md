# Even Realities Glasses Project

Even Hub app for Even Realities G2 glasses that shows live wildfire summaries to firefighters.
It polls a backend for the latest summary (JSON) every 2 seconds and displays it on the glasses.
If updates stop for 15 seconds, it shows a NO SIGNAL warning with the age of the last update.

Backend contract: see [SUMMARY_FORMAT.md](SUMMARY_FORMAT.md).

## Run in the simulator

```sh
npm install
npm run mock     # fake backend on http://localhost:8787/latest
npm run dev
evenhub-simulator http://localhost:5173
```

Tap to fetch immediately. Double-tap to exit.

## Point at the real backend

Create `.env.local`:

```
VITE_SUMMARY_URL=https://your-backend.example.com/latest
```

Also add the backend's origin to the `network` permission `whitelist` in `app.json`.

## Run on real glasses

```sh
npm run dev -- --host
evenhub qr --url "http://$(ipconfig getifaddr en0):5173"
```

Scan the QR with the Even app (Developer Mode). The phone and the computer must be on the same network.

## Notes

- With SDK 0.0.16, taps arrive as `sysEvent`, not `textEvent`. `src/main.ts` handles both.
- The startup page can only be created once per session, so after a hot reload the app falls back to `rebuildPageContainer`.
