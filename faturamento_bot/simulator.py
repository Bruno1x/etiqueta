from __future__ import annotations

from .config import AppConfig, Workflow
from .windows import enable_dpi_awareness


def simulate(config: AppConfig, workflow: Workflow) -> None:
    enable_dpi_awareness()
    import tkinter as tk

    width = config.monitor.physical_width
    height = config.monitor.physical_height
    points = [step for step in workflow.steps if step.x_ratio is not None]

    root = tk.Tk()
    root.title(f"Simulação segura — {workflow.name}")
    root.geometry(f"{width}x{height}+0+0")
    root.attributes("-topmost", True)
    root.configure(bg="#0c1722")

    canvas = tk.Canvas(root, width=width, height=height, bg="#0c1722", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        40,
        36,
        anchor="nw",
        fill="#f4f7fa",
        font=("Segoe UI", 22, "bold"),
        text=f"{workflow.description} — {width}×{height} / {config.monitor.scale_percent}%",
    )
    canvas.create_text(
        40,
        82,
        anchor="nw",
        fill="#8fa4b8",
        font=("Segoe UI", 13),
        text="Simulação: nenhum clique será enviado. Esc fecha esta tela.",
    )

    state = {"index": 0, "marker": None, "label": None}

    def show_next() -> None:
        if not points:
            return
        step = points[state["index"] % len(points)]
        x = round(step.x_ratio * width)
        y = round(step.y_ratio * height)
        if state["marker"]:
            canvas.delete(state["marker"])
            canvas.delete(state["label"])
        state["marker"] = canvas.create_oval(
            x - 18, y - 18, x + 18, y + 18, outline="#ff6b35", width=5
        )
        state["label"] = canvas.create_text(
            min(x + 28, width - 520),
            max(y - 8, 130),
            anchor="w",
            fill="#ffffff",
            font=("Segoe UI", 15, "bold"),
            text=f"{state['index'] + 1}. {step.label}\n({x}, {y})",
        )
        state["index"] = (state["index"] + 1) % len(points)
        root.after(1300, show_next)

    root.bind("<Escape>", lambda _event: root.destroy())
    show_next()
    root.mainloop()
