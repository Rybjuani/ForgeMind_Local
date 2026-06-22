"""UI principal ForgeMind Local - PyQt6.

Diseno:
  - 1 ventana QMainWindow con un QTabWidget (6 pestanas = 6 paneles pedidos).
  - Worker thread para NO bloquear la UI durante generate().
  - Imports compatibles con PyQt6 >= 6.7 (QAction en QtGui).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QAction, QFont  # PyQt6 >= 6.7: QAction vive aca
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPushButton,
    QPlainTextEdit, QLabel, QGroupBox, QFileDialog, QMessageBox, QListWidget,
    QListWidgetItem, QProgressBar, QTextEdit, QStatusBar,
)

from .benchmark import DEFAULT_PROMPTS_FILE, DEFAULT_RESULTS_DIR, run_benchmark, load_prompts
from .gpu_detect import system_summary
from .llama_backend import LlamaBackend
from .metrics import get_process_metrics, get_system_memory
from .model_config import ModelConfig
from .presets import PRESETS, get_preset, default_preset


# ----------------- Worker thread (no bloquea UI) -----------------

class GenerateWorker(QObject):
    finished = pyqtSignal(str, dict)   # texto, metrics
    failed = pyqtSignal(str)           # mensaje

    def __init__(self, backend: LlamaBackend, prompt: str, system: str) -> None:
        super().__init__()
        self._backend = backend
        self._prompt = prompt
        self._system = system

    def run(self) -> None:
        from .metrics import measure_inference
        m = measure_inference(self._backend.generate, self._prompt, self._system)
        out = self._backend.generate(self._prompt, self._system)
        # measure_inference ya corrio generate; lo corremos otra vez seria doble trabajo.
        # Mejor: medir dentro de run para no duplicar. Pero el contrato de generate()
        # NO debe raise; aqui podemos envolver.
        # Solucion limpia: medimos alrededor de una sola llamada.
        self.finished.emit(out, m)


class GenerateRunner(QThread):
    """Thread wrapper que SI mide una sola vez y no duplica generate()."""
    finished = pyqtSignal(str, dict)
    failed = pyqtSignal(str)

    def __init__(self, backend: LlamaBackend, prompt: str, system: str,
                 max_tokens_override: int | None = None) -> None:
        super().__init__()
        self._backend = backend
        self._prompt = prompt
        self._system = system
        self._override = max_tokens_override

    def run(self) -> None:
        from .metrics import measure_inference
        old_max = self._backend.config.max_tokens
        if self._override is not None:
            self._backend.config.max_tokens = self._override
        try:
            t0 = time.perf_counter()
            try:
                out = self._backend.generate(self._prompt, self._system)
            except Exception as e:  # no deberia, pero por si acaso
                self.failed.emit(str(e))
                return
            elapsed = time.perf_counter() - t0
            m = {
                "elapsed_sec": round(elapsed, 3),
                "char_count": len(out),
                "tokens_per_sec_proxy": round((len(out) / 4.0) / elapsed, 3) if elapsed > 0 else None,
                "first_token_sec": None,
                "error": None,
            }
            self.finished.emit(out, m)
        finally:
            self._backend.config.max_tokens = old_max


# ----------------- Ventana principal -----------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ForgeMind Local")
        self.resize(1100, 760)

        self.backend = LlamaBackend(ModelConfig())
        self._chat_history: list[dict[str, str]] = []
        self._current_runner: GenerateRunner | None = None

        self._build_menu()
        self._build_tabs()
        self._build_statusbar()
        self._refresh_gpu_panel()
        self._refresh_metrics_panel()
        self._refresh_backend_panel()

    # ---------- menus / acciones ----------

    def _build_menu(self) -> None:
        m_file = self.menuBar().addMenu("&Archivo")

        act_load = QAction("Cargar configuracion...", self)
        act_load.triggered.connect(self._on_load_config)
        m_file.addAction(act_load)

        act_save = QAction("Guardar configuracion...", self)
        act_save.triggered.connect(self._on_save_config)
        m_file.addAction(act_save)

        m_file.addSeparator()

        act_quit = QAction("Salir", self)
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        m_help = self.menuBar().addMenu("&Ayuda")
        act_about = QAction("Acerca de...", self)
        act_about.triggered.connect(self._on_about)
        m_help.addAction(act_about)

    def _build_statusbar(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage("Listo. Configura un modelo y un backend para empezar.")

    # ---------- tabs ----------

    def _build_tabs(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._build_model_tab(), "1. Modelo")
        tabs.addTab(self._build_backend_tab(), "2. Backend")
        tabs.addTab(self._build_chat_tab(), "3. Chat")
        tabs.addTab(self._build_metrics_tab(), "4. Rendimiento")
        tabs.addTab(self._build_gpu_tab(), "5. AMD / Vulkan")
        tabs.addTab(self._build_bench_tab(), "6. Benchmark")
        self.setCentralWidget(tabs)

    # ---- Tab 1: Modelo ----

    def _build_model_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        gb_path = QGroupBox("Ruta al .gguf")
        form = QFormLayout(gb_path)
        self.in_gguf_path = QLineEdit()
        self.in_gguf_path.setPlaceholderText("C:\\ruta\\a\\modelo.gguf")
        row = QHBoxLayout()
        row.addWidget(self.in_gguf_path, 1)
        b = QPushButton("Elegir...")
        b.clicked.connect(self._on_pick_gguf)
        row.addWidget(b)
        form.addRow("Archivo:", row)

        self.lbl_info = QLabel("(sin modelo)")
        self.lbl_info.setWordWrap(True)
        form.addRow("Info:", self.lbl_info)
        v.addWidget(gb_path)

        gb_meta = QGroupBox("Identidad")
        f2 = QFormLayout(gb_meta)
        self.in_name = QLineEdit()
        self.in_name.setPlaceholderText("Nombre amigable (ej: Gemma 4 12B Q4_K_M)")
        f2.addRow("Nombre:", self.in_name)
        v.addWidget(gb_meta)

        gb_inf = QGroupBox("Inferencia")
        f3 = QFormLayout(gb_inf)
        self.sb_ctx = QSpinBox(); self.sb_ctx.setRange(256, 32768); self.sb_ctx.setValue(4096); self.sb_ctx.setSingleStep(256)
        f3.addRow("Contexto (tokens):", self.sb_ctx)
        self.sb_threads = QSpinBox(); self.sb_threads.setRange(1, 64); self.sb_threads.setValue(8)
        f3.addRow("Threads CPU:", self.sb_threads)
        self.sb_max = QSpinBox(); self.sb_max.setRange(16, 8192); self.sb_max.setValue(512); self.sb_max.setSingleStep(32)
        f3.addRow("Max tokens respuesta:", self.sb_max)
        self.ds_temp = QDoubleSpinBox(); self.ds_temp.setRange(0.0, 2.0); self.ds_temp.setDecimals(3); self.ds_temp.setSingleStep(0.05); self.ds_temp.setValue(0.7)
        f3.addRow("Temperatura:", self.ds_temp)
        self.ds_top_p = QDoubleSpinBox(); self.ds_top_p.setRange(0.0, 1.0); self.ds_top_p.setDecimals(3); self.ds_top_p.setSingleStep(0.01); self.ds_top_p.setValue(0.95)
        f3.addRow("Top-p:", self.ds_top_p)
        self.ds_rep = QDoubleSpinBox(); self.ds_rep.setRange(0.5, 2.0); self.ds_rep.setDecimals(3); self.ds_rep.setSingleStep(0.05); self.ds_rep.setValue(1.1)
        f3.addRow("Repeat penalty:", self.ds_rep)
        v.addWidget(gb_inf)

        gb_mode = QGroupBox("Modo de computo")
        f4 = QFormLayout(gb_mode)
        self.cmb_mode = QComboBox(); self.cmb_mode.addItems(["cpu", "vulkan"])
        f4.addRow("Modo:", self.cmb_mode)
        self.sb_gpu_layers = QSpinBox(); self.sb_gpu_layers.setRange(0, 999); self.sb_gpu_layers.setValue(0)
        f4.addRow("GPU layers (0 = off):", self.sb_gpu_layers)
        self.lbl_mode_warn = QLabel(
            "Aviso: Vulkan / GPU offload es experimental en AMD Radeon RX550 4 GB. "
            "Si falla, volve a CPU. Vulkan NO cambia la calidad del modelo."
        )
        self.lbl_mode_warn.setWordWrap(True)
        f4.addRow(self.lbl_mode_warn)
        v.addWidget(gb_mode)

        v.addStretch(1)

        row_btns = QHBoxLayout()
        b_apply = QPushButton("Aplicar config al backend")
        b_apply.clicked.connect(self._on_apply_model)
        row_btns.addWidget(b_apply)
        b_refresh = QPushButton("Refrescar info del archivo")
        b_refresh.clicked.connect(self._refresh_model_info)
        row_btns.addWidget(b_refresh)
        row_btns.addStretch(1)
        v.addLayout(row_btns)

        self.in_gguf_path.textChanged.connect(self._refresh_model_info)
        return w

    def _refresh_model_info(self) -> None:
        cfg = self._gather_model_config_from_ui()
        if not cfg.gguf_path:
            self.lbl_info.setText("(sin modelo)")
            self.in_name.setPlaceholderText("Nombre amigable (ej: Gemma 4 12B Q4_K_M)")
            return
        if not cfg.exists():
            self.lbl_info.setText(f"Ruta no existe: {cfg.gguf_path}")
            return
        self.lbl_info.setText(
            f"Cuant: <b>{cfg.quant or '?'}</b>  -  Tamano disco: <b>{cfg.size_human}</b>"
        )
        if not self.in_name.text():
            base = os.path.basename(cfg.gguf_path)
            stem = base.rsplit(".", 1)[0] if "." in base else base
            self.in_name.setText(stem)

    def _gather_model_config_from_ui(self) -> ModelConfig:
        cfg = ModelConfig(
            name=self.in_name.text().strip() or "modelo-sin-nombre",
            gguf_path=self.in_gguf_path.text().strip(),
            ctx_size=int(self.sb_ctx.value()),
            threads=int(self.sb_threads.value()),
            max_tokens=int(self.sb_max.value()),
            temperature=float(self.ds_temp.value()),
            top_p=float(self.ds_top_p.value()),
            repeat_penalty=float(self.ds_rep.value()),
            mode=self.cmb_mode.currentText(),
            gpu_layers=int(self.sb_gpu_layers.value()),
            backend_kind=self.backend.config.backend_kind,
            llama_cli_path=self.backend.config.llama_cli_path,
            llama_server_path=self.backend.config.llama_server_path,
        )
        return cfg

    def _on_apply_model(self) -> None:
        new_cfg = self._gather_model_config_from_ui()
        # NO destruir el proceso actual sin querer: si esta corriendo, pararlo.
        if self.backend.is_running():
            self.backend.stop()
        self.backend = LlamaBackend(new_cfg)
        self._refresh_backend_panel()
        self.statusBar().showMessage(f"Config aplicada: {new_cfg.name} ({new_cfg.size_human})", 5000)

    def _on_pick_gguf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Elegir modelo GGUF",
                                              "", "GGUF (*.gguf);;Todos (*.*)")
        if path:
            self.in_gguf_path.setText(path)

    # ---- Tab 2: Backend ----

    def _build_backend_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        gb_kind = QGroupBox("Tipo de backend")
        f = QFormLayout(gb_kind)
        self.cmb_backend_kind = QComboBox()
        self.cmb_backend_kind.addItems(["llama_cli", "llama_server", "llama_cpp"])
        self.cmb_backend_kind.setCurrentText(self.backend.config.backend_kind)
        self.cmb_backend_kind.currentTextChanged.connect(self._on_backend_kind_changed)
        f.addRow("Backend kind:", self.cmb_backend_kind)
        v.addWidget(gb_kind)

        gb_paths = QGroupBox("Rutas a ejecutables de llama.cpp")
        f2 = QFormLayout(gb_paths)
        self.in_llama_cli = QLineEdit(self.backend.config.llama_cli_path)
        self.in_llama_cli.setPlaceholderText("(vacio = buscar en PATH)")
        f2.addRow("llama-cli:", self.in_llama_cli)
        self.in_llama_server = QLineEdit(self.backend.config.llama_server_path)
        self.in_llama_server.setPlaceholderText("(vacio = buscar en PATH)")
        f2.addRow("llama-server:", self.in_llama_server)
        v.addWidget(gb_paths)

        row_btns = QHBoxLayout()
        self.btn_test = QPushButton("Probar backend")
        self.btn_test.clicked.connect(self._on_test_backend)
        row_btns.addWidget(self.btn_test)
        self.btn_start = QPushButton("Iniciar modelo")
        self.btn_start.clicked.connect(self._on_start_backend)
        row_btns.addWidget(self.btn_start)
        self.btn_stop = QPushButton("Detener modelo")
        self.btn_stop.clicked.connect(self._on_stop_backend)
        row_btns.addWidget(self.btn_stop)
        row_btns.addStretch(1)
        v.addLayout(row_btns)

        gb_state = QGroupBox("Estado del backend")
        f3 = QFormLayout(gb_state)
        self.lbl_backend_status = QLabel("?")
        f3.addRow("Estado:", self.lbl_backend_status)
        self.lbl_backend_kind_active = QLabel("?")
        f3.addRow("Backend activo:", self.lbl_backend_kind_active)
        self.lbl_pid = QLabel("?")
        f3.addRow("PID:", self.lbl_pid)
        self.lbl_cmd = QLabel("-")
        self.lbl_cmd.setWordWrap(True)
        self.lbl_cmd.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        f3.addRow("Comando:", self.lbl_cmd)
        self.lbl_load_err = QLabel("-")
        self.lbl_load_err.setWordWrap(True)
        self.lbl_load_err.setStyleSheet("color: #c0392b;")
        f3.addRow("Errores:", self.lbl_load_err)
        v.addWidget(gb_state)

        gb_log = QGroupBox("Log basico")
        vlog = QVBoxLayout(gb_log)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(2000)
        vlog.addWidget(self.txt_log)
        v.addWidget(gb_log, 1)

        return w

    def _on_backend_kind_changed(self, kind: str) -> None:
        cfg = self.backend.config
        cfg.backend_kind = kind
        cfg.llama_cli_path = self.in_llama_cli.text().strip()
        cfg.llama_server_path = self.in_llama_server.text().strip()
        self._refresh_backend_panel()
        self._log(f"backend_kind cambiado a: {kind}")

    def _on_test_backend(self) -> None:
        cfg = self.backend.config
        cfg.llama_cli_path = self.in_llama_cli.text().strip()
        cfg.llama_server_path = self.in_llama_server.text().strip()
        # Probar SOLO presencia de ejecutable, sin cargar modelo
        from .metrics import find_executable
        ok_cli = find_executable("llama-cli") or find_executable("llama-cli.exe") or (
            cfg.llama_cli_path and os.path.isfile(cfg.llama_cli_path))
        ok_srv = find_executable("llama-server") or find_executable("llama-server.exe") or (
            cfg.llama_server_path and os.path.isfile(cfg.llama_server_path))
        msgs = []
        msgs.append(f"llama-cli: {'OK' if ok_cli else 'NO encontrado'}")
        msgs.append(f"llama-server: {'OK' if ok_srv else 'NO encontrado'}")
        msgs.append(f"llama_cpp binding: {'OK' if _have_binding() else 'NO instalado'}")
        msgs.append(f"Modelo existe: {'OK' if cfg.exists() else 'falta'}")
        self._log(" | ".join(msgs))
        QMessageBox.information(self, "Probar backend", "\n".join(msgs))

    def _on_start_backend(self) -> None:
        cfg = self.backend.config
        cfg.llama_cli_path = self.in_llama_cli.text().strip()
        cfg.llama_server_path = self.in_llama_server.text().strip()
        cfg.backend_kind = self.cmb_backend_kind.currentText()
        if not cfg.exists() and cfg.backend_kind != "mock":
            QMessageBox.warning(self, "Modelo",
                                "Ruta al .gguf invalida. Configurala en la pestana Modelo.")
            return
        ok = self.backend.start()
        self._log(f"start() -> {ok}")
        self._refresh_backend_panel()
        self._refresh_metrics_panel()
        if ok:
            self.statusBar().showMessage("Backend arrancado.", 3000)
        else:
            self.statusBar().showMessage("Backend NO arranco. Revisa errores.", 5000)

    def _on_stop_backend(self) -> None:
        self.backend.stop()
        self._log("stop()")
        self._refresh_backend_panel()
        self._refresh_metrics_panel()
        self.statusBar().showMessage("Backend detenido.", 3000)

    def _refresh_backend_panel(self) -> None:
        s = self.backend.status()
        self.lbl_backend_status.setText("ACTIVO" if s["running"] else "DETENIDO")
        self.lbl_backend_kind_active.setText(f"{s['backend']} (mock={s['mock']})")
        self.lbl_pid.setText(str(s.get("pid") or "(n/a)"))
        self.lbl_cmd.setText(s.get("command") or "-")
        self.lbl_load_err.setText(s.get("load_error") or "-")

    def _log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.txt_log.appendPlainText(f"[{ts}] {msg}")

    # ---- Tab 3: Chat ----

    def _build_chat_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        gb_p = QGroupBox("Preset de uso")
        hp = QHBoxLayout(gb_p)
        self.cmb_preset = QComboBox()
        for p in PRESETS:
            self.cmb_preset.addItem(p.label, userData=p.key)
        self.cmb_preset.setCurrentIndex(0)
        hp.addWidget(QLabel("Preset:"))
        hp.addWidget(self.cmb_preset, 1)
        hp.addStretch(1)
        v.addWidget(gb_p)

        gb_o = QGroupBox("Salida del modelo")
        vo = QVBoxLayout(gb_o)
        self.txt_output = QPlainTextEdit()
        self.txt_output.setReadOnly(True)
        f = QFont("Consolas"); f.setStyleHint(QFont.StyleHint.Monospace)
        self.txt_output.setFont(f)
        vo.addWidget(self.txt_output)
        v.addWidget(gb_o, 1)

        gb_i = QGroupBox("Prompt")
        vi = QVBoxLayout(gb_i)
        self.txt_prompt = QPlainTextEdit()
        self.txt_prompt.setPlaceholderText("Escribi tu prompt aca...")
        self.txt_prompt.setMaximumHeight(160)
        vi.addWidget(self.txt_prompt)

        hb = QHBoxLayout()
        self.btn_send = QPushButton("Enviar")
        self.btn_send.clicked.connect(self._on_send)
        hb.addWidget(self.btn_send)
        self.btn_stop_gen = QPushButton("Detener generacion")
        self.btn_stop_gen.clicked.connect(self._on_stop_gen)
        self.btn_stop_gen.setEnabled(False)
        hb.addWidget(self.btn_stop_gen)
        self.btn_clear = QPushButton("Limpiar")
        self.btn_clear.clicked.connect(self._on_clear_chat)
        hb.addWidget(self.btn_clear)
        hb.addStretch(1)
        self.lbl_last_metrics = QLabel("")
        hb.addWidget(self.lbl_last_metrics)
        vi.addLayout(hb)
        v.addWidget(gb_i)
        return w

    def _on_send(self) -> None:
        prompt_text = self.txt_prompt.toPlainText().strip()
        if not prompt_text:
            return
        if not self.backend.is_running():
            ok = self.backend.start()
            self._refresh_backend_panel()
            self._refresh_metrics_panel()
            if not ok:
                QMessageBox.warning(self, "Backend",
                                    "No se pudo arrancar el backend. Revisa la pestana Backend.")
                return
        preset = get_preset(self.cmb_preset.currentData()) or default_preset()
        self._append_chat("user", prompt_text)
        self.txt_prompt.clear()
        self._run_generate(prompt_text, preset.system, preset.max_tokens)

    def _run_generate(self, prompt: str, system: str, max_tokens: int) -> None:
        self.btn_send.setEnabled(False)
        self.btn_stop_gen.setEnabled(True)
        self.lbl_last_metrics.setText("generando...")
        runner = GenerateRunner(self.backend, prompt, system, max_tokens_override=max_tokens)
        runner.finished.connect(self._on_gen_finished)
        runner.failed.connect(self._on_gen_failed)
        runner.finished.connect(runner.deleteLater)
        runner.failed.connect(runner.deleteLater)
        self._current_runner = runner
        runner.start()

    def _on_stop_gen(self) -> None:
        if self._current_runner is not None and self._current_runner.isRunning():
            self._current_runner.requestInterruption()
            # Subprocesos one-shot de llama-cli no se pueden matar "a medias" sin hack;
            # lo dejamos: el runner termina cuando subprocess termina.
            self._log("stop solicitado (runner se marcara al terminar)")
        self.btn_stop_gen.setEnabled(False)

    def _on_gen_finished(self, out: str, metrics: dict[str, Any]) -> None:
        self._append_chat("assistant", out)
        tps = metrics.get("tokens_per_sec_proxy")
        tps_s = f"{tps:.2f} t/s" if isinstance(tps, (int, float)) else "?"
        self.lbl_last_metrics.setText(
            f"{metrics.get('elapsed_sec','?')} s | {metrics.get('char_count','?')} chars | {tps_s}"
        )
        self.btn_send.setEnabled(True)
        self.btn_stop_gen.setEnabled(False)
        self._current_runner = None
        self._refresh_metrics_panel()

    def _on_gen_failed(self, err: str) -> None:
        self._append_chat("assistant", f"[error] {err}")
        self.btn_send.setEnabled(True)
        self.btn_stop_gen.setEnabled(False)
        self._current_runner = None

    def _on_clear_chat(self) -> None:
        self._chat_history.clear()
        self.txt_output.clear()
        self.lbl_last_metrics.setText("")

    def _append_chat(self, role: str, text: str) -> None:
        self._chat_history.append({"role": role, "text": text})
        head = "Usuario" if role == "user" else "Asistente"
        self.txt_output.appendPlainText(f"--- {head} ---\n{text}\n")

    # ---- Tab 4: Rendimiento ----

    def _build_metrics_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        gb_sys = QGroupBox("Sistema")
        fs = QFormLayout(gb_sys)
        self.lbl_ram_total = QLabel("?")
        fs.addRow("RAM total:", self.lbl_ram_total)
        self.lbl_ram_avail = QLabel("?")
        fs.addRow("RAM disponible:", self.lbl_ram_avail)
        self.lbl_cpu = QLabel("?")
        fs.addRow("CPU % sistema:", self.lbl_cpu)
        v.addWidget(gb_sys)

        gb_be = QGroupBox("Backend")
        fb = QFormLayout(gb_be)
        self.lbl_be_pid = QLabel("?")
        fb.addRow("PID:", self.lbl_be_pid)
        self.lbl_be_rss = QLabel("?")
        fb.addRow("RSS proceso:", self.lbl_be_rss)
        self.lbl_be_cpu = QLabel("?")
        fb.addRow("CPU % proceso:", self.lbl_be_cpu)
        self.lbl_be_status = QLabel("?")
        fb.addRow("Estado:", self.lbl_be_status)
        v.addWidget(gb_be)

        gb_run = QGroupBox("Corrida actual")
        fr = QFormLayout(gb_run)
        self.lbl_model_size = QLabel("?")
        fr.addRow("Tamano modelo en disco:", self.lbl_model_size)
        self.lbl_ctx_used = QLabel("?")
        fr.addRow("Contexto configurado:", self.lbl_ctx_used)
        self.lbl_last_latency = QLabel("?")
        fr.addRow("Latencia ultima:", self.lbl_last_latency)
        self.lbl_last_tps = QLabel("?")
        fr.addRow("Tokens/s proxy:", self.lbl_last_tps)
        self.lbl_first_token = QLabel("(pendiente; requiere streaming)")
        fr.addRow("Tiempo a 1er token:", self.lbl_first_token)
        self.lbl_mode_state = QLabel("?")
        fr.addRow("CPU / Vulkan:", self.lbl_mode_state)
        v.addWidget(gb_run)

        row = QHBoxLayout()
        b_refresh = QPushButton("Refrescar ahora")
        b_refresh.clicked.connect(self._refresh_metrics_panel)
        row.addWidget(b_refresh)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)
        return w

    def _refresh_metrics_panel(self) -> None:
        sys_mem = get_system_memory()
        self.lbl_ram_total.setText(sys_mem.get("total_human") or "?")
        self.lbl_ram_avail.setText(sys_mem.get("available_human") or "?")
        self.lbl_cpu.setText("?")  # medir cpu% global requiere interval>0; lo dejamos manual

        s = self.backend.status()
        cfg = s["config"]
        self.lbl_model_size.setText(cfg.get("size_human") or "?")
        self.lbl_ctx_used.setText(str(cfg.get("ctx_size")))

        be_proc = self.backend.process_metrics()
        self.lbl_be_pid.setText(str(be_proc.get("pid") or "(n/a)"))
        self.lbl_be_rss.setText(be_proc.get("rss_human") or "?")
        self.lbl_be_cpu.setText(f"{be_proc.get('cpu_percent')}" if be_proc.get("cpu_percent") is not None else "?")
        self.lbl_be_status.setText("ACTIVO" if s["running"] else "DETENIDO")

        self.lbl_mode_state.setText(f"{cfg.get('mode')} | gpu_layers={cfg.get('gpu_layers')}")

    # ---- Tab 5: GPU / Vulkan ----

    def _build_gpu_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        row = QHBoxLayout()
        b = QPushButton("Re-detectar")
        b.clicked.connect(self._refresh_gpu_panel)
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)

        self.txt_gpu = QPlainTextEdit()
        self.txt_gpu.setReadOnly(True)
        v.addWidget(self.txt_gpu, 1)
        return w

    def _refresh_gpu_panel(self) -> None:
        try:
            summary = system_summary()
        except Exception as e:
            self.txt_gpu.setPlainText(f"Error detectando: {e}")
            return
        lines = ["=== GPUs detectadas (WMI) ===", ""]
        for g in summary.get("gpus", []) or ["(ninguna)"]:
            if isinstance(g, str):
                lines.append(g)
                continue
            ram = g.get("adapter_ram_bytes") or 0
            lines.append(f"- {g.get('name')}")
            lines.append(f"    VRAM: {(ram/1024**3):.2f} GB" if ram else "    VRAM: ?")
            lines.append(f"    Driver: {g.get('driver_version') or '?'}")
            lines.append(f"    Procesador: {g.get('video_processor') or '?'}")
        lines.append("")
        amd = summary.get("amd_gpu")
        lines.append("=== GPU AMD ===")
        if amd:
            lines.append(f"- {amd['name']}")
            lines.append(f"  VRAM: {amd['vram_human']}")
        else:
            lines.append("(no se detecto AMD/Radeon)")
        lines.append("")
        vk = summary.get("vulkan", {}) or {}
        lines.append("=== Vulkan ===")
        lines.append(f"vulkan-1.dll presente: {vk.get('vulkan_dll_present')}")
        lines.append(f"vulkaninfo instalado: {vk.get('vulkaninfo_installed')}")
        lines.append(f"Vulkan 'disponible' (heuristica): {vk.get('available')}")
        info = vk.get("info")
        if isinstance(info, dict):
            for k in ("api_version", "driver_version"):
                if info.get(k):
                    lines.append(f"  {k}: {info[k]}")
        lines.append("")
        lines.append("IMPORTANTE:")
        lines.append("- Vulkan NO cambia la inteligencia del modelo.")
        lines.append("- La calidad depende del modelo + cuantizacion + parametros.")
        lines.append("- Si Vulkan falla, volve a CPU; no rompe la app.")
        self.txt_gpu.setPlainText("\n".join(lines))

    # ---- Tab 6: Benchmark ----

    def _build_bench_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        gb = QGroupBox("Configuracion")
        f = QFormLayout(gb)
        self.in_prompts_file = QLineEdit(DEFAULT_PROMPTS_FILE)
        f.addRow("Archivo de prompts:", self.in_prompts_file)
        self.in_results_dir = QLineEdit(DEFAULT_RESULTS_DIR)
        f.addRow("Carpeta resultados:", self.in_results_dir)
        self.in_bench_label = QLineEdit("bench")
        f.addRow("Etiqueta:", self.in_bench_label)
        v.addWidget(gb)

        row = QHBoxLayout()
        b_run = QPushButton("Correr benchmark")
        b_run.clicked.connect(self._on_run_benchmark)
        row.addWidget(b_run)
        b_open = QPushButton("Abrir carpeta resultados")
        b_open.clicked.connect(self._on_open_results)
        row.addWidget(b_open)
        row.addStretch(1)
        v.addLayout(row)

        gb_l = QGroupBox("Prompts cargados")
        vl = QVBoxLayout(gb_l)
        self.lst_prompts = QListWidget()
        vl.addWidget(self.lst_prompts)
        v.addWidget(gb_l, 1)

        gb_out = QGroupBox("Resumen ultima corrida")
        vo = QVBoxLayout(gb_out)
        self.txt_bench_out = QPlainTextEdit()
        self.txt_bench_out.setReadOnly(True)
        vo.addWidget(self.txt_bench_out)
        v.addWidget(gb_out, 1)

        # Carga inicial de prompts para mostrar al usuario
        self._reload_prompts_list()
        return w

    def _reload_prompts_list(self) -> None:
        self.lst_prompts.clear()
        prompts = load_prompts(self.in_prompts_file.text().strip() or DEFAULT_PROMPTS_FILE)
        if not prompts:
            self.lst_prompts.addItem("(no se encontraron prompts)")
            return
        for p in prompts:
            title = p.get("title") or p.get("key") or "?"
            self.lst_prompts.addItem(QListWidgetItem(f"{title}"))

    def _on_run_benchmark(self) -> None:
        if not self.backend.is_running():
            ok = self.backend.start()
            self._refresh_backend_panel()
            self._refresh_metrics_panel()
            if not ok:
                QMessageBox.warning(self, "Benchmark",
                                    "No se pudo arrancar el backend. Revisa la pestana Backend.")
                return
        prompts = load_prompts(self.in_prompts_file.text().strip() or DEFAULT_PROMPTS_FILE)
        if not prompts:
            QMessageBox.warning(self, "Benchmark",
                                f"No hay prompts en {self.in_prompts_file.text()}.")
            return
        # Bloquear UI suavemente (sin hilo extra en MVP): benchmark puede tardar.
        self.statusBar().showMessage("Corriendo benchmark...")
        QApplication.processEvents()
        result = run_benchmark(
            backend=self.backend,
            prompts=prompts,
            results_dir=self.in_results_dir.text().strip() or DEFAULT_RESULTS_DIR,
            label=self.in_bench_label.text().strip() or "bench",
        )
        self._render_bench_summary(result)
        self.statusBar().showMessage(f"Benchmark listo: {result['label']}", 5000)

    def _on_open_results(self) -> None:
        d = self.in_results_dir.text().strip() or DEFAULT_RESULTS_DIR
        Path(d).mkdir(parents=True, exist_ok=True)
        # Abrir explorador de Windows
        try:
            if os.name == "nt":
                os.startfile(str(Path(d).resolve()))  # type: ignore[attr-defined]
            else:
                QMessageBox.information(self, "Resultados", f"Resultados en: {d}")
        except Exception as e:
            QMessageBox.warning(self, "Abrir carpeta", f"No se pudo abrir: {e}")

    def _render_bench_summary(self, r: dict[str, Any]) -> None:
        be = r["backend"]
        cfg = be.get("config", {})
        lines = []
        lines.append(f"Run: {r['label']}  ({r['timestamp']})")
        lines.append(f"Backend: {be.get('backend')}  mock={be.get('mock')}")
        lines.append(f"Modelo: {cfg.get('name')}  Cuant: {cfg.get('quant') or '?'}")
        lines.append(f"Wall time: {r['totals']['wall_time_sec']} s")
        lines.append("")
        lines.append("| # | Titulo | elapsed (s) | t/s (proxy) | chars |")
        lines.append("|---|--------|------------:|------------:|------:|")
        for i, it in enumerate(r["items"], 1):
            m = it["metrics"]
            tps = m.get("tokens_per_sec_proxy")
            tps_s = f"{tps:.2f}" if isinstance(tps, (int, float)) else "-"
            lines.append(f"| {i} | {it['title']} | {m.get('elapsed_sec')} | {tps_s} | {m.get('char_count')} |")
        lines.append("")
        lines.append(f"Resultados guardados en: {self.in_results_dir.text().strip() or DEFAULT_RESULTS_DIR}")
        self.txt_bench_out.setPlainText("\n".join(lines))

    # ---- acciones de menu: config ----

    def _on_save_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Guardar configuracion",
                                              "", "JSON (*.json)")
        if not path:
            return
        data = self._gather_model_config_from_ui().to_dict()
        data["backend_kind"] = self.cmb_backend_kind.currentText()
        data["llama_cli_path"] = self.in_llama_cli.text().strip()
        data["llama_server_path"] = self.in_llama_server.text().strip()
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._log(f"config guardada en {path}")
        self.statusBar().showMessage(f"Config guardada: {path}", 4000)

    def _on_load_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Cargar configuracion",
                                              "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.warning(self, "Cargar config", f"JSON invalido: {e}")
            return
        self.in_name.setText(data.get("name", ""))
        self.in_gguf_path.setText(data.get("gguf_path", ""))
        self.sb_ctx.setValue(int(data.get("ctx_size", 4096)))
        self.sb_threads.setValue(int(data.get("threads", 8)))
        self.sb_max.setValue(int(data.get("max_tokens", 512)))
        self.ds_temp.setValue(float(data.get("temperature", 0.7)))
        self.ds_top_p.setValue(float(data.get("top_p", 0.95)))
        self.ds_rep.setValue(float(data.get("repeat_penalty", 1.1)))
        self.cmb_mode.setCurrentText(str(data.get("mode", "cpu")))
        self.sb_gpu_layers.setValue(int(data.get("gpu_layers", 0)))
        self.cmb_backend_kind.setCurrentText(str(data.get("backend_kind", "llama_cli")))
        self.in_llama_cli.setText(str(data.get("llama_cli_path", "")))
        self.in_llama_server.setText(str(data.get("llama_server_path", "")))
        self._refresh_model_info()
        self._log(f"config cargada de {path}")
        self.statusBar().showMessage(f"Config cargada: {path}", 4000)

    def _on_about(self) -> None:
        QMessageBox.information(
            self, "Acerca de ForgeMind Local",
            "ForgeMind Local v0.1\n\n"
            "App desktop para comparar modelos GGUF locales en Windows.\n"
            "Backend: llama.cpp (llama-cli / llama-server / binding).\n"
            "Sin cloud. Sin CUDA. Vulkan = experimental en AMD."
        )

    # ---- cierre limpio ----

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            if self._current_runner is not None and self._current_runner.isRunning():
                self._current_runner.requestInterruption()
        except Exception:
            pass
        try:
            self.backend.stop()
        except Exception:
            pass
        super().closeEvent(event)


def _have_binding() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:
        return False