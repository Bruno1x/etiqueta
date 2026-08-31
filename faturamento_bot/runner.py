from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
from pathlib import Path
import re
import time
from threading import Event

from .config import AppConfig, Step, Workflow
from .calibration import CalibrationManager
from .reference import ReferenceScreenMatcher
from .printing import find_required_printer, installed_printer_names
from .label_policy import delivery_window
from .windows import (
    activate_and_maximize,
    find_unique_window,
    foreground_matches,
    foreground_title,
    screen_metrics,
    virtual_screen_metrics,
)


@dataclass(frozen=True)
class RunMode:
    live: bool = False
    confirm_live: bool = False
    safe_test: bool = False

    @classmethod
    def for_patrol(cls, config: AppConfig, live: bool) -> "RunMode":
        return cls(
            live=live, confirm_live=live,
            safe_test=bool(config.raw["printing"]["test_without_physical_print"]),
        )


class SafetyError(RuntimeError):
    pass


# Visual order of the fixed SYSEMP CheckedComboBoxEdit. Keeping the complete
# list is essential: the operator may search only some ML stores, but keyboard
# navigation still starts at the first item in the control.
ECOMMERCE_CHANNEL_INDEX = {
    # After Home, the first Down enters the first item (AMAZON). Therefore the
    # key count is the zero-based item index plus one.
    'ML CENTRAL': 15,
    'ML DISTRIBUIDOR': 16,
    'ML FABRICA': 17,
    'ML HERO BAND': 18,
    'ML POOLSY': 19,
    'ML SHOPPING': 20,
    'ML STORE': 21,
    'ML UNIVERSO': 22,
}


class OperationCancelled(RuntimeError):
    pass


class WorkflowRunner:
    def __init__(self, config: AppConfig, mode: RunMode, stop_event: Event | None = None) -> None:
        self.config = config
        self.mode = mode
        self.log = logging.getLogger("faturamento_bot")
        self.calibration = CalibrationManager(config)
        self.reference_matcher = ReferenceScreenMatcher(config)
        self._delivery_dates: tuple[date, date] | None = None
        self.stop_event = stop_event or Event()
        self.print_routing_confirmed = False

    def _check_cancelled(self) -> None:
        if self.stop_event.is_set():
            raise OperationCancelled("Operação parada. Nenhum próximo clique será enviado.")

    def _check_input(self) -> None:
        self._check_cancelled()
        if not foreground_matches(
            self.config.target_window.get("title_regex"),
            self.config.target_window.get("process_path_regex"),
        ):
            raise SafetyError("O foco saiu do SYSEMP; entrada interrompida.")

    def validate_environment(self) -> None:
        self._check_cancelled()
        if self.mode.live:
            if self.mode.safe_test and not self.config.safety["allow_sysemp_test"]:
                raise SafetyError("O teste direto no SYSEMP está desabilitado.")
            if not self.mode.safe_test and not self.config.safety["allow_live"]:
                raise SafetyError("Cliques reais estão desabilitados na configuração.")
            if self.config.safety["require_live_flag"] and not self.mode.confirm_live:
                raise SafetyError("Use --confirm-live para autorizar esta execução.")

            if not self.mode.safe_test:
                printing = self.config.raw["printing"]
                required = str(printing["printer_name_contains"])
                printer = find_required_printer(installed_printer_names(), required)
                if printer is None:
                    raise SafetyError(
                        f"Impressora obrigatória {required!r} não encontrada. "
                        "A ronda real foi bloqueada antes de imprimir qualquer etiqueta."
                    )
                self.log.info("Impressora validada para a ronda: %s", printer)
                if not self.print_routing_confirmed:
                    raise SafetyError('Confirme o destino da impressão na janela Iniciar ronda.')

        actual = screen_metrics()
        if self.config.safety["fail_on_monitor_mismatch"]:
            profile = self.calibration.load_profile()
            profile_monitor = profile.get("monitor", {})
            if profile_monitor:
                expected_width = int(profile_monitor["width"])
                expected_height = int(profile_monitor["height"])
                expected_scale = int(profile_monitor["scale_percent"])
                expected_source = "perfil calibrado deste computador"
            else:
                expected_width = self.config.monitor.physical_width
                expected_height = self.config.monitor.physical_height
                expected_scale = self.config.monitor.scale_percent
                expected_source = "configuração inicial"
            actual_tuple = (actual.width, actual.height, actual.scale_percent)
            expected_tuple = (expected_width, expected_height, expected_scale)
            if actual_tuple != expected_tuple:
                raise SafetyError(
                    "Monitor divergente. "
                    f"Esperado pelo {expected_source}: {expected_tuple}; "
                    f"detectado: {actual_tuple}. Execute Auto calibrar novamente."
                )


    def run(self, workflow: Workflow) -> None:
        if workflow.name == "ecommerce_labels":
            if not self.mode.live:
                for channel in self.config.processing["label_channels"]:
                    self._check_cancelled()
                    self.log.info("Simulação sem cliques: pesquisar %s", channel)
                return
            if self.mode.safe_test:
                self.test_ecommerce_channel_cycle()
            else:
                from .print_desktop import run_print_patrol
                run_print_patrol(self)
            return
        self.validate_environment()
        self._delivery_dates = delivery_window(
            self.config.processing["delivery_window"], date.today()
        )
        self.log.info("Iniciando workflow %s: %s", workflow.name, workflow.description)

        window = None
        if self.mode.live:
            window = find_unique_window(
                title_regex=self.config.target_window.get("title_regex"),
                process_path_regex=self.config.target_window.get("process_path_regex"),
            )
            if self.config.target_window["maximize_before_run"]:
                activate_and_maximize(window)
                time.sleep(1.0)

        for index, step in enumerate(workflow.steps, start=1):
            self.log.info("%02d/%02d %s", index, len(workflow.steps), step.label)
            if not self.mode.live:
                continue
            self._execute_live(step)

        self.log.info("Workflow %s concluído", workflow.name)

    def _click_reference(
        self,
        screen_id: str,
        reference_x: int,
        reference_y: int,
        pause_seconds: float = 0.8,
    ) -> None:
        import pyautogui

        self._check_cancelled()

        point = self.reference_matcher.locate_point(
            screen_id, reference_x, reference_y
        )
        if point is None:
            raise SafetyError(f"Tela esperada não encontrada: {screen_id}.")
        if not foreground_matches(
            self.config.target_window.get("title_regex"),
            self.config.target_window.get("process_path_regex"),
        ):
            raise SafetyError("O foco saiu do SYSEMP antes do clique.")
        self._check_input()
        pyautogui.click(point.x, point.y)
        time.sleep(pause_seconds)

    @staticmethod
    def _channel_anchor(channel: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", channel.casefold()).strip("_")
        return f"channels/{slug}.png"

    @staticmethod
    def _checkbox_is_checked(x: int, y: int) -> bool:
        import numpy as np
        from PIL import ImageGrab

        rgb = np.array(
            ImageGrab.grab(
                bbox=(x - 7, y - 7, x + 8, y + 8),
                all_screens=True,
            ).convert("RGB")
        )
        # Distinguish the interior check mark from the orange focus border.
        center = rgb[3:12, 3:12].astype(float)
        orange = ((center[:, :, 0] > 190) & (center[:, :, 1] > 90)
                  & (center[:, :, 1] < 225) & (center[:, :, 2] < 110))
        if int(orange.sum()) >= 4:
            interior = rgb[4:11, 4:11].astype(float)
            check_mark = ((interior[:, :, 0] > 180)
                          & (interior[:, :, 1] < 160)
                          & (interior[:, :, 2] < 110))
            return int(check_mark.sum()) >= 6
        interior = rgb[5:10, 5:10].astype(float)
        if float(interior.mean()) > 180 and float(np.ptp(interior, axis=2).max()) < 25:
            return False
        checkbox = np.mean(rgb, axis=2)
        return int((checkbox > 150).sum()) >= 8 and float(checkbox.std()) >= 18.0

    def _set_checklist_value(
        self,
        screen_id: str,
        field_x: int,
        field_y: int,
        anchor: str,
        label: str,
        selected: bool,
        dropdown_height: int | None = None,
        scrollbar_offset: int | None = None,
        force_click: bool = False,
    ) -> None:
        import pyautogui

        self._check_cancelled()
        matched = self.reference_matcher.match(screen_id)
        if matched is None:
            raise SafetyError(f"Campo não encontrado para selecionar {label}.")
        field = self.reference_matcher.map_point(matched, field_x, field_y)
        if field is None:
            raise SafetyError(f"Campo não encontrado para selecionar {label}.")
        if (screen_id == 'ecommerce_manager' and field_y == 211
                and self.mode.live and label in ECOMMERCE_CHANNEL_INDEX):
            self._set_ecommerce_channel_by_keyboard(
                field, anchor, label, selected
            )
            return
        virtual = virtual_screen_metrics()
        if dropdown_height is None:
            dropdown_height = 440 if screen_id == "invoice_main" else 190
        if scrollbar_offset is None:
            scrollbar_offset = 202 if screen_id == "invoice_main" else 228
        region = (
            field.x - 240,
            field.y + 8,
            field.x + scrollbar_offset + 4,
            min(
                field.y + dropdown_height,
                virtual.top + virtual.height - 30,
            ),
        )
        scrollbar_x = field.x + scrollbar_offset
        down_arrow_y = region[3] - 12
        checkbox_x_fixed = None
        up_arrow_y = region[1] + 12
        if screen_id == "ecommerce_manager" and field_y == 211:
            # Mapear os limites reais, não deslocamentos fixos do centro.
            # O limite antigo (450 - 240) cortava o início do texto em x=207.
            first = self.reference_matcher.map_point(matched, 180, 225)
            last = self.reference_matcher.map_point(matched, 699, 398)
            arrow = self.reference_matcher.map_point(matched, 689, 385)
            checkbox = self.reference_matcher.map_point(matched, 192, 235)
            region = (first.x, first.y, last.x, last.y)
            scrollbar_x, down_arrow_y = arrow.x, arrow.y
            checkbox_x_fixed = checkbox.x
            up_arrow_y = self.reference_matcher.map_point(matched, 689, 235).y

        self._check_input()
        pyautogui.click(field.x, field.y)
        time.sleep(0.5)

        # Primeiro examina a posição atual; só então avança uma linha.
        # Ao atingir o fim, permite voltar para encontrar lojas acima, inclusive
        # quando uma nova ronda começa com a lista na posição da ronda anterior.
        direction_down = True
        unchanged = 0
        previous_view = None
        # The checklist contains far fewer rows than this. The hard bound is a
        # safety guard: theme animations must never create an endless scroll.
        max_attempts = 56
        for _attempt in range(max_attempts):
            self._check_cancelled()
            item = self.calibration.locate_anchor(
                anchor, region=region, min_score=0.80
            )
            if item is not None:
                checkbox_x = (
                    checkbox_x_fixed if checkbox_x_fixed is not None
                    else item.x - item.width // 2 - 11
                )
                currently_selected = self._checkbox_is_checked(checkbox_x, item.y)
                if force_click:
                    if not selected:
                        pyautogui.press("escape")
                        raise SafetyError('Clique forçado somente pode ser usado para marcar uma loja.')
                    self._check_input()
                    pyautogui.click(checkbox_x, item.y)
                    time.sleep(0.35)
                    if self._checkbox_is_checked(checkbox_x, item.y) != selected:
                        pyautogui.press("escape")
                        raise SafetyError(f"Não foi possível confirmar a seleção de {label}.")
                elif currently_selected != selected:
                    self._check_input()
                    pyautogui.click(checkbox_x, item.y)
                    time.sleep(0.35)
                    if self._checkbox_is_checked(checkbox_x, item.y) != selected:
                        pyautogui.press("escape")
                        raise SafetyError(f"Não foi possível confirmar a seleção de {label}.")
                self._check_input()
                pyautogui.press("escape")
                time.sleep(0.35)
                state = "marcado" if selected else "desmarcado"
                self.log.info("Checklist confirmado: %s — %s", label, state)
                return
            from PIL import ImageGrab

            view_image = ImageGrab.grab(bbox=region, all_screens=True).convert("L")
            # Ignore the scrollbar and quantize the list. Its moving thumb,
            # hover border and antialiasing otherwise prevent end detection.
            content_width = max(1, view_image.width - 36)
            view_image = view_image.crop((0, 0, content_width, view_image.height))
            signature_width = min(96, view_image.width)
            signature_height = min(48, view_image.height)
            view = view_image.resize((signature_width, signature_height)).point(
                lambda value: (value // 16) * 16
            ).tobytes()
            unchanged = unchanged + 1 if view == previous_view else 0
            previous_view = view
            if unchanged >= 2:
                if not direction_down:
                    break
                direction_down = False
                unchanged = 0
                previous_view = None
            self._check_input()
            pyautogui.click(
                scrollbar_x, down_arrow_y if direction_down else up_arrow_y
            )
            time.sleep(0.35)

        self._check_input()
        pyautogui.press("escape")
        raise SafetyError(
            f"Não foi possível localizar {label!r} dentro da lista aberta após "
            "varredura completa. A rolagem foi interrompida por segurança."
        )

    def _ecommerce_channel_is_in_field(self, field, anchor):
        region = (field.x - 275, field.y - 15, field.x + 205, field.y + 15)
        return self.calibration.locate_anchor(
            anchor, region=region, min_score=.72
        ) is not None

    def _set_ecommerce_channel_by_keyboard(
        self, field, anchor: str, label: str, selected: bool
    ) -> None:
        """Toggle one fixed SYSEMP item without image-driven scrolling."""
        import pyautogui

        self._check_cancelled()
        currently_selected = self._ecommerce_channel_is_in_field(field, anchor)
        if currently_selected == selected:
            state = 'marcado' if selected else 'desmarcado'
            self.log.info('Canal confirmado no campo: %s — %s', label, state)
            return

        def toggle_target():
            self._check_input()
            pyautogui.click(field.x, field.y)
            time.sleep(.25)
            pyautogui.press('home')
            pyautogui.press(
                'down', presses=ECOMMERCE_CHANNEL_INDEX[label], interval=.025
            )
            pyautogui.press('space')
            time.sleep(.2)
            pyautogui.press('escape')
            time.sleep(.25)

        toggle_target()

        actual = self._ecommerce_channel_is_in_field(field, anchor)
        if actual != selected:
            # Undo the exact keyboard action before stopping. This prevents a
            # wrong item from remaining selected after a failed validation.
            toggle_target()
            state = 'marcar' if selected else 'desmarcar'
            raise SafetyError(
                f'Não foi possível {state} {label} pela navegação do SYSEMP. '
                'A ronda foi interrompida sem pesquisar.'
            )
        state = 'marcado' if selected else 'desmarcado'
        self.log.info('Canal confirmado por teclado: %s — %s', label, state)

    def _clear_company_checkbox(
        self, screen_id: str, field_x: int, field_y: int
    ) -> None:
        if screen_id == "ecommerce_manager":
            self._clear_ecommerce_company()
            return
        field = self.reference_matcher.locate_point(screen_id, field_x, field_y)
        if field is None:
            raise SafetyError("Campo Empresa não encontrado.")
        field_region = (field.x - 215, field.y - 14, field.x + 215, field.y + 14)

        full_selected = self.calibration.locate_anchor(
            "company_full_selected.png", region=field_region, min_score=0.78
        )
        if full_selected is not None:
            self._set_checklist_value(
                screen_id,
                field_x,
                field_y,
                "company_full_hero_row.png",
                "Empresa FULL HERO BAND / ATACADO",
                selected=False,
                dropdown_height=215,
            )

        field = self.reference_matcher.locate_point(screen_id, field_x, field_y)
        if field is None:
            raise SafetyError("Campo Empresa não encontrado após a primeira limpeza.")
        field_region = (field.x - 215, field.y - 14, field.x + 215, field.y + 14)
        hero_selected = self.calibration.locate_anchor(
            "company_hero_selected.png", region=field_region, min_score=0.78
        )
        if hero_selected is not None:
            self._set_checklist_value(
                screen_id,
                field_x,
                field_y,
                "company_hero_row.png",
                "Empresa HERO BAND / ATACADO",
                selected=False,
                dropdown_height=215,
            )
        self.log.info("Filtro Empresa confirmado sem seleção.")

    @staticmethod
    def _field_interior_is_empty(pixels) -> bool:
        import numpy as np

        gray = np.asarray(pixels.convert("L"), dtype=float)
        if gray.size == 0:
            return False
        # Somente interiores dos campos: bordas, seta e rótulo ficam de fora.
        background = float(np.median(gray))
        return int((np.abs(gray - background) > 30).sum()) < 3

    def _ecommerce_company_is_empty(self) -> bool:
        from PIL import ImageGrab

        matched = self.reference_matcher.match("ecommerce_manager")
        if matched is None:
            return False
        for left, top, right, bottom in (
            (182, 141, 226, 158), (240, 141, 670, 158),
        ):
            first = self.reference_matcher.map_point(matched, left, top)
            last = self.reference_matcher.map_point(matched, right, bottom)
            if last.x <= first.x or last.y <= first.y:
                return False
            pixels = ImageGrab.grab(
                bbox=(first.x, first.y, last.x, last.y), all_screens=True
            )
            if not self._field_interior_is_empty(pixels):
                return False
        return True

    def _clear_ecommerce_company(self) -> None:
        import pyautogui

        # Na gravação, o e-commerce usa código + descrição, não checklist.
        self._click_reference("ecommerce_manager", 201, 149, 0.2)
        self._check_cancelled()
        if not foreground_matches(
            self.config.target_window.get("title_regex"),
            self.config.target_window.get("process_path_regex"),
        ):
            raise SafetyError("O foco saiu do SYSEMP antes de limpar a Empresa.")
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        pyautogui.press("tab")
        for _attempt in range(10):
            self._check_cancelled()
            time.sleep(0.2)
            if self._ecommerce_company_is_empty():
                self.log.info("Empresa do e-commerce: código e descrição vazios.")
                return
        raise SafetyError(
            "O código da Empresa foi limpo, mas não foi possível confirmar "
            "código e descrição vazios. Pesquisa não iniciada."
        )

    def _prepare_label_dates(self) -> None:
        import pyautogui

        start, end = delivery_window(
            self.config.processing["delivery_window"], date.today()
        )
        self._delivery_dates = (start, end)
        # Remover datas de emissão e aplicar somente o Limite Entrega.
        for x, y, value in (
            (925, 118, ""), (1110, 118, ""),
            (925, 149, start.strftime("%d/%m/%Y")),
            (1110, 149, end.strftime("%d/%m/%Y")),
        ):
            self._click_reference("ecommerce_manager", x, y)
            self._check_cancelled()
            if not foreground_matches(
                self.config.target_window.get("title_regex"),
                self.config.target_window.get("process_path_regex"),
            ):
                raise SafetyError("O foco saiu do SYSEMP antes de preencher a data.")
            pyautogui.hotkey("ctrl", "a")
            if value:
                pyautogui.write(value, interval=0.03)
            else:
                pyautogui.press("backspace")
            pyautogui.press("tab")
        self.log.info("Período de entrega informado: %s até %s", start, end)

    def test_ecommerce_channel_cycle(self, after_search=None):
        if not self.mode.live:
            raise SafetyError("O teste de navegação exige autorização para cliques.")
        self.validate_environment()
        self._check_cancelled()
        window = find_unique_window(
            title_regex=self.config.target_window.get("title_regex"),
            process_path_regex=self.config.target_window.get("process_path_regex"),
        )
        activate_and_maximize(window)
        time.sleep(0.8)
        visible = self.reference_matcher.detect_visible_screen()
        if visible is None or visible.screen_id != "ecommerce_manager":
            self.prepare_home_ecommerce()
            self._click_reference("home_ecommerce", 455, 610, 1.2)
        self._clear_company_checkbox("ecommerce_manager", 450, 149)
        self._prepare_label_dates()

        channels = tuple(self.config.processing["label_channels"])
        self.log.info('Normalizando Canal de Vendas: desmarcando todas as lojas ML antes da ronda.')
        for channel in channels:
            self._set_checklist_value(
                "ecommerce_manager", 450, 211, self._channel_anchor(channel),
                channel, selected=False
            )
        for index, channel in enumerate(channels, start=1):
            self._check_cancelled()
            self.log.info("Loja e-commerce %d/%d: %s", index, len(channels), channel)
            anchor = self._channel_anchor(channel)
            selection_attempted = False
            try:
                selection_attempted = True
                self._set_checklist_value(
                    "ecommerce_manager", 450, 211, anchor, channel,
                    selected=True, force_click=True
                )
                self._click_reference("ecommerce_manager", 40, 50, 2.0)
                if after_search is not None:
                    result = after_search(channel)
                    if result is not None:
                        # The finally block clears the store before returning.
                        return result
                if after_search is None:
                    self.log.info('Teste seguro de %s concluído; nenhuma impressão foi iniciada.', channel)
            finally:
                if selection_attempted:
                    self._set_checklist_value(
                        "ecommerce_manager", 450, 211, anchor, channel, selected=False
                    )

    def prepare_home_sales(self) -> None:
        import pyautogui

        self.validate_environment()
        window = find_unique_window(
            title_regex=self.config.target_window.get("title_regex"),
            process_path_regex=self.config.target_window.get("process_path_regex"),
        )
        activate_and_maximize(window)
        time.sleep(0.8)

        navigation_points = {
            "home_ecommerce": (784, 182),
            "ecommerce_manager": (1208, 50),
        }
        for _attempt in range(5):
            self._check_cancelled()
            visible = self.reference_matcher.detect_visible_screen()
            if visible is None:
                raise SafetyError(
                    "Não foi possível identificar a tela atual do SYSEMP."
                )
            if visible.screen_id == "home_sales":
                self.log.info("Tela inicial de Vendas pronta.")
                return
            if visible.screen_id == "invoice_channel_dropdown":
                pyautogui.press("escape")
                time.sleep(0.7)
                continue
            if visible.screen_id == "invoice_main":
                exit_point = self.calibration.locate_anchor("invoice_exit.png")
                if exit_point is None:
                    raise SafetyError("Botão Sair da tela de Notas Fiscais não encontrado.")
                pyautogui.click(exit_point.x, exit_point.y)
                time.sleep(1.2)
                continue
            coordinates = navigation_points.get(visible.screen_id)
            if coordinates is None:
                raise SafetyError(
                    f"Não há rota automática a partir de {visible.screen_id}."
                )
            point = self.reference_matcher.map_point(
                visible, coordinates[0], coordinates[1]
            )
            pyautogui.click(point.x, point.y)
            time.sleep(1.2)
        raise SafetyError("Não foi possível retornar à tela inicial de Vendas.")

    def prepare_home_ecommerce(self) -> None:
        import pyautogui

        self.validate_environment()
        window = find_unique_window(
            title_regex=self.config.target_window.get("title_regex"),
            process_path_regex=self.config.target_window.get("process_path_regex"),
        )
        activate_and_maximize(window)
        time.sleep(0.8)

        navigation_points = {
            "home_sales": (895, 182),
            "ecommerce_manager": (1208, 50),
        }
        for _attempt in range(5):
            self._check_cancelled()
            visible = self.reference_matcher.detect_visible_screen()
            if visible is None:
                raise SafetyError(
                    "Não foi possível identificar a tela atual do SYSEMP."
                )
            if visible.screen_id == "home_ecommerce":
                self.log.info("Tela inicial de e-Commerce pronta.")
                return
            if visible.screen_id == "invoice_channel_dropdown":
                pyautogui.press("escape")
                time.sleep(0.7)
                continue
            if visible.screen_id == "invoice_main":
                exit_point = self.calibration.locate_anchor("invoice_exit.png")
                if exit_point is None:
                    raise SafetyError("Botão Sair da tela de Notas Fiscais não encontrado.")
                pyautogui.click(exit_point.x, exit_point.y)
                time.sleep(1.2)
                continue
            coordinates = navigation_points.get(visible.screen_id)
            if coordinates is None:
                raise SafetyError(
                    f"Não há rota automática para e-Commerce a partir de "
                    f"{visible.screen_id}."
                )
            point = self.reference_matcher.map_point(
                visible, coordinates[0], coordinates[1]
            )
            pyautogui.click(point.x, point.y)
            time.sleep(1.2)
        raise SafetyError("Não foi possível abrir a tela inicial de e-Commerce.")

    def _execute_live(self, step: Step) -> None:
        import pyautogui

        title_regex = self.config.target_window.get("title_regex")
        process_regex = self.config.target_window.get("process_path_regex")
        current_title = foreground_title()
        if not foreground_matches(title_regex, process_regex):
            raise SafetyError(
                f"Foco saiu do SYSEMP. Janela ativa: {current_title!r}."
            )

        if step.action == "manual_review":
            if self.mode.safe_test:
                self.log.info("Checkpoint seguro, sem ação: %s", step.label)
                return
            raise SafetyError(f"Revisão manual obrigatória: {step.label}")

        if step.action == "replace_text":
            pyautogui.hotkey("ctrl", "a")
            pyautogui.write(step.value or "", interval=0.03)
            pyautogui.press("enter")
            return

        if step.action in {"delivery_start", "delivery_end"}:
            if self._delivery_dates is None:
                raise SafetyError("Período de entrega não inicializado para a ronda.")
            value = self._delivery_dates[step.action == "delivery_end"]
            pyautogui.hotkey("ctrl", "a")
            pyautogui.write(value.strftime("%d/%m/%Y"), interval=0.03)
            return

        if step.action == "today":
            pyautogui.hotkey("ctrl", "a")
            pyautogui.write(datetime.now().strftime("%d/%m/%Y"), interval=0.03)
            return

        if step.action == "clear_focused":
            pyautogui.hotkey("ctrl", "a")
            pyautogui.press("backspace")
            return

        if step.action != "click":
            raise SafetyError(f"Ação não suportada: {step.action}")

        reference_point = None
        uses_reference_pack = (
            step.screen_id
            and step.reference_x is not None
            and step.reference_y is not None
            and self.reference_matcher.is_ready()
        )
        if uses_reference_pack:
            reference_point = self.reference_matcher.locate_point(
                step.screen_id,
                step.reference_x,
                step.reference_y,
            )

        point = reference_point
        if point is None and step.anchor and not uses_reference_pack:
            point = self.calibration.locate_anchor(step.anchor)
        if point is None:
            self._save_failure_screenshot(pyautogui, step)
            raise SafetyError(
                f"Tela ou elemento não encontrado: {step.label}. "
                "Confira se o SYSEMP está na tela esperada."
            )

        if not foreground_matches(title_regex, process_regex):
            raise SafetyError("A janela ativa mudou durante a validação visual.")
        if reference_point is not None:
            self.log.info(
                "Tela %s mapeada em (%d, %d), confiança %.3f, %d inliers",
                reference_point.screen_id,
                reference_point.x,
                reference_point.y,
                reference_point.confidence,
                reference_point.inliers,
            )
        else:
            self.log.info(
                "Âncora %s reconhecida em (%d, %d), confiança %.3f",
                point.name,
                point.x,
                point.y,
                point.score,
            )
        pyautogui.click(point.x, point.y)
        pause = (
            step.pause_seconds
            if step.pause_seconds is not None
            else float(self.config.safety["pause_after_click_seconds"])
        )
        time.sleep(pause)

    def _save_failure_screenshot(self, pyautogui: object, step: Step) -> None:
        from PIL import ImageGrab

        output_dir = self.config.root / "runtime" / "failures"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = output_dir / f"{timestamp}-{step.id}.png"
        ImageGrab.grab(all_screens=True).save(path)


def configure_logging(root: Path) -> None:
    log_dir = root / "runtime" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"etiquetas-{datetime.now():%Y%m%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )
