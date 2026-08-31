from __future__ import annotations

import queue
import threading
import time
from copy import deepcopy
from dataclasses import replace
from . import __version__

from .calibration import AnchorSpec, CalibrationManager, CalibrationResult
from .config import AppConfig, load_config
from .runner import OperationCancelled, RunMode, WorkflowRunner, configure_logging
from .printing import find_required_printer, installed_printer_names
from .windows import enable_dpi_awareness, screen_metrics, virtual_screen_metrics
from .user_settings import load_channels, load_interval, save_channels, save_interval

enable_dpi_awareness()

import tkinter as tk
from tkinter import messagebox, ttk


class EtiquetasApp:
    def __init__(self, config: AppConfig) -> None:
        enable_dpi_awareness()
        self.config = config
        self.calibration = CalibrationManager(config)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self._task_minimized = False
        self.interval_minutes = load_interval(
            config.root, max(1, int(config.patrol['interval_seconds']) // 60))
        self.available_channels = tuple(config.processing['label_channels'])
        self.selected_channels = load_channels(config.root, self.available_channels)

        self.root = tk.Tk()
        self.root.title(f"Etiquetas Bot — SYSEMP — {__version__}")
        self.root.geometry("920x720")
        self.root.minsize(820, 650)
        self.root.configure(bg="#0f1923")
        self._build_ui()
        self.root.after(120, self._consume_events)
        self._refresh_environment()

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#0f1923")
        style.configure("TLabel", background="#0f1923", foreground="#eaf0f6")
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("Info.TLabel", foreground="#9db0c2")
        style.configure("TButton", padding=(12, 9), font=("Segoe UI", 10, "bold"))
        style.configure("Accent.TButton", background="#2b7fff", foreground="white")
        style.configure("Danger.TButton", background="#bd3b3b", foreground="white")

        shell = ttk.Frame(self.root, padding=24)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="Etiquetas Bot", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            shell,
            text="Impressão de etiquetas do Mercado Livre no SYSEMP",
            style="Info.TLabel",
        ).pack(anchor="w", pady=(2, 18))

        status_frame = ttk.Frame(shell)
        status_frame.pack(fill="x", pady=(0, 16))
        self.environment_var = tk.StringVar(value="Verificando ambiente…")
        self.profile_var = tk.StringVar(value="Perfil: não verificado")
        self.printer_var = tk.StringVar(value="Impressora configurada: verificando…")
        ttk.Label(status_frame, textvariable=self.environment_var).pack(anchor="w")
        ttk.Label(status_frame, textvariable=self.profile_var, style="Info.TLabel").pack(
            anchor="w", pady=(4, 0)
        )
        ttk.Label(status_frame, textvariable=self.printer_var, style="Info.TLabel").pack(
            anchor="w", pady=(4, 0)
        )

        buttons = ttk.Frame(shell)
        buttons.pack(fill="x", pady=(0, 10))
        ttk.Button(
            buttons,
            text="INICIAR RONDA DE IMPRESSÃO",
            style="Accent.TButton",
            command=self.start_patrol,
        ).grid(row=0, column=0, columnspan=2, padx=(0, 8), pady=4, sticky="ew")
        ttk.Button(
            buttons,
            text="PARAR",
            style="Danger.TButton",
            command=self.stop_patrol,
        ).grid(row=0, column=2, padx=8, pady=4, sticky="ew")
        ttk.Button(buttons, text='ATUALIZAR SISTEMA', command=self.check_updates).grid(
            row=1, column=2, padx=8, pady=4, sticky='ew')
        ttk.Button(buttons, text='AUTO CALIBRAR TELA', style='Accent.TButton',
                   command=self.auto_calibrate).grid(
            row=1, column=0, columnspan=2, padx=(0, 8), pady=4, sticky='ew')
        for column in range(3):
            buttons.columnconfigure(column, weight=1)

        timer = ttk.Frame(shell)
        timer.pack(fill='x', pady=(0, 8))
        ttk.Label(timer, text='Nova ronda após').pack(side='left')
        self.interval_var = tk.StringVar(value=str(self.interval_minutes))
        ttk.Spinbox(timer, from_=1, to=1440, width=7, justify='center',
                    textvariable=self.interval_var).pack(side='left', padx=8)
        ttk.Label(timer, text='minuto(s) do término').pack(side='left')
        ttk.Button(timer, text='SALVAR INTERVALO', command=self.save_patrol_interval).pack(side='right')

        stores = ttk.LabelFrame(shell, text='Lojas da ronda', padding=(10, 7))
        stores.pack(fill='x', pady=(0, 8))
        self.channel_vars: dict[str, tk.BooleanVar] = {}
        for index, channel in enumerate(self.available_channels):
            variable = tk.BooleanVar(value=channel in self.selected_channels)
            self.channel_vars[channel] = variable
            ttk.Checkbutton(stores, text=channel, variable=variable).grid(
                row=index // 4, column=index % 4, padx=(0, 12), pady=2, sticky='w')
        for column in range(4):
            stores.columnconfigure(column, weight=1)
        store_actions = ttk.Frame(stores)
        store_actions.grid(row=2, column=0, columnspan=4, pady=(6, 0), sticky='ew')
        ttk.Button(store_actions, text='SELECIONAR TODAS', command=self.select_all_channels).pack(side='left')
        ttk.Button(store_actions, text='SALVAR LOJAS', command=self.save_store_selection).pack(side='right')

        self.live_var = tk.BooleanVar(value=True)
        self.advanced_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(shell, text='Mostrar ferramentas avançadas',
                        variable=self.advanced_visible, command=self._toggle_advanced).pack(anchor='w', pady=(0, 8))
        self.advanced_frame = ttk.Frame(shell)
        advanced_buttons = (
            ('Calibração manual', self.guided_calibration),
            ('Testar pontos', self.test_points),
            ('Teste sem imprimir', self.test_sysemp_flow),
            ('Imprimir somente 1 pedido', self.print_one_order),
            ('Atualizar status', self._refresh_environment),
        )
        for index, (label, command) in enumerate(advanced_buttons):
            ttk.Button(self.advanced_frame, text=label, command=command).grid(
                row=index // 3, column=index % 3, padx=4, pady=4, sticky='ew')
        for column in range(3):
            self.advanced_frame.columnconfigure(column, weight=1)

        self.activity_label = ttk.Label(shell, text="Atividade")
        self.activity_label.pack(anchor="w", pady=(4, 6))
        self.log = tk.Text(
            shell,
            height=16,
            bg="#09121a",
            fg="#dbe7f2",
            insertbackground="white",
            relief="flat",
            padx=12,
            pady=10,
            font=("Consolas", 10),
            state="disabled",
        )
        self.log.pack(fill="both", expand=True)

    def _toggle_advanced(self):
        if self.advanced_visible.get():
            self.advanced_frame.pack(fill='x', pady=(0, 10), before=self.activity_label)
        else:
            self.advanced_frame.pack_forget()

    def save_patrol_interval(self, *, notify=True):
        try:
            self.interval_minutes = save_interval(self.config.root, self.interval_var.get())
        except (OSError, ValueError) as error:
            messagebox.showerror('Intervalo inválido', str(error))
            return None
        self.interval_var.set(str(self.interval_minutes))
        self._append_log(f'Intervalo salvo: nova ronda {self.interval_minutes} minuto(s) após o término.')
        if notify:
            messagebox.showinfo('Intervalo salvo', f'Nova ronda após {self.interval_minutes} minuto(s).')
        return self.interval_minutes

    def _checked_channels(self):
        return tuple(
            channel for channel in self.available_channels
            if self.channel_vars[channel].get()
        )

    def select_all_channels(self):
        for variable in self.channel_vars.values():
            variable.set(True)

    def save_store_selection(self, *, notify=True):
        try:
            self.selected_channels = save_channels(
                self.config.root,
                self._checked_channels(),
                self.available_channels,
            )
        except (OSError, ValueError) as error:
            messagebox.showerror('Lojas inválidas', str(error))
            return None
        names = ', '.join(self.selected_channels)
        self._append_log(f'Lojas salvas para a ronda: {names}.')
        if notify:
            messagebox.showinfo('Lojas salvas', f'A ronda pesquisará somente: {names}.')
        return self.selected_channels

    def _config_for_channels(self, channels):
        raw = deepcopy(self.config.raw)
        raw['processing']['label_channels'] = list(channels)
        return replace(self.config, raw=raw)

    def _selected_run_config(self):
        channels = self.save_store_selection(notify=False)
        if channels is None:
            return None
        return self._config_for_channels(channels)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _refresh_environment(self) -> None:
        try:
            metrics = screen_metrics()
            virtual = virtual_screen_metrics()
            self.environment_var.set(
                f"Tela detectada: {metrics.width}×{metrics.height} — "
                f"{metrics.scale_percent}% — {metrics.dpi} DPI — "
                f"{virtual.monitor_count} monitor(es)"
            )
            profile = self.calibration.load_profile()
            if self.calibration.reference_pack_ready():
                version = self.calibration.reference_matcher.version
                if profile.get("reference_pack_version") == version:
                    status = profile.get("status", "não executado")
                else:
                    status = "aguardando Auto calibrar"
                self.profile_var.set(
                    f"Reconhecimento de tela: pacote v{version} — {status} (não valida o fluxo)"
                )
            elif profile:
                count = len(profile.get("anchors", {}))
                total = len(self.calibration.anchor_specs())
                self.profile_var.set(
                    f"Perfil deste computador: {count}/{total} referências capturadas"
                )
            else:
                self.profile_var.set("Perfil deste computador: ainda não criado")
            required = str(self.config.raw["printing"]["printer_name_contains"])
            printer = find_required_printer(installed_printer_names(), required)
            self.printer_var.set(
                f"Impressora da ronda: {printer}"
                if printer
                else f"Impressora da ronda: nenhuma fila {required} encontrada"
            )
        except Exception as error:
            self.environment_var.set(f"Falha ao medir a tela: {error}")

    def _background(self, task, success_label: str, minimize: bool = False) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Operação em andamento", "Aguarde a operação atual.")
            return
        self.stop_event.clear()
        if minimize:
            self._task_minimized = True
            self.root.iconify()

        def execute() -> None:
            try:
                result = task()
                self.events.put(("success", (success_label, result)))
            except OperationCancelled as error:
                self.events.put(("success", ("Parada", str(error))))
            except Exception as error:
                self.events.put(("error", error))

        self.worker = threading.Thread(target=execute, daemon=True)
        self.worker.start()

    def auto_calibrate(self) -> None:
        self._append_log("Autocalibração iniciada. Abra a tela desejada no SYSEMP.")
        self._background(self.calibration.auto_calibrate, "Autocalibração")

    def check_updates(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning('Ronda em andamento', 'Pare a ronda e aguarde o encerramento antes de atualizar.')
            return
        if not messagebox.askokcancel('Verificar atualizações',
                'Consultar a versão publicada em Bruno1x/etiqueta e baixar se houver atualização? '
                'A instalação só será ativada após sua confirmação para reiniciar.'):
            return
        def download():
            from .updater import latest, prepare_update
            release = latest(__version__)
            if release is None:
                return 'Nenhuma versão mais recente publicada no GitHub.'
            return {'prepared_update': prepare_update(self.config, release)}
        self._background(download, 'Atualizações')

    def test_points(self) -> None:
        self._append_log("Testando referências visíveis na tela atual…")
        self._background(self.calibration.validate_all, "Teste de pontos")

    def guided_calibration(self) -> None:
        specs = self.calibration.anchor_specs()
        if not specs:
            messagebox.showerror("Sem pontos", "Nenhum ponto foi configurado.")
            return
        GuidedCalibrationDialog(self, specs)

    def start_patrol(self) -> None:
        interval_minutes = self.save_patrol_interval(notify=False)
        if interval_minutes is None:
            return
        run_config = self._selected_run_config()
        if run_config is None:
            return
        channels = tuple(run_config.processing['label_channels'])
        live = True
        physical = live and not run_config.raw['printing']['test_without_physical_print']
        if physical:
            required = run_config.raw['printing']['printer_name_contains']
            if not messagebox.askokcancel(
                'Iniciar ronda de impressão real',
                f'A ronda imprimirá os pedidos verdes e não impressos de {len(channels)} loja(s), um por vez:\n'
                f'{", ".join(channels)}\n\n'
                f'Confirme Etiqueta + Documentos configurado no SYSEMP para {required}: transporte + DANFE, 100 × 150 mm cada, uma cópia.\n\n'
                f'Nova passagem após {interval_minutes} minuto(s) do término. '
                'Deixe a cópia da célula em Sim e não use este computador durante a execução. '
                'Em resultado incerto, a ronda será interrompida. Iniciar?',
            ):
                return
        self._append_log(
            "Ronda iniciada com cliques reais." if live else "Ronda de teste iniciada."
        )

        def patrol() -> str:
            runner = WorkflowRunner(
                run_config,
                RunMode.for_patrol(run_config, live),
                stop_event=self.stop_event,
            )
            runner.print_routing_confirmed = physical
            while not self.stop_event.is_set():
                for name in run_config.patrol["workflows"]:
                    if self.stop_event.is_set():
                        break
                    runner.run(run_config.workflows[name])
                interval_seconds = interval_minutes * 60
                runner.log.info('Aguardando %s minuto(s) para a próxima ronda.', interval_minutes)
                if self.stop_event.wait(interval_seconds):
                    break
            return "Ronda encerrada."

        self._background(patrol, "Ronda", minimize=live)

    def test_sysemp_flow(self) -> None:
        if not self.calibration.reference_pack_ready():
            messagebox.showerror(
                "Referências ausentes",
                "O pacote automático de telas não está instalado.",
            )
            return

        run_config = self._selected_run_config()
        if run_config is None:
            return
        channels = tuple(run_config.processing['label_channels'])

        if not messagebox.askokcancel(
            "Testar no SYSEMP",
            f"O teste fará cliques reais em {len(channels)} loja(s): {', '.join(channels)}. "
            "Ele preencherá "
            "os filtros. Nenhuma etiqueta será impressa. Continuar?",
        ):
            return

        self._append_log("Teste de etiquetas iniciado: nenhuma impressão será feita.")

        def execute_test() -> str:
            runner = WorkflowRunner(
                run_config,
                RunMode(live=True, confirm_live=True, safe_test=True),
                stop_event=self.stop_event,
            )
            runner.test_ecommerce_channel_cycle()
            return (
                f"Filtros de {len(channels)} loja(s) percorridos, sem imprimir. "
                "A grade de etiquetas ainda não foi lida automaticamente."
            )

        self._background(execute_test, "Teste direto", minimize=True)

    def stop_patrol(self) -> None:
        self.stop_event.set()
        self._append_log("Solicitação de parada enviada.")

    def print_one_order(self) -> None:
        if not self.live_var.get():
            messagebox.showwarning('Permissão necessária', 'Marque Permitir cliques reais para fazer uma impressão física.')
            return
        run_config = self._selected_run_config()
        if run_config is None:
            return
        channels = tuple(run_config.processing['label_channels'])
        required = run_config.raw['printing']['printer_name_contains']
        if not messagebox.askokcancel(
            'Impressão física de um pedido',
            f'O bot seguirá o mesmo caminho do teste para: {", ".join(channels)}.\n\n'
            f'Confirme que Etiqueta + Documentos está configurado NO SYSEMP para envio direto à {required}, transporte + DANFE de 100 × 150 mm, uma cópia.\n\n'
            'O bot não altera o destino interno do SYSEMP. A cópia da célula ao clicar deve estar em Sim.\n\n'
            'Será enviado apenas um pedido verde e não impresso da loja pesquisada. Lojas sem candidato visível serão desmarcadas antes da próxima. Não use mouse/teclado durante o teste. Confirmar envio real?',
        ):
            return
        self._append_log('Teste real autorizado: um pedido; sem repetição automática.')
        def execute():
            from .print_desktop import run_print_test_flow
            runner = WorkflowRunner(run_config, RunMode(live=True, confirm_live=True, safe_test=True), stop_event=self.stop_event)
            return run_print_test_flow(runner, routing_confirmed=True)
        self._background(execute, 'Teste de impressão real', minimize=True)

    def _consume_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind in ('error', 'success') and self._task_minimized:
                    self._task_minimized = False
                    self.root.deiconify()
                if kind == "error":
                    self._append_log(f"ERRO: {payload}")
                    messagebox.showerror("Operação interrompida", str(payload))
                elif kind == "success":
                    label, result = payload
                    if isinstance(result, dict) and 'prepared_update' in result:
                        prepared = result['prepared_update']
                        if messagebox.askokcancel('Atualização pronta',
                                f'Versão {prepared["tag"]} baixada e checksum conferido. Fechar e reiniciar atualizado agora?'):
                            from .updater import activate_on_close
                            try:
                                activate_on_close(prepared)
                            except Exception as error:
                                messagebox.showerror('Atualização não aplicada', str(error))
                            else:
                                self.root.destroy()
                                return
                        continue
                    if isinstance(result, CalibrationResult):
                        self._append_log(f"{label}: {result.message}")
                        if result.detected:
                            self._show_points(result)
                    else:
                        self._append_log(f"{label}: {result}")
                    self._refresh_environment()
                elif kind == "guided":
                    spec, x, y, path, dialog = payload
                    dialog.restore_after_capture(
                        f"Ponto {spec.label!r} capturado em ({x}, {y}): {path.name}"
                    )
                elif kind == "guided_error":
                    error, dialog = payload
                    dialog.restore_after_capture(f"ERRO na captura guiada: {error}")
                    messagebox.showerror("Falha na captura", str(error))
        except queue.Empty:
            pass
        self.root.after(120, self._consume_events)

    def _show_points(self, result: CalibrationResult) -> None:
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.72)
        virtual = virtual_screen_metrics()
        overlay.geometry(
            f"{virtual.width}x{virtual.height}{virtual.left:+d}{virtual.top:+d}"
        )
        canvas = tk.Canvas(overlay, bg="#061018", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        for item in result.detected:
            canvas.create_oval(
                item.x - 18,
                item.y - 18,
                item.x + 18,
                item.y + 18,
                outline="#36e27b",
                width=5,
            )
            canvas.create_text(
                item.x + 25,
                item.y,
                anchor="w",
                fill="white",
                font=("Segoe UI", 12, "bold"),
                text=f"{item.name}  {item.score:.0%}",
            )
        canvas.create_text(
            30,
            28,
            anchor="nw",
            fill="white",
            font=("Segoe UI", 16, "bold"),
            text="Pontos reconhecidos — esta tela fecha em 5 segundos",
        )
        overlay.after(5000, overlay.destroy)

    def run(self) -> None:
        def close() -> None:
            self.stop_event.set()
            self.root.destroy()

        self.root.protocol("WM_DELETE_WINDOW", close)
        self.root.mainloop()


class GuidedCalibrationDialog:
    def __init__(self, app: EtiquetasApp, specs: tuple[AnchorSpec, ...]) -> None:
        self.app = app
        self.specs = specs
        self.index = 0
        self.window = tk.Toplevel(app.root)
        self.window.title("Calibração guiada")
        self.window.geometry("700x360")
        self.window.transient(app.root)
        self.window.grab_set()

        frame = ttk.Frame(self.window, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Calibração guiada", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text=(
                "Abra manualmente a tela indicada no SYSEMP. Ao capturar, a janela "
                "será ocultada por 5 segundos; apenas posicione o mouse no ponto exato."
            ),
            wraplength=640,
            style="Info.TLabel",
        ).pack(anchor="w", pady=(8, 20))
        self.counter_var = tk.StringVar()
        self.label_var = tk.StringVar()
        self.file_var = tk.StringVar()
        ttk.Label(frame, textvariable=self.counter_var).pack(anchor="w")
        ttk.Label(
            frame,
            textvariable=self.label_var,
            font=("Segoe UI", 13, "bold"),
            wraplength=640,
        ).pack(anchor="w", pady=(8, 4))
        ttk.Label(frame, textvariable=self.file_var, style="Info.TLabel").pack(anchor="w")

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(28, 0))
        ttk.Button(controls, text="Anterior", command=self.previous).pack(side="left")
        ttk.Button(
            controls,
            text="Capturar este ponto em 5 s",
            style="Accent.TButton",
            command=self.capture,
        ).pack(side="left", padx=10)
        ttk.Button(controls, text="Próximo", command=self.next).pack(side="left")
        ttk.Button(controls, text="Fechar", command=self.window.destroy).pack(side="right")
        self.refresh()

    def refresh(self) -> None:
        spec = self.specs[self.index]
        self.counter_var.set(f"Ponto {self.index + 1} de {len(self.specs)}")
        self.label_var.set(spec.label)
        self.file_var.set(f"Referência: {spec.name}")

    def previous(self) -> None:
        self.index = max(0, self.index - 1)
        self.refresh()

    def next(self) -> None:
        self.index = min(len(self.specs) - 1, self.index + 1)
        self.refresh()

    def capture(self) -> None:
        spec = self.specs[self.index]
        self.window.grab_release()
        self.window.withdraw()
        self.app.root.withdraw()

        def execute() -> None:
            try:
                import pyautogui

                time.sleep(5)
                point = pyautogui.position()
                path = self.app.calibration.capture_anchor_at(spec, point.x, point.y)
                self.app.events.put(
                    ("guided", (spec, point.x, point.y, path, self))
                )
            except Exception as error:
                self.app.events.put(("guided_error", (error, self)))

        threading.Thread(target=execute, daemon=True).start()

    def restore_after_capture(self, message: str) -> None:
        self.app.root.deiconify()
        self.window.deiconify()
        self.window.grab_set()
        self.app._append_log(message)
        self.app._refresh_environment()
        if self.index < len(self.specs) - 1:
            self.index += 1
            self.refresh()


def run_gui() -> None:
    config = load_config()
    configure_logging(config.root)
    EtiquetasApp(config).run()
