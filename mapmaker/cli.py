from __future__ import annotations

import sys
from pathlib import Path

import typer

from .pipeline import Pipeline

app = typer.Typer(help="Generate a textured 3D scene from one image.")


@app.command()
def run(image: Path, output: Path = Path("output"), gen3c_repo: Path = Path("external/GEN3C"),
        gen3c_checkpoints: Path = Path("external/GEN3C/checkpoints"),
        ram_checkpoint: Path = Path("checkpoints/ram_plus_swin_large_14m.pth"),
        gen3c_python: str = sys.executable, moge_python: str = "",
        vision_python: str = "", hunyuan_python: str = "", distance: float = 1.0, angle: float = 90.0,
        force: bool = False) -> None:
    pipeline = Pipeline(image, output)
    pipeline.original(force=force, moge_python=moge_python or None)
    pipeline.views(gen3c_repo.resolve(), gen3c_checkpoints.resolve(), gen3c_python,
                   force=force, distance=distance, angle=angle)
    pipeline.candidates(ram_checkpoint.resolve(), vision_python or None)
    pipeline.segment(vision_python or None)
    pipeline.select_views()
    pipeline.meshes(hunyuan_python or None)
    target = pipeline.scene()
    typer.echo(str(target))


@app.command()
def step(name: str, image: Path, output: Path = Path("output"),
         gen3c_repo: Path = Path("external/GEN3C"),
         gen3c_checkpoints: Path = Path("external/GEN3C/checkpoints"),
         ram_checkpoint: Path = Path("checkpoints/ram_plus_swin_large_14m.pth"),
         gen3c_python: str = sys.executable, moge_python: str = "",
         vision_python: str = "", hunyuan_python: str = "",
         distance: float = 1.0, angle: float = 90.0) -> None:
    pipeline = Pipeline(image, output)
    actions = {
        "original": lambda: pipeline.original(moge_python=moge_python or None),
        "views": lambda: pipeline.views(gen3c_repo.resolve(), gen3c_checkpoints.resolve(),
                                         gen3c_python, distance=distance, angle=angle),
        "candidates": lambda: pipeline.candidates(ram_checkpoint.resolve(), vision_python or None),
        "segment": lambda: pipeline.segment(vision_python or None),
        "select-views": pipeline.select_views,
        "meshes": lambda: pipeline.meshes(hunyuan_python or None),
        "scene": pipeline.scene,
    }
    if name not in actions:
        raise typer.BadParameter(f"Choose one of: {', '.join(actions)}")
    actions[name]()




@app.command()
def doctor(gen3c_repo: Path = Path("external/GEN3C"),
           gen3c_checkpoints: Path = Path("external/GEN3C/checkpoints"),
           ram_checkpoint: Path = Path("checkpoints/ram_plus_swin_large_14m.pth"),
           moge_python: str = ".venv-moge/bin/python",
           vision_python: str = ".venv-vision/bin/python",
           hunyuan_python: str = ".venv/bin/python",
           gen3c_python: str = ".venv-gen3c/bin/python") -> None:
    """Show local model code and checkpoint readiness."""
    import subprocess

    def module_available(python: str, module: str) -> bool:
        if not Path(python).is_file():
            return False
        result = subprocess.run([python, "-c",
                                 f"import importlib.util; assert importlib.util.find_spec('{module}')"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0

    checks = {
        "MoGe environment": module_available(moge_python, "moge"),
        "RAM++/SAM 3 environment": module_available(vision_python, "ram")
                                    and module_available(vision_python, "sam3"),
        "RAM++ checkpoint": ram_checkpoint.is_file(),
        "Hunyuan environment": module_available(hunyuan_python, "hy3dgen"),
        "GEN3C environment": module_available(gen3c_python, "amp_C"),
        "GEN3C source": (gen3c_repo / "cosmos_predict1/diffusion/inference/gen3c_single_image.py").is_file(),
        "GEN3C checkpoints": (gen3c_checkpoints / "Gen3C-Cosmos-7B/model.pt").is_file(),
    }
    for label, ready in checks.items():
        typer.echo(f"{'OK' if ready else 'MISSING'}  {label}")


if __name__ == "__main__":
    app()
