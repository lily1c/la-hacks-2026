# Verification

From the root after `pip install -e '.[test]'`:

```sh
FIRESIGHT_DETECTOR=opencv python -m unittest discover -s tests
node --test glasses-app/tests/display.test.mjs
cd glasses-app
npm ci
npm run build
```

A release also needs a real smoke test: send two distinct paired frames, observe changing /live IDs and telemetry, wait for matching /latest analysis IDs, then verify phone SDK reporting at /g2/status. Stop sending and ensure freshness clears after 30 seconds. Test reconnects with a new sender session. Automated tests do not verify physical glasses or a real drone.

The mock server and demo feeders are test inputs, not live sources. Gemini calls require separate account/model validation; unit tests mock that external dependency.
