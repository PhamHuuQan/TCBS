"""Read-only, paginated model picker for the local TDnook host."""
import os
from pathlib import Path

from app.llm.settings import DEFAULT_MODEL_PATH


def is_mlx_folder(path):
    return (path / "config.json").is_file() and any(path.glob("*.safetensors"))


def folder_model_path(folder):
    """A folder selects MLX weights or its sole GGUF; multiple GGUFs need a choice."""
    try:
        if is_mlx_folder(folder):
            return str(folder.resolve())
        models = []
        for entry in folder.iterdir():
            if entry.is_file() and entry.suffix.lower() == ".gguf":
                models.append(entry)
                if len(models) > 1:
                    return None
        return str(models[0].resolve()) if models else None
    except OSError:
        return None


def browse_models(path=None, offset=0, limit=100):
    if path is not None and (not isinstance(path, str) or any(c in path for c in "\x00\r\n")):
        raise ValueError("Invalid folder path.")
    if offset < 0:
        raise ValueError("Invalid page offset.")
    home = Path.home()
    if path:
        folder = Path(path).expanduser().resolve()
        if folder.is_file():
            folder = folder.parent
        if not folder.is_dir():
            raise ValueError("Folder does not exist.")
    else:
        folder = Path(os.getenv("LOCAL_MODEL_PATH", DEFAULT_MODEL_PATH)).expanduser().resolve()
        if not folder.is_dir():
            folder = folder.parent
        if not folder.is_dir():
            folder = home
    entries = []
    for entry in folder.iterdir():
        if entry.name.startswith('.'):
            continue
        try:
            is_dir = entry.is_dir()
            if is_dir or (entry.is_file() and entry.suffix.lower() == '.gguf'):
                entries.append({"name": entry.name, "path": str(entry.resolve()), "is_directory": is_dir})
        except OSError:
            continue
    entries.sort(key=lambda entry: (not entry['is_directory'], entry['name'].casefold()))
    candidates = [("home", home), ("lmstudio", home / '.lmstudio' / 'models'),
                  ("huggingface", home / '.cache' / 'huggingface' / 'hub'),
                  ("project", Path.cwd() / 'models')]
    if os.name == 'nt':
        candidates.extend((f'{letter}:', Path(f'{letter}:/')) for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')
    shortcuts = [{"name": name, "path": str(target.resolve())} for name, target in candidates if target.is_dir()]
    page = entries[offset:offset + limit]
    for entry in page:
        entry["selection_path"] = folder_model_path(Path(entry["path"])) if entry["is_directory"] else entry["path"]
    selection_path = folder_model_path(folder)
    return {"path": str(folder),
            "selection_path": selection_path,
            "breadcrumbs": [{"name": parent.name or str(parent), "path": str(parent)}
                            for parent in [*reversed(folder.parents), folder]], "parent": str(folder.parent),
            "can_select_directory": is_mlx_folder(folder),
            "entries": page, "offset": offset,
            "next_offset": offset + limit if offset + limit < len(entries) else None,
            "shortcuts": shortcuts}
