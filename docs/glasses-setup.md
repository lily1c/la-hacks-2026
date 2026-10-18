# G2 setup

Installing and running the glasses app (simulator, real G2 with the hosted backend, or your own backend), including the accounts, keys and tokens a tester needs, is in [glasses-app/README.md → Install and run on G2](../glasses-app/README.md#install-and-run-on-g2).

Notes for operators:
- `G2_REPORT_TOKEN` (backend) must equal `VITE_G2_REPORT_TOKEN` (glasses build). It authorizes `POST /g2/display` and `POST /wearer`. Never put model API keys or `INGEST_TOKEN` in the glasses build.
- Drone-frame alerts reach the glasses only with `G2_DELIVERY_ENABLED=true`.
- Check `/g2/status` and `/wearer` while testing on physical glasses. SDK acceptance is not a screenshot of the physical display.
- Demo maps (`FIRESIGHT_DEMO_MAP`) and the demo fire (`FIRESIGHT_DEMO_HAZARD`) are for explicitly simulated demonstrations only. API details are in [api-contracts.md](api-contracts.md).
