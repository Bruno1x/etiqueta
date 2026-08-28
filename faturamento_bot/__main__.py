from __future__ import annotations

import argparse
import time

from .config import load_config
from .runner import RunMode, WorkflowRunner, configure_logging
from .simulator import simulate
from .windows import screen_metrics


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Automação de etiquetas do SYSEMP")
    subparsers = result.add_subparsers(dest="command", required=True)
    subparsers.add_parser("gui", help="Abre a interface gráfica")
    subparsers.add_parser("monitor", help="Mostra resolução e escala detectadas")
    subparsers.add_parser("plan", help="Lista as etapas configuradas")
    subparsers.add_parser("diagnose", help="Salva diagnóstico local sem cliques")

    for name in ("simulate", "run"):
        command = subparsers.add_parser(name)
        command.add_argument("--workflow", required=True)
        if name == "run":
            command.add_argument("--confirm-live", action="store_true")

    direct_test = subparsers.add_parser(
        "test-sysemp", help="Testa o fluxo de etiquetas sem imprimir"
    )
    direct_test.add_argument("--confirm-live", action="store_true", required=True)

    patrol = subparsers.add_parser("patrol")
    patrol.add_argument("--iterations", type=int, default=0, help="0 mantém a ronda contínua")
    patrol.add_argument("--confirm-live", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    config = load_config()
    configure_logging(config.root)

    if args.command == "diagnose":
        from .diagnostics import save_diagnostics

        print(save_diagnostics(config))
        return 0

    if args.command == "gui":
        from .gui import run_gui

        run_gui()
        return 0

    if args.command == "monitor":
        actual = screen_metrics()
        print(f"Físico: {actual.width}×{actual.height}")
        print(f"DPI: {actual.dpi} ({actual.scale_percent}%)")
        print(
            "Perfil: "
            f"{config.monitor.physical_width}×{config.monitor.physical_height} "
            f"a {config.monitor.scale_percent}%"
        )
        return 0

    if args.command == "plan":
        for workflow in config.workflows.values():
            print(f"\n{workflow.name}: {workflow.description}")
            for index, step in enumerate(workflow.steps, start=1):
                print(f"  {index:02d}. {step.label} [{step.action}]")
        return 0

    if args.command == "simulate":
        simulate(config, config.workflows[args.workflow])
        return 0

    if args.command == "run":
        runner = WorkflowRunner(
            config, RunMode(live=True, confirm_live=args.confirm_live,
                            safe_test=bool(config.raw["printing"]["test_without_physical_print"]))
        )
        runner.run(config.workflows[args.workflow])
        return 0

    if args.command == "test-sysemp":
        runner = WorkflowRunner(
            config,
            RunMode(live=True, confirm_live=args.confirm_live, safe_test=True),
        )
        runner.test_ecommerce_channel_cycle()
        return 0

    if args.command == "patrol":
        live = bool(args.confirm_live)
        runner = WorkflowRunner(config, RunMode.for_patrol(config, live))
        iteration = 0
        while args.iterations == 0 or iteration < args.iterations:
            iteration += 1
            for workflow_name in config.patrol["workflows"]:
                runner.run(config.workflows[workflow_name])
            if args.iterations == 0 or iteration < args.iterations:
                time.sleep(int(config.patrol["interval_seconds"]))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
