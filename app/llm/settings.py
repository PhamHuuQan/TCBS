"""Validate local model locations and persist settings before changing runtime state."""
import os
from pathlib import Path
import re
import tempfile

DEFAULT_MODEL_PATH = "./gemma-4-E4B-it-Q4_K_M.gguf"
DEFAULT_MODEL_TYPE = "gemma"


def normalize_model_path(value):
    return str(Path(value).expanduser().resolve())


def save_model_settings(model_path, model_type, env_file=None):
    if not isinstance(model_path, str) or not model_path.strip():
        raise ValueError("Model path cannot be empty.")
    if any(char in model_path for char in "\r\n\x00"):
        raise ValueError("Model path must be a single line.")
    if not isinstance(model_type, str) or model_type not in {"qwen", "gemma", "llama", "mistral"}:
        raise ValueError("Unsupported model architecture.")
    path = Path(normalize_model_path(model_path.strip()))
    if not path.exists():
        raise ValueError("Model path does not exist on the server.")
    if path.is_dir():
        if not (path / "config.json").is_file() or not any(path.glob("*.safetensors")):
            raise ValueError("Choose an MLX model folder containing config.json and .safetensors weights.")
    elif not path.is_file() or path.suffix.lower() != ".gguf":
        raise ValueError("Choose a .gguf file or an MLX model folder.")

    settings = {"LOCAL_MODEL_PATH": str(path), "LOCAL_MODEL_TYPE": model_type}
    env_file = Path(env_file) if env_file else Path.cwd() / ".env"
    content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    for key, value in settings.items():
        # Single-quoted dotenv values preserve spaces, #, and Windows backslashes.
        quoted = value.replace("\\", "\\\\").replace("'", "\\'")
        line = f"{key}='{quoted}'"
        pattern = rf"^(?:export\s+)?{key}\s*=.*$"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, lambda _: line, content, flags=re.MULTILINE)
        else:
            content = content.rstrip("\n") + "\n" + line + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=env_file.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(content)
        os.replace(temporary, env_file)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    os.environ.update(settings)
    return settings
