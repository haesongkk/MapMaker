"""Restore the official SAM3D auxiliary backbone in the persistent Torch Hub cache."""

from pathlib import Path
import hashlib, json, os, tarfile, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
REV = "7764ea0f912e53c92e82eb78a2a1631e92725fc8"
HUB = Path(os.environ.get("TORCH_HOME", ROOT / ".runtime/sam3d-torch")) / "hub"
SOURCE = HUB / "facebookresearch_dinov2_main"
WEIGHT = HUB / "checkpoints/dinov2_vitl14_reg4_pretrain.pth"
URL = "https://dl.fbaipublicfiles.com/dinov2/dinov2_vitl14/dinov2_vitl14_reg4_pretrain.pth"


def fetch(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, partial.open("wb") as f:
        while chunk := r.read(8 * 1024 * 1024):
            f.write(chunk)
    partial.replace(path)


def source():
    if (SOURCE / "revision.txt").exists() and (
        SOURCE / "revision.txt"
    ).read_text().strip() != REV:
        raise RuntimeError(
            "Existing DINO source revision differs from the pinned recovery revision"
        )
    if not (SOURCE / "hubconf.py").exists():
        archive = HUB / (REV + ".tar.gz")
        fetch(
            "https://codeload.github.com/facebookresearch/dinov2/tar.gz/" + REV, archive
        )
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            for member in members:
                if not (HUB / member.name).resolve().is_relative_to(
                    HUB.resolve()
                ) or not (member.isfile() or member.isdir()):
                    raise RuntimeError("Unexpected archive member")
            tar.extractall(HUB, members=members)
        (HUB / ("dinov2-" + REV)).rename(SOURCE)
    (SOURCE / "revision.txt").write_text(REV + "\n")


def weight():
    if not WEIGHT.exists():
        fetch(URL, WEIGHT)


with ThreadPoolExecutor(2) as pool:
    list(pool.map(lambda f: f(), [source, weight]))
hash = hashlib.sha256()
with WEIGHT.open("rb") as f:
    while chunk := f.read(8 * 1024 * 1024):
        hash.update(chunk)
assert (
    hash.hexdigest()
    == "36e4deffbaef061a2576705b0c36f93621e2ae20bf6274694821b0b492551b51"
), "Official weight checksum mismatch"
report = {
    "source_url": "https://github.com/facebookresearch/dinov2",
    "revision": REV,
    "source": str(SOURCE),
    "weight_url": URL,
    "weight": str(WEIGHT),
    "bytes": WEIGHT.stat().st_size,
    "sha256": hash.hexdigest(),
    "historical_hub_revision_known": False,
    "weight_format_modified": False,
}
provenance = Path(os.environ.get("MAPMAKER_DINO_PROVENANCE", Path(os.environ.get("MAPMAKER_MODEL_ROOT", ROOT)) / ".runtime/sam3d-recovery/dinov2-restoration.json"))
provenance.parent.mkdir(parents=True, exist_ok=True)
provenance.write_text(
    json.dumps(report, indent=2)
)
print(json.dumps(report, indent=2))
