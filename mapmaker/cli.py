"""SAM3D object-scene commands. Model environments remain isolated."""

from pathlib import Path
import typer

app = typer.Typer(
    help="Generate an object-based 3D scene from one image with RAM++, SAM3 and SAM3D."
)


@app.command()
def run(image: Path, output: Path | None = None):
    """Analyze one image, reconstruct its objects and export scene.glb."""
    from .scene_pipeline import configured_pipeline, create_run

    target = create_run(image.read_bytes(), output)
    pipeline = configured_pipeline()
    try:
        pipeline.run(target)
        typer.echo(str(target / "scene.glb"))
    finally:
        pipeline.close()


@app.command()
def serve(port: int = 8082, host: str = "127.0.0.1"):
    """Open the local upload/generate/preview web application."""
    from .web import serve as serve_web

    serve_web(host, port)


@app.command()
def render(scene: Path, output: Path = Path("previews")):
    """Render mesh previews without loading reconstruction models."""
    import subprocess, sys

    subprocess.run(
        [
            sys.executable,
            "-m",
            "mapmaker.scene_preview",
            str(scene.resolve()),
            "--out",
            str(output.resolve()),
            "--material",
        ],
        check=True,
    )


@app.command()
def doctor():
    """Check persistent runtime files; use the smoke scripts for GPU inference checks."""
    import os
    from .runtime_paths import (ROOT, SAM3D_REPO, SAM3_CHECKPOINT,
                                SAM3D_CHECKPOINT, RAM_CHECKPOINT, VISION_PYTHON, MODEL_ROOT)

    if os.environ.get("MAPMAKER_BACKEND", "runpod" if os.name == "nt" else "local") == "runpod":
        from .remote_settings import load_settings
        load_settings()
        missing = False
        for name in ("RUNPOD_API_KEY", "RUNPOD_ENDPOINT_ID", "MAPMAKER_S3_BUCKET"):
            exists = bool(os.environ.get(name))
            typer.echo(f"{'OK' if exists else 'MISSING'}  {name}")
            missing |= not exists
        try:
            import boto3
            credentials = boto3.Session().get_credentials()
            exists = credentials is not None
        except Exception:
            exists = False
        typer.echo(f"{'OK' if exists else 'MISSING'}  S3 credentials")
        missing |= not exists
        exists = (ROOT / "web/node_modules/three/package.json").is_file()
        typer.echo(f"{'OK' if exists else 'MISSING'}  Web dependencies")
        if missing or not exists:
            raise typer.Exit(1)
        return

    checks = {
        "SAM3D environment": Path(os.environ.get("SAM3D_PYTHON", ROOT / ".venv-sam3d/bin/python")),
        "Vision environment": VISION_PYTHON,
        "RAM++ checkpoint": RAM_CHECKPOINT,
        "SAM3 checkpoint": SAM3_CHECKPOINT,
        "Official SAM3D inference": SAM3D_REPO / "notebook/inference.py",
        "SAM3D configuration": SAM3D_CHECKPOINT,
        "DINOv2 source": Path(os.environ.get("TORCH_HOME", MODEL_ROOT / ".runtime/sam3d-torch"))
        / "hub/facebookresearch_dinov2_main/hubconf.py",
        "DINOv2 pretrained weights": Path(os.environ.get("TORCH_HOME", MODEL_ROOT / ".runtime/sam3d-torch"))
        / "hub/checkpoints/dinov2_vitl14_reg4_pretrain.pth",
        "Web dependencies": ROOT / "web/node_modules/three/package.json",
    }
    missing = False
    for label, path in checks.items():
        exists = path.is_file()
        typer.echo(f"{'OK' if exists else 'MISSING'}  {label}: {path}")
        missing |= not exists
    if missing:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
