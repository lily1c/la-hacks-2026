# Architecture and consolidation

One Python process hosts the API and dashboard. Greg sends outbound HTTPS bundles from his local computer; no inbound tunnel is needed. The phone separately polls alerts and reports SDK acceptance. The backend uses bounded latest-only buffering so inference cannot build a growing queue. It keeps state in memory; restart loses it. Keep one Uvicorn worker until shared state is implemented.

The API entrypoint and existing module imports remain compatible after moving implementations to ingestion/, analysis/, contracts/ and services/. Dashboard CSS/JS are packaged assets, not inline blocks. The current map-first layout is preserved.

## Branch decisions

- feature/dashboard supplies the live application and push integration already in main.
- demo/map-feed supplies Gemini response compatibility, caching, opt-in fallback, map rendering and demo feeders. Demo options remain disabled by default. Its older dashboard layout is not restored. Demo context must not generate unverified wearer-relative navigation.
- feature/video-to-json contains the response-schema fix already incorporated via the demo branch. Its stray legacy script is not an application entrypoint.
- glasses-app has older client implementations. Preserve the newer SDK acknowledgement, retries and stale clearing in main rather than replacing them.
- vm-setup remains the historical optional VM receiver. Do not vendor its GPU checkpoint or duplicate server into the hosted app.
- feat/integrate_beagle_eyes provides an optional local installer, not a Render dependency.

Simulated map overlays and glasses demo images are not live geographic fire maps. Accurate map placement needs independently verified geographic calibration. Public read endpoints currently reveal images and telemetry; private location requires access control before implementation.
