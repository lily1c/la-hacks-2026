# FireSight cloud VM deployment

Prepared for project `firesight-la-hacks-2026`. The VM `firesight-ingest` exists in `us-central1-a`; its observed external IP was `34.170.148.82` (not confirmed reserved). Application deployment is still pending. Do not run the provisioning script to create another VM. The chosen initial machine is Ubuntu 24.04, `e2-small` (2 GiB RAM), 20 GB standard persistent disk, with an external IPv4. It relays video and samples JPEGs; it does not run DPVO or an AI model. Confirm capacity against real source resolution/bitrate.

## Before provisioning

Review the console estimate: VM compute, disk, external IPv4, and outbound video traffic are separately billable. No remaining credits were shown on the inspected billing account. Establish a budget and teardown time before launch; budget alerts do not stop spending.

The creation script expects an existing default VPC. Set the drone sender and teammate's public IP/CIDR; only those addresses get ingress on media ports. Do not replace them with unrestricted internet access without reviewing the exposure. A controller's LAN address such as 192.168.x.x is not its public address.

In Google Cloud Shell, after cost approval and uploading this checkout:

```sh
export PROJECT_ID=firesight-la-hacks-2026
export DRONE_CIDR=REPLACE_WITH_PUBLISHER_PUBLIC_IP/32
export TEAM_CIDR=REPLACE_WITH_TEAM_PUBLIC_IP/32
bash cloud/provision.sh
```

The script is intentionally not idempotent; if a step fails, inspect existing resources before rerunning it. It may leave a reserved IP or VM behind. It creates no public dashboard, storage bucket, or cloud AI endpoint. Existing VPC SSH rules remain in force; use Google Cloud SSH according to your project's existing policy.

## Install on the new VM

Copy the checkout to the VM with `gcloud compute scp --recurse` or the console upload mechanism. Keep generated credentials off GitHub. On the VM:

```sh
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 python3
sudo systemctl enable --now docker
cd /path/to/la-hacks-2026
sudo python3 cloud/configure.py
sudo docker compose -f cloud/compose.yaml up -d --build
sudo docker compose -f cloud/compose.yaml ps
sudo docker compose -f cloud/compose.yaml logs --tail=30 snapshots
```

The relay and worker restart after reboot through Docker's restart policy. Data lives under `cloud/data/bundles` on the persistent boot disk. It is not backed up. Storage is bounded to 2,000 bundles or 512 MiB with a 256 MiB free-space reserve. Pending bundles are retained; new frames are skipped when full. The sender deletes acknowledged bundles after one hour. Default HLS/browser playback is disabled in this deployment; use authenticated RTSP in VLC/OpenCV.

## Addresses to give the team

Read `cloud/.env` privately on the VM. Substitute its credentials below; placeholders are not usable links.

```text
Drone publish:
rtmp://VM_PUBLIC_IP:1935/live/dji?user=drone&pass=PUBLISH_PASSWORD

Beagle Eyes / AI live read:
rtmp://VM_PUBLIC_IP:1935/live/dji?user=reader&pass=READ_PASSWORD
rtsp://reader:READ_PASSWORD@VM_PUBLIC_IP:8554/live/dji
```

The firewall script allows the AI teammate RTSP on 8554 only. If Beagle must read RTMP instead, explicitly allow that teammate's IP on 1935 too. Prefer the RTSP reader where supported. Check that the drone controller can actually supply RTMP credentials; if it cannot, use an authenticated OBS/FFmpeg bridge. Do not assume controller support from the URL alone. This RTMP/RTSP setup uses unencrypted transport; for real sensitive footage, add a supported TLS endpoint or private VPN before using it outside a trusted demo.

Snapshots start automatically after valid media arrives. They pair image and metadata by frame_id. The standalone worker emits image metadata only; Beagle's optional latest-keyframe pose requires its integrated exporter in the teammate's inference environment. See `docs/beagle-integration.md` for the exact contract and caveats.

## Forward image + JSON to AI

Once the AI teammate provides an agreed multipart receiving endpoint, set `AI_ENDPOINT` and `AI_TOKEN` in `cloud/.env` on the VM, then:

```sh
sudo docker compose -f cloud/compose.yaml --profile ai up -d --build
```

Do not enable two delivery workers on the same bundle directory. Existing bundles are sent oldest first and marked after acknowledgment. No AI destination is configured by default.

## Stop and clean up

`sudo docker compose -f cloud/compose.yaml --profile ai down` stops the application, but **VM/disk/IP billing continues**. When finished, delete the VM, its boot disk (if retained), reserved address, and dedicated firewall rules through the console. The provisioning script names them `firesight-ingest`, `firesight-ingest-ip`, `firesight-ingest-publish`, and `firesight-ingest-read`. Review data you want to keep before deleting the VM/disk.

## QNX direction

Read `qnx/README.md` before attempting to move the Linux stack. Docker images, Linux wheels, and CUDA/DPVO are not a QNX deployment package. Keep media, storage and inference behind the JSON interface so they can be replaced component by component.
