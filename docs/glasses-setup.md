# G2 setup

In glasses-app, run `npm ci`. Use `npm run use-backend -- https://firesight-dashboard.onrender.com` to set the backend and manifest network whitelist (see the client README for script options). Configure VITE_G2_REPORT_TOKEN to match the backend G2_REPORT_TOKEN privately, then `npm run build`. Configure voice reports off: the /report backend is not implemented.

The phone polls /latest and reports /g2/display. Check /g2/status while testing on physical glasses. Keep tokens out of commits and logs. SDK acceptance is not a screenshot of the physical display.

Demo maps are optional; enable FIRESIGHT_DEMO_MAP only for an explicitly simulated demonstration. The image is labelled DEMO - NOT NAVIGATION. Wearer GPS is not implemented.
