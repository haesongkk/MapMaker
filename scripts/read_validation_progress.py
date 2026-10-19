"""Read persisted job states and worker-published progress without submitting jobs."""
import argparse
from pathlib import Path
from mapmaker.scene_run import read
from mapmaker.scene_transfer import ArtifactStore


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    store = ArtifactStore()
    for job in read(args.root/'jobs.json'):
        progress = store.progress(job['run_id'])
        print(dict(sample=job['sample'], run_id=job['run_id'],
            job_status=job['status'], progress=progress), flush=True)
