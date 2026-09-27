import importlib
from pathlib import Path

from mapmaker import runtime_paths


def test_vision_interpreter_keeps_virtual_environment_path(monkeypatch, tmp_path):
    interpreter = tmp_path / "venv" / "bin" / "python"
    monkeypatch.setenv("MAPMAKER_VISION_PYTHON", str(interpreter))
    original = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == interpreter:
            return tmp_path / "base-python"
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "resolve", resolve)
        assert importlib.reload(runtime_paths).VISION_PYTHON == interpreter
    monkeypatch.delenv("MAPMAKER_VISION_PYTHON")
    importlib.reload(runtime_paths)
