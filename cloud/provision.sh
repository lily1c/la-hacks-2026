#!/usr/bin/env bash
# Run in Google Cloud Shell AFTER reviewing cost and approving VM creation.
set -euo pipefail
: "${PROJECT_ID:?Set PROJECT_ID}"
: "${DRONE_CIDR:?Set the drone publisher public IP/CIDR, e.g. 203.0.113.1/32}"
: "${TEAM_CIDR:?Set the AI teammate public IP/CIDR}"
REGION="${REGION:-us-west1}"
ZONE="${ZONE:-us-west1-b}"
VM_NAME="${VM_NAME:-firesight-ingest}"
gcloud services enable compute.googleapis.com --project="$PROJECT_ID"
gcloud compute addresses create "$VM_NAME-ip" --region="$REGION" --project="$PROJECT_ID"
VM_IP="$(gcloud compute addresses describe "$VM_NAME-ip" --region="$REGION" --project="$PROJECT_ID" --format='value(address)')"
gcloud compute instances create "$VM_NAME" \
  --project="$PROJECT_ID" --zone="$ZONE" --machine-type=e2-small \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=20GB --boot-disk-type=pd-standard \
  --address="$VM_IP" --tags=firesight-ingest \
  --no-service-account --shielded-secure-boot
gcloud compute firewall-rules create "$VM_NAME-publish" --project="$PROJECT_ID" \
  --network=default --direction=INGRESS --action=ALLOW --rules=tcp:1935 \
  --source-ranges="$DRONE_CIDR" --target-tags=firesight-ingest
gcloud compute firewall-rules create "$VM_NAME-read" --project="$PROJECT_ID" \
  --network=default --direction=INGRESS --action=ALLOW --rules=tcp:8554 \
  --source-ranges="$TEAM_CIDR" --target-tags=firesight-ingest
printf 'VM prepared at %s. Install the stack using cloud/README.md.\n' "$VM_IP"
