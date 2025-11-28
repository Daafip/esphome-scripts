import re
import urllib.request
import json
from pathlib import Path


def get_latest_version(package: str = "esphome") -> str:
    """Fetch the latest version from PyPI."""
    url = f"https://pypi.org/pypi/{package}/json"
    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode())
    return data["info"]["version"]


def get_current_version(pixi_path: Path) -> str | None:
    """Extract the current esphome version from pixi.toml."""
    content = pixi_path.read_text()
    match = re.search(r'esphome\s*=\s*"==([^"]+)"', content)
    return match.group(1) if match else None


def update_pixi_toml(pixi_path: Path, new_version: str) -> None:
    """Update the esphome version in pixi.toml."""
    content = pixi_path.read_text()
    updated = re.sub(
        r'(esphome\s*=\s*"==)[^"]+"',
        f'\\g<1>{new_version}"',
        content
    )
    pixi_path.write_text(updated)


def main():
    pixi_path = Path(__file__).parent.parent / "pixi.toml"
    
    current = get_current_version(pixi_path)
    latest = get_latest_version()
    
    print(f"Current: {current}")
    print(f"Latest:  {latest}")
    
    if current != latest:
        print(f"\nNew version available! Updating pixi.toml...")
        update_pixi_toml(pixi_path, latest)
        print(f"Updated to {latest}. Run 'pixi install' to apply.")
    else:
        print("\nAlready up to date!")


if __name__ == "__main__":
    main()