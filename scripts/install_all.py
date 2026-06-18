#!/usr/bin/env python3
"""Install every non-gitignored ESPHome YAML over WiFi (OTA).

For each config the script:
  1. compiles + uploads via OTA (WiFi) using `esphome run ... --device <name>.local
     --no-logs`, so the interactive "how do you want to upload?" prompt never
     appears and the upload always goes over WiFi.
  2. captures the first minute of device logs into a dated folder, one file per
     device.
  3. writes a markdown overview reporting whether each install succeeded.

Run with:  pixi run install
"""
from __future__ import annotations

import datetime as dt
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
LOG_SECONDS = 60  # how long to capture logs after a successful upload


# --------------------------------------------------------------------------- #
# YAML loading that tolerates ESPHome custom tags (!secret, !include, !lambda) #
# --------------------------------------------------------------------------- #
class _ESPHomeLoader(yaml.SafeLoader):
    pass


def _ignore_unknown(loader: yaml.Loader, tag_suffix: str, node: yaml.Node):
    """Turn any `!tag value` into a plain placeholder so parsing never fails."""
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_ESPHomeLoader.add_multi_constructor("!", _ignore_unknown)


def load_config(path: Path) -> dict | None:
    """Parse an ESPHome YAML, returning the top-level mapping (or None)."""
    try:
        data = yaml.load(path.read_text(), Loader=_ESPHomeLoader)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not parse {path.name}: {exc}")
        return None
    return data if isinstance(data, dict) else None


def device_name(config: dict) -> str | None:
    """Resolve the `esphome: name:` field, expanding ${substitutions}."""
    esp = config.get("esphome")
    if not isinstance(esp, dict):
        return None
    name = esp.get("name")
    if not isinstance(name, str):
        return None
    subs = config.get("substitutions") or {}
    for key, value in subs.items():
        if isinstance(value, str):
            name = name.replace(f"${{{key}}}", value).replace(f"${key}", value)
    return name.strip() or None


# --------------------------------------------------------------------------- #
# Locating configs                                                            #
# --------------------------------------------------------------------------- #
def git_yamls() -> list[Path]:
    """All .yaml/.yml files that are NOT ignored by .gitignore."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         "--", "*.yaml", "*.yml"],
        cwd=REPO, capture_output=True, text=True, check=True,
    )
    seen: list[Path] = []
    for line in out.stdout.splitlines():
        p = (REPO / line.strip())
        if p.is_file() and p not in seen:
            seen.append(p)
    return seen


def esphome_cmd() -> list[str]:
    """Use the esphome on PATH (inside the pixi env) or fall back to pixi run."""
    if shutil.which("esphome"):
        return ["esphome"]
    return ["pixi", "run", "esphome"]


# --------------------------------------------------------------------------- #
# Install + logging                                                           #
# --------------------------------------------------------------------------- #
def upload_ota(yaml_path: Path, name: str, upload_log: Path) -> bool:
    """Compile and upload over WiFi, retrying once after 10s. True on success."""
    cmd = esphome_cmd() + [
        "run", str(yaml_path),
        "--device", f"{name}.local",  # network address -> OTA over WiFi
        "--no-logs",
    ]
    with upload_log.open("w") as f:
        for attempt in (1, 2):
            print(f"  > attempt {attempt}: {' '.join(cmd)}")
            f.write(f"\n===== upload attempt {attempt} =====\n")
            f.flush()
            proc = subprocess.run(cmd, cwd=REPO, stdout=f,
                                  stderr=subprocess.STDOUT, text=True)
            if proc.returncode == 0:
                return True
            if attempt == 1:
                print("  ! upload failed, retrying in 10s...")
                time.sleep(10)
    return False


def capture_logs(yaml_path: Path, name: str, log_file: Path) -> bool:
    """Stream device logs for LOG_SECONDS, then stop. Returns True if captured."""
    cmd = esphome_cmd() + ["logs", str(yaml_path), "--device", f"{name}.local"]
    print(f"  > capturing {LOG_SECONDS}s of logs -> {log_file.name}")
    with log_file.open("w") as f:
        proc = subprocess.Popen(cmd, cwd=REPO, stdout=f,
                                stderr=subprocess.STDOUT, text=True)
        try:
            proc.wait(timeout=LOG_SECONDS)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    return log_file.exists() and log_file.stat().st_size > 0


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #
def main() -> int:
    now = dt.datetime.now()
    out_dir = REPO / "logs" / now.strftime("%Y-%m-%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    configs: list[tuple[Path, str]] = []
    for path in git_yamls():
        cfg = load_config(path)
        if cfg is None:
            continue
        name = device_name(cfg)
        if name is None:
            print(f"  - skipping {path.name} (no esphome: name:, e.g. secrets)")
            continue
        configs.append((path, name))

    if not configs:
        print("No ESPHome device configs found.")
        return 1

    print(f"Installing {len(configs)} device(s) over WiFi. Logs -> {out_dir}\n")

    results: list[dict] = []
    for path, name in configs:
        print(f"== {path.name}  (name: {name}) ==")
        stem = path.stem
        upload_log = out_dir / f"{stem}.upload.log"
        log_file = out_dir / f"{stem}.log"

        uploaded = upload_ota(path, name, upload_log)
        logged = False
        if uploaded:
            logged = capture_logs(path, name, log_file)
        else:
            print("  ! upload failed, skipping log capture")

        results.append({
            "yaml": path.name,
            "name": name,
            "uploaded": uploaded,
            "logged": logged,
            "upload_log": upload_log.name,
            "log": log_file.name if logged else "",
        })
        print()

    write_overview(out_dir, now, results)
    ok = sum(r["uploaded"] for r in results)
    print(f"Done: {ok}/{len(results)} uploaded successfully.")
    print(f"Overview: {out_dir / 'README.md'}")
    return 0 if ok == len(results) else 2


def write_overview(out_dir: Path, now: dt.datetime, results: list[dict]) -> None:
    ok = sum(r["uploaded"] for r in results)
    lines = [
        f"# ESPHome install overview — {now.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Upload method: **OTA (WiFi)** · {ok}/{len(results)} succeeded.",
        "",
        "| Device (YAML) | Name | Upload (OTA) | Log captured | Log file |",
        "| --- | --- | :---: | :---: | --- |",
    ]
    for r in results:
        up = "✅" if r["uploaded"] else "❌"
        lg = "✅" if r["logged"] else ("—" if not r["uploaded"] else "❌")
        log_ref = f"[{r['log']}]({r['log']})" if r["log"] else "—"
        lines.append(
            f"| {r['yaml']} | {r['name']} | {up} | {lg} | {log_ref} |"
        )
    lines.append("")
    (out_dir / "README.md").write_text("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
