from pathlib import Path
from tempfile import TemporaryDirectory

from market_intelligence.configuration import load_bundle, safe_path


def save_markdown(root: Path, relative: str, original: str, replacement: str) -> None:
    """Validate a candidate scenario before replacing a single editable document."""
    bundle = load_bundle(root)
    editable = {skill.path for skill in bundle.skills.values()} | {
        name for name in bundle.files if Path(name).parts[0] == "knowledge"
    }
    if relative not in editable:
        raise ValueError("Only scenario skills and knowledge are editable here")
    target = safe_path(root, relative)
    if target.read_text(encoding="utf-8") != original:
        raise ValueError("This file changed since you opened it. Reload before saving.")
    with TemporaryDirectory(prefix="mip-validate-") as directory:
        candidate = Path(directory)
        for name, text in bundle.files.items():
            path = candidate / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(replacement if name == relative else text, encoding="utf-8")
        load_bundle(candidate)
    if target.read_text(encoding="utf-8") != original:
        raise ValueError("Concurrent edit detected. Reload before saving.")
    target.write_text(replacement, encoding="utf-8")
