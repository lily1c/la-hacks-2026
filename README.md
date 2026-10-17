# Even Realities Glasses Project

A minimal Even Hub app for Even Realities G2 glasses: tap to count, double-tap to exit.

## Run in the simulator

```sh
npm install
npm run dev
evenhub-simulator http://localhost:5173
```

## Run on real glasses

```sh
npm run dev -- --host
evenhub qr --url "http://$(ipconfig getifaddr en0):5173"
```

Scan the QR with the Even app (Developer Mode). The phone and the computer must be on the same network.

## Notes

- With SDK 0.0.16, taps arrive as `sysEvent`, not `textEvent`. `src/main.ts` handles both.
- The startup page can only be created once per session, so after a hot reload the app falls back to `rebuildPageContainer`.
