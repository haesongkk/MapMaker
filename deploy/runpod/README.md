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
Browser <--------- signed artifact URLs --+
```

## Build and deploy

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
3. Set the web endpoint's `RUNPOD_ENDPOINT_ID` to the **GPU queue endpoint** ID,
   not its own ID. Set `RUNPOD_API_KEY` using a secret environment variable.
4. Configure both endpoints with `MAPMAKER_S3_BUCKET`, `MAPMAKER_S3_ENDPOINT`,
   `AWS_DEFAULT_REGION`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY`.
   The GPU endpoint also needs read access to the existing model storage.
   Never put credentials in Docker build arguments, images, or frontend JavaScript.
5. Optionally set `MAPMAKER_JOB_TIMEOUT` on the web endpoint (60–21600 seconds;
   default 7200). Worker minimum zero is supported: web requests do not own the
   lifetime of GPU jobs, and any web worker can read any job's status.

## Browser authentication and artifact access

Runpod's Load Balancer gateway requires `Authorization: Bearer <Runpod API key>`.
An ordinary browser navigation does not supply this header. The raw endpoint URL
is therefore **not a public website URL**. For a private operator deployment, use
a browser environment that injects this header only for the exact endpoint host.
For normal website access, place an authenticated HTTPS gateway in front of the
endpoint which adds the header server-side for all paths, including modules and
downloads. Do not embed an account API key in the HTML or query string. Such a
gateway is additional hosting and is not provisioned by this repository.

Runpod contract: [Build a load balancing worker](https://docs.runpod.io/serverless/load-balancing/build-a-worker).

Final GLB files are loaded directly from private S3 through one-hour signed URLs,
avoiding HTTP endpoint response-size limits. The S3 endpoint must be reachable
from the browser and permit CORS `GET`/`HEAD` for your exact frontend origin
(including `Range` request headers if applicable). Configure CORS on the storage
service; verify that your S3-compatible provider supports it before deployment.
If the existing Runpod volume S3 service does not support the required browser
CORS behavior, use a compatible artifact bucket and retain model storage access
on the GPU worker, or provide an artifact gateway. Do not make the bucket public.

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
