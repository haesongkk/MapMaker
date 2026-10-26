# Full serverless MapMaker

The browser UI and HTTP API run in a Runpod **Load Balancer** endpoint using
`Dockerfile.web`. Inference, assembly, placement correction, preview generation,
and final publication run in a separate **Queue** endpoint using `Dockerfile`.
There is no local Python server in this deployment. Rendering the interactive
Three.js view still happens in the user's browser.

```text
Browser -> authenticated HTTP entry -> Runpod web/API endpoint
                                         | submit / poll
                                         v
                                   Runpod GPU queue endpoint
                                         | inference + finalization
                                         v
                                     private S3 bucket
Browser <--- bounded HTTP artifact reads <- web/API <- S3
```

## Build and deploy

The live deployment uses `configs/cloud-deployment.json`. The web image is built
from `main`. The GPU GitHub integration also follows `main`, using
`deploy/runpod/Dockerfile.application` to reuse the verified CUDA/model runtime.
The GPU endpoint additionally applies the explicitly pinned application release
recorded in `configs/cloud-deployment.json`; a main push does not automatically
advance that application ZIP. Advance and verify the release hash when promoting
new GPU application behavior. The GPU endpoint reuses the existing CUDA/model
runtime image and applies a private, SHA-256-pinned application ZIP at startup
using `scripts/bootstrap_release.py`. Its entrypoint is `/bin/bash` with arguments
`-c` and `exec /opt/mapmaker/.venv/bin/python -c "$MAPMAKER_BOOTSTRAP"`.
Set `MAPMAKER_BOOTSTRAP` to the script contents. The final exec must retain the
absolute virtual-environment Python path in argv[0] so Python finds its packages.
`MAPMAKER_RELEASE_KEY` selects the S3 object and `MAPMAKER_RELEASE_SHA256` pins its
contents. The bundle contains only application files under `mapmaker`, `scripts`,
and `configs`; dependencies and weights are unchanged. Worker results record the
application hash in `metadata.deployment.application_sha256`.

The full-image commands below remain the deployment path for dependency/runtime
changes. Routine main builds use the application-only Dockerfile; use the full
GPU Dockerfile only when deliberately updating dependencies or the CUDA runtime.

Build from the repository root, replacing `REGISTRY` with your registry:

```sh
docker build --platform linux/amd64 -f deploy/runpod/Dockerfile -t REGISTRY/mapmaker-gpu:cloud-v1 .
docker build --platform linux/amd64 -f deploy/runpod/Dockerfile.web -t REGISTRY/mapmaker-web:cloud-v1 .
docker push REGISTRY/mapmaker-gpu:cloud-v1
docker push REGISTRY/mapmaker-web:cloud-v1
```

1. Update the GPU queue endpoint to `mapmaker-gpu:cloud-v1`. Retain its model
   storage configuration, compatible GPU types, disk space, and credentials.
   Web publication requires this new worker version. GPU jobs remain serial per
   worker, with one complete scene per queue job.
2. Create a separate **Load Balancer** endpoint with `mapmaker-web:cloud-v1`.
   Expose `8080/http` and `8081/http`; set `PORT=8080`, `PORT_HEALTH=8081`.
   `/ping` is the health route. The web process itself does not load GPU models.
   Select compute supported by Runpod for Load Balancer endpoints in your account.
3. Set the web endpoint's `MAPMAKER_GPU_ENDPOINT_ID` to the **GPU queue endpoint** ID.
   Runpod injects `RUNPOD_ENDPOINT_ID` with the web endpoint's own ID; it cannot
   be used for the target GPU endpoint. Set `RUNPOD_API_KEY` using a secret environment variable.
4. Configure both endpoints with `MAPMAKER_S3_BUCKET`, `MAPMAKER_S3_ENDPOINT`,
   `AWS_DEFAULT_REGION`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY`.
   The GPU endpoint also needs read access to the existing model storage.
   Never put credentials in Docker build arguments, images, or frontend JavaScript.
5. Optionally set `MAPMAKER_JOB_TIMEOUT` on the web endpoint (60–21600 seconds;
   default 7200). Worker minimum zero is supported: web requests do not own the
   lifetime of GPU jobs, and any web worker can read any job's status.

## Browser authentication and artifact access

The deployed browser gateway is `zlkpn4g5odgrqq` at
`https://zlkpn4g5odgrqq-8080.proxy.runpod.net`. Open the private access link saved in
`.runtime/cloud-browser-access.json` (not tracked in Git). It logs in through a
URL fragment, removes the fragment immediately, and sets a Secure/HttpOnly cookie.
The root URL alone works after that browser has authenticated. The link grants
application access, including paid generation; keep it private.

`scripts/cloud_browser_gateway.py` handles authentication and HTTP forwarding only.
The UI/API and inference remain on the existing serverless endpoints. The gateway
is an always-on Runpod CPU Pod (cpu3c, 2 vCPU, EU-RO-1): $0.06/hour compute at
deployment, plus disk billing. Stopping it disables browser access. It uses the
web runtime image pinned to `1768aaebe`, with this script supplied through
`MAPMAKER_GATEWAY_SOURCE`; entrypoint `/bin/sh`, command `-c` followed by
`exec /opt/mapmaker/.venv/bin/python -c "$MAPMAKER_GATEWAY_SOURCE"`.
`MAPMAKER_WEB_ORIGIN`, `MAPMAKER_GATEWAY_API_KEY`, and `MAPMAKER_ACCESS_TOKEN`
are private environment settings. No storage credentials are given to the gateway.
GET cold-start failures show a retry page; POST submissions are never retried.

The browser launcher below remains an alternative without the gateway.

For this private deployment, launch the authenticated browser client:

```powershell
npm.cmd ci --prefix web
node scripts/open_cloud_web.mjs
```

It uses installed Chrome and the existing `.runtime/runpod-api.key` (or
`RUNPOD_API_KEY`). It starts no local web server. The key is added only to requests
to the configured Runpod endpoint; it is not embedded in the app or URL. Close
the opened browser to stop the launcher. Keep keys out of source control.

Runpod's Load Balancer gateway requires `Authorization: Bearer <Runpod API key>`.
An ordinary browser navigation does not supply this header. The raw endpoint URL
is therefore **not a public website URL**. For a private operator deployment, use
a browser environment that injects this header only for the exact endpoint host.
For normal website access, place an authenticated HTTPS gateway in front of the
endpoint which adds the header server-side for all paths, including modules and
downloads. Do not embed an account API key in the HTML or query string. Such a
gateway is additional hosting and is not provisioned by this repository.

Runpod contract: [Build a load balancing worker](https://docs.runpod.io/serverless/load-balancing/build-a-worker).

The web worker reads private S3 with server-side credentials. The browser fetches
GLB files in 8 MiB HTTP ranges from the same origin (server maximum 16 MiB per
request), then uses the assembled Blob for viewing and download. This avoids
gateway response-size limits and requires neither presigned S3 URLs nor S3 CORS.
The existing Runpod volume rejected a presigned GET during deployment testing.
Do not make the bucket public.

## Durability and failure behavior

`mapmaker-jobs/<run_id>/request.json` persists submission identity. The worker
uploads the verified result archive and individual artifacts to `files/`, then
writes `completion.json` last. The web API never trusts an intermediate `done`
progress message as completion. Once published, saved `/?run=<run_id>` links work
across worker restarts and beyond Runpod's job-status retention period.

GPU failure/cancellation is persisted in `terminal.json` when observed. The queue
job's execution timeout/TTL limits its lifetime even if nobody polls. A web worker
restart does not cancel GPU jobs. A lost submit response is not retried: the UI
retains its run ID and waits for completion or timeout, preventing duplicate jobs.
Configure bucket lifecycle retention deliberately: deleting run records/artifacts
also invalidates saved scene links. Input/result ZIPs and individually published
files consume additional storage.

## Validation after deployment

Use an authenticated browser/gateway to open `/`, load the Three.js view, upload
a small image, and follow the returned run ID until completion. Confirm that:

- `/ping` returns 200 on both configured ports.
- Restarting only the web worker does not interrupt a GPU job.
- A second web worker can read `/api/runs/<run_id>` and completed metadata.
- GLB loads without CORS errors and the download link saves the final scene.
- Reopening `/?run=<run_id>` works after the GPU worker scales down.

Local contract tests: `.venv/Scripts/python.exe -m pytest -q`. These tests mock
cloud services and models; they do not certify an actual deployed endpoint.
