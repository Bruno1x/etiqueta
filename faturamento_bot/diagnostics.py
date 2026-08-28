"""Diagnóstico local sem clicar, abrir janelas ou enviar documentos."""

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import platform

from .calibration import CalibrationManager
from .config import AppConfig
from .printing import find_required_printer, installed_printer_names
from .windows import find_unique_window, screen_metrics, virtual_screen_metrics


def collect_diagnostics(config: AppConfig) -> dict:
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "version": config.raw["project"]["version"],
        "python": platform.python_version(),
        "label_channels": config.processing["label_channels"],
        "delivery_window": config.processing["delivery_window"],
        "printing_implemented": False,
        "test_without_physical_print": config.raw["printing"]["test_without_physical_print"],
        "errors": {},
    }
    checks = {
        "monitor": lambda: asdict(screen_metrics()),
        "virtual_desktop": lambda: asdict(virtual_screen_metrics()),
        "reference_pack_present": lambda: CalibrationManager(config).reference_pack_ready(),
        "calibration": lambda: CalibrationManager(config).load_profile(),
        "sysemp_window": lambda: asdict(find_unique_window(
            config.target_window.get("title_regex"),
            config.target_window.get("process_path_regex"),
        )),
        "printers": installed_printer_names,
        "selected_printer": lambda: find_required_printer(
            installed_printer_names(), config.raw["printing"]["printer_name_contains"]
        ),
    }
    for name, check in checks.items():
        try:
            report[name] = check()
        except Exception as error:
            report["errors"][name] = str(error)
    return report


def save_diagnostics(config: AppConfig) -> Path:
    path = config.root / "runtime" / "diagnostics" / (
        datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(collect_diagnostics(config), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path
