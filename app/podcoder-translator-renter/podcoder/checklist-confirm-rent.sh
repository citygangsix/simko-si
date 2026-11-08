#!/usr/bin/env bash
# One command Joseph can run later, after he says Confirm Rent.
# It only prints the checklist. It does not create or destroy a Vast instance.
set -euo pipefail
if [[ "${1:-}" == "destroy" || "${PODCODER_DESTROY:-}" == "1" ]]; then
  echo "refuse destroy; this checklist does not destroy instances" >&2
  exit 3
fi
cat <<'EOF'
READY CHECK. vast_calls=0. This command does not create a Vast instance and does not destroy one.
Use it only after Joseph says Confirm Rent, and only with an SSH host that already exists.

1. Start the workbench:
   cd podcoder-translator-renter/local && bash start_local.sh

2. Record Confirm Rent for that existing host. Replace YOUR_SSH_HOST. Coding example:
   curl -s -X POST http://127.0.0.1:8788/api/rent -H 'Content-Type: application/json' \
     -d '{"confirm":"RENT","dry_run":false,"role":"coding","gpu":"RTX 3090","inet_down":1200,"disk_gb":150,"ssh_host":"YOUR_SSH_HOST","ssh_port":22,"ssh_user":"root"}'

3. Download onto that host. role is coding, video, or image:
   curl -s -X POST http://127.0.0.1:8788/api/download -H 'Content-Type: application/json' \
     -d '{"compute":"cloud","role":"coding"}'

4. When http://127.0.0.1:8788/api/install/status says Ready, tunnel and run the calc smoke:
   ssh -p PORT -L 8787:127.0.0.1:8787 root@YOUR_SSH_HOST
   curl -s -X POST http://127.0.0.1:8787/api/mission -H 'Content-Type: application/json' \
     -d @podcoder/sample-mission-dryverify.json

Coding uses install-on-pod-q8.sh. Video uses install-video-comfy-wan.sh. Image uses install-image-role.sh.
Destroy stays refused unless Joseph explicitly asks. Do not call Vast.
EOF
