# Deployment

Render uses the root render.yaml and deploy/Dockerfile. Set the existing service's deployment branch to main. Preserve INGEST_TOKEN and G2_REPORT_TOKEN; set INGEST_MODE=push and PUBLIC_DEPLOYMENT=true. The detector defaults to opencv. Gemini requires explicit account configuration.

For local Docker: set INGEST_TOKEN and G2_REPORT_TOKEN, then run `docker compose -f deploy/compose.yaml up --build`. Open localhost:8790. No VM or mounted frame folder is required for push ingestion.

After deploying, verify /health and /live. Before Greg connects, /live should show source=beagle_push and fresh=false. Test a real upload before declaring the pipeline live. Use one worker while state remains in memory.
