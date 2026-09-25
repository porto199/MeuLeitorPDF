import sys
import pymupdf
import threading
import json
import os
import re
import asyncio
import edge_tts
import uuid
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout,
                             QWidget, QFileDialog, QLabel, QScrollArea, QHBoxLayout,
                             QComboBox, QListWidget, QDialog, QTextBrowser)
from PyQt6.QtGui import QImage, QPixmap, QIcon
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint

CONFIG_FILE = "config_leitor.json"
ATALHOS_TEXTO = " (Atalhos: Espaço: Pausar/Retomar | Ctrl+Espaço: Parar)"

class Sinais(QObject):
    mudar_pagina_scroll = pyqtSignal(int)
    destacar_frase = pyqtSignal(int, str)
    resetar_botoes = pyqtSignal()
    status_exportacao = pyqtSignal(str)
    resetar_botoes_exportacao = pyqtSignal()

class LeitorPDF(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MeuLeitorPDF")
        self.setGeometry(100, 100, 1150, 800)

        pygame.mixer.init(buffer=512)
        
        self.parar_flag = False
        self.mudou_parametro_flag = False
        self.is_paused = False
        self.dark_mode = False
        self.cancelar_exportacao_flag = False

        self.pdf_document = None
        self.pdf_path = None
        self.zoom_factor = 1.2
        self.current_page = 0
        self.page_labels = [] 
        self.capitulos_dados = []
        
        self.voz_atual = "pt-BR-AntonioNeural"
        self.velocidade_atual = "+0%"
        self.ignorar_scroll_inicial = True 

        self.sinais = Sinais()
        self.sinais.mudar_pagina_scroll.connect(self.rolar_para_pagina)
        self.sinais.destacar_frase.connect(self.destacar_texto_na_tela)
        self.sinais.resetar_botoes.connect(self.reset_ui_botoes)
        self.sinais.status_exportacao.connect(self.atualizar_status)
        self.sinais.resetar_botoes_exportacao.connect(self.reset_ui_exportacao)

        self.initUI()
        self.carregar_checkpoint()
        self.aplicar_estilo()

    def initUI(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        top_panel = QVBoxLayout()

        # --- LINHA 1: FICHEIRO, VISUALIZAÇÃO E BOTÃO SOBRE/AJUDA ---
        linha1 = QHBoxLayout()
        linha1.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.btn_open = QPushButton("📂 Abrir")
        self.btn_open.clicked.connect(self.abrir_pdf_dialog)
        linha1.addWidget(self.btn_open)

        self.btn_zoom_out = QPushButton("🔍 -")
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        self.btn_zoom_in = QPushButton("🔍 +")
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        linha1.addWidget(self.btn_zoom_out)
        linha1.addWidget(self.btn_zoom_in)

        self.btn_dark = QPushButton("🌙 Inverter Cores")
        self.btn_dark.clicked.connect(self.toggle_dark_mode)
        linha1.addWidget(self.btn_dark)

        linha1.addWidget(QLabel("  Capítulo:"))
        self.btn_capitulos = QPushButton("--- Sumário Não Encontrado ---")
        self.btn_capitulos.setFixedWidth(280)
        self.btn_capitulos.setEnabled(False)
        self.btn_capitulos.clicked.connect(self.mostrar_painel_capitulos)
        linha1.addWidget(self.btn_capitulos)

        self.btn_export = QPushButton("💾 Exportar Livro (MP3)")
        self.btn_export.clicked.connect(self.exportar_audio_mp3)
        self.btn_export.setEnabled(False)
        linha1.addWidget(self.btn_export)

        self.btn_cancel_export = QPushButton("❌ Cancelar Exportação")
        self.btn_cancel_export.clicked.connect(self.cancelar_exportacao)
        self.btn_cancel_export.hide()
        linha1.addWidget(self.btn_cancel_export)
        
        linha1.addStretch()

        self.btn_sobre = QPushButton("💡 MeuLeitorPDF")
        self.btn_sobre.setStyleSheet("background-color: #4A4A4A; color: white;")
        self.btn_sobre.clicked.connect(self.mostrar_janela_sobre)
        linha1.addWidget(self.btn_sobre)

        # --- LINHA 2: CONTROLOS DE VOZ E LEITURA ---
        linha2 = QHBoxLayout()
        linha2.setAlignment(Qt.AlignmentFlag.AlignLeft)

        linha2.addWidget(QLabel("Voz:"))
        self.combo_vozes = QComboBox()
        vozes = [
            ("🇧🇷 Antônio", "pt-BR-AntonioNeural"), ("🇧🇷 Francisca", "pt-BR-FranciscaNeural"),
            ("🇵🇹 Duarte", "pt-PT-DuarteNeural"), ("🇵🇹 Raquel", "pt-PT-RaquelNeural"),
            ("🇪🇸 Álvaro", "es-ES-AlvaroNeural"), ("🇪🇸 Elvira", "es-ES-ElviraNeural"),
            ("🇺🇸 Guy", "en-US-GuyNeural"), ("🇺🇸 Jenny", "en-US-JennyNeural")
        ]
        for nome, codigo in vozes:
            self.combo_vozes.addItem(nome, codigo)
        self.combo_vozes.currentIndexChanged.connect(self.atualizar_parametros_voz)
        linha2.addWidget(self.combo_vozes)
        
        linha2.addWidget(QLabel("  Velocidade:"))
        self.combo_velocidade = QComboBox()
        velocidades = [
            ("0.5x", "-50%"), ("0.75x", "-25%"), ("1.0x (Normal)", "+0%"), 
            ("1.25x", "+25%"), ("1.5x", "+50%"), ("1.75x", "+75%"), 
            ("2.0x", "+100%"), ("2.5x", "+150%"), ("3.0x", "+200%")
        ]
        for nome, valor in velocidades:
            self.combo_velocidade.addItem(nome, valor)
        self.combo_velocidade.setCurrentIndex(2)
        self.combo_velocidade.currentIndexChanged.connect(self.atualizar_parametros_voz)
        linha2.addWidget(self.combo_velocidade)

        linha2.addSpacing(15)
        self.btn_read = QPushButton("▶ Ler")
        self.btn_read.clicked.connect(self.iniciar_leitura)
        self.btn_read.setEnabled(False)
        linha2.addWidget(self.btn_read)

        self.btn_pause = QPushButton("⏸ Pausar")
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_pause.setEnabled(False)
        linha2.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("⏹ Parar")
        self.btn_stop.clicked.connect(self.parar_leitura)
        self.btn_stop.setEnabled(False)
        linha2.addWidget(self.btn_stop)

        self.lbl_status = QLabel(f"  Status: Pronto{ATALHOS_TEXTO}")
        linha2.addWidget(self.lbl_status)
        
        linha2.addStretch()

        top_panel.addLayout(linha1)
        top_panel.addLayout(linha2)

        # --- ÁREA DO PDF ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.atualizar_paginas_visiveis)
        
        self.container_paginas = QWidget()
        self.layout_paginas = QVBoxLayout()
        self.layout_paginas.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.container_paginas.setLayout(self.layout_paginas)
        self.scroll_area.setWidget(self.container_paginas)

        main_layout.addLayout(top_panel)
        main_layout.addWidget(self.scroll_area)

        container_principal = QWidget()
        container_principal.setLayout(main_layout)
        self.setCentralWidget(container_principal)
        
        self.atualizar_parametros_voz() 

    def aplicar_estilo(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #e5e5e5; }
            QPushButton { background-color: #0078D7; color: white; border: none; border-radius: 4px; padding: 6px 12px; font-weight: bold; }
            QPushButton:hover { background-color: #005A9E; }
            QPushButton:disabled { background-color: #cccccc; color: #666666; }
            QPushButton#btn_stop { background-color: #D13438; }
            QPushButton#btn_stop:hover { background-color: #A4262C; }
            QPushButton#btn_cancel_export { background-color: #D13438; }
            QPushButton#btn_cancel_export:hover { background-color: #A4262C; }
            
            QComboBox { padding: 4px; border-radius: 3px; border: 1px solid #ccc; background: white; color: black; }
            QScrollArea { border: 1px solid #ccc; background-color: #2b2b2b; }
        """)
        self.btn_stop.setObjectName("btn_stop")
        self.btn_cancel_export.setObjectName("btn_cancel_export")

    def mostrar_janela_sobre(self):
        """Apresenta a janela de Sobre com o logotipo limpo e as suas informações."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Sobre o MeuLeitorPDF")
        dialog.resize(520, 490)
        
        layout = QVBoxLayout(dialog)
        
        # Cabeçalho com Logo e Título
        header_layout = QHBoxLayout()
        
        lbl_logo = QLabel()
        if os.path.exists("logo_pdf-bco.png"):
            pixmap = QPixmap("logo_pdf-bco.png").scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            lbl_logo.setPixmap(pixmap)
        header_layout.addWidget(lbl_logo)
        
        lbl_titulo = QLabel("<b>MeuLeitorPDF</b><br><span style='font-size:11pt; color:#555;'>Leitor Neural Avançado de Livros PDF</span>")
        header_layout.addWidget(lbl_titulo)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)

        # Conteúdo em Texto Formatado
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        
        html_conteudo = """
        <body style="font-family: Arial, sans-serif; font-size: 10pt; color: #333;">
            <b>✨ Funcionalidades Principais:</b>
            <ul>
                <li>Deteção automática de idioma (Português/Inglês/Espanhol) ao abrir o ficheiro.</li>
                <li>Leitura em 3 idiomas (Português/Inglês/Espanhol).</li>
                <li>Foco central estático: o texto desliza suavemente enquanto a linha ativa fica fixa no centro da tela.</li>
                <li>Sumário interativo em lista com barra de rolagem clássica (quando disponível no arquivo).</li>
                <li>Exportação completa do livro em formato MP3 (com opção de cancelamento).</li>
                <li>Modo Noturno (Inversão de Cores) e controlo de zoom dinâmico.</li>
            </ul>
            
            <b>⌨️ Atalhos de Teclado Úteis:</b>
            <ul>
                <li><b>Espaço:</b> Inicia a leitura / Pausa / Retoma.</li>
                <li><b>Ctrl + Espaço:</b> Para a leitura imediatamente.</li>
            </ul>
            
            <hr style="border:0; border-top:1px solid #ccc; margin:10px 0;">
            
            <b>Idealizado por Luis Roberto Porto Mendes</b><br>
            📫 <a href="mailto:lrpmendes@proton.me">lrpmendes@proton.me</a><br>
            Desenvolvido com Python, PyQt6 e Edge TTS.<br>
            <b>Versão 1.0</b><br><br>
            <b>Apoie o projeto</b> - Saiba como por e-mail.
        </body>
        """
        browser.setHtml(html_conteudo)
        layout.addWidget(browser)
        
        # Botão Fechar
        btn_fechar = QPushButton("Fechar")
        btn_fechar.clicked.connect(dialog.close)
        layout.addWidget(btn_fechar, alignment=Qt.AlignmentFlag.AlignRight)
        
        dialog.exec()

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Space:
            if self.btn_stop.isEnabled():
                self.parar_leitura()
        elif event.key() == Qt.Key.Key_Space:
            if not self.btn_stop.isEnabled():
                self.iniciar_leitura()
            else:
                self.toggle_pause()
        else:
            super().keyPressEvent(event)

    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode
        self.btn_dark.setText("☀️ Cores Normais" if self.dark_mode else "🌙 Inverter Cores")
        self.recalcular_tamanho_paginas() 

    def detetar_idioma_e_ajustar_voz(self):
        texto_amostra = ""
        for p in range(min(3, len(self.pdf_document))):
            page = self.pdf_document.load_page(p)
            texto_amostra += page.get_text("text").lower() + " "
            
        if not texto_amostra.strip():
            return

        palavras_pt = [" de ", " a ", " o ", " da ", " do ", " em ", " para ", " com ", " não ", " uma ", " os ", " no "]
        palavras_en = [" the ", " and ", " to ", " of ", " a ", " in ", " is ", " that ", " for ", " it ", " with ", " as "]
        palavras_es = [" de ", " la ", " el ", " y ", " en ", " los ", " del ", " se ", " las ", " por ", " un ", " para "]

        pontos_pt = sum(texto_amostra.count(p) for p in palavras_pt)
        pontos_en = sum(texto_amostra.count(p) for p in palavras_en)
        pontos_es = sum(texto_amostra.count(p) for p in palavras_es)

        max_pontos = max(pontos_pt, pontos_en, pontos_es)
        
        if max_pontos == pontos_en:
            alvo_codigo = "en-US-JennyNeural"
        elif max_pontos == pontos_es:
            alvo_codigo = "es-ES-AlvaroNeural"
        else:
            alvo_codigo = "pt-BR-AntonioNeural"
        
        for i in range(self.combo_vozes.count()):
            if self.combo_vozes.itemData(i) == alvo_codigo:
                self.combo_vozes.setCurrentIndex(i)
                break

    def carregar_capitulos(self):
        self.capitulos_dados.clear()
        if self.pdf_document:
            toc = self.pdf_document.get_toc()
            if toc:
                self.btn_capitulos.setEnabled(True)
                self.btn_capitulos.setText("Selecione um Capítulo ▼")
                for item in toc:
                    nivel, titulo, pagina = item
                    identacao = "  " * (nivel - 1)
                    self.capitulos_dados.append((f"{identacao}{titulo}", pagina - 1))
                return

        self.btn_capitulos.setEnabled(False)
        self.btn_capitulos.setText("--- Sumário Não Encontrado ---")

    def mostrar_painel_capitulos(self):
        if not self.capitulos_dados: return
        
        self.popup_dialog = QWidget(self, Qt.WindowType.Popup)
        self.popup_dialog.setWindowTitle("Sumário")
        self.popup_dialog.resize(450, 350)
        
        layout = QVBoxLayout(self.popup_dialog)
        layout.setContentsMargins(2, 2, 2, 2)
        
        lista_widget = QListWidget()
        lista_widget.setStyleSheet("font-size: 14px;")
        
        for titulo, pagina in self.capitulos_dados:
            lista_widget.addItem(titulo)
            
        lista_widget.itemClicked.connect(lambda item: self.selecionar_capitulo_popup(lista_widget.row(item)))
        
        layout.addWidget(lista_widget)
        
        pos_botao = self.btn_capitulos.mapToGlobal(QPoint(0, self.btn_capitulos.height()))
        self.popup_dialog.move(pos_botao)
        self.popup_dialog.show()

    def selecionar_capitulo_popup(self, index):
        if 0 <= index < len(self.capitulos_dados):
            titulo, pagina = self.capitulos_dados[index]
            self.btn_capitulos.setText(f"📖 {titulo.strip()[:28]}...")
            self.rolar_para_pagina(pagina)
            self.popup_dialog.close()

    def exportar_audio_mp3(self):
        if not self.pdf_document: return
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Salvar Audiobook do Livro", "livro_completo.mp3", "Áudio MP3 (*.mp3)")
        if not file_path: return

        self.cancelar_exportacao_flag = False
        self.btn_export.hide()
        self.btn_cancel_export.show()
        self.btn_cancel_export.setEnabled(True)

        pagina_inicio = 0
        pagina_fim = len(self.pdf_document)
                
        self.lbl_status.setText("Status: A iniciar exportação do livro...")
        threading.Thread(target=self._tarefa_exportar_mp3, args=(pagina_inicio, pagina_fim, file_path), daemon=True).start()

    def cancelar_exportacao(self):
        self.cancelar_exportacao_flag = True
        self.btn_cancel_export.setEnabled(False)
        self.lbl_status.setText("Status: A cancelar exportação...")

    def _tarefa_exportar_mp3(self, inicio, fim, caminho):
        try:
            async def _run():
                with open(caminho, 'wb') as f:
                    for p in range(inicio, fim):
                        if self.cancelar_exportacao_flag:
                            break
                        
                        self.sinais.status_exportacao.emit(f"Status: A exportar página {p+1} de {fim}...")
                        
                        page = self.pdf_document.load_page(p)
                        blocos = page.get_text("blocks")
                        texto_pag = ""
                        for bloco in blocos:
                            t = bloco[4].replace('\n', ' ').strip()
                            if t:
                                texto_pag += t + ("." if not re.search(r'[.!?:]$', t) else " ")
                                
                        if len(texto_pag.strip()) > 10:
                            communicate = edge_tts.Communicate(texto_pag.strip(), self.voz_atual, rate=self.velocidade_atual)
                            async for chunk in communicate.stream():
                                if self.cancelar_exportacao_flag:
                                    break
                                if chunk["type"] == "audio":
                                    f.write(chunk["data"])
                                    
                if self.cancelar_exportacao_flag:
                    try:
                        os.remove(caminho)
                    except:
                        pass
                    self.sinais.status_exportacao.emit(f"Status: Exportação cancelada.{ATALHOS_TEXTO}")
                else:
                    self.sinais.status_exportacao.emit(f"Status: Audiobook guardado com sucesso!{ATALHOS_TEXTO}")
            
            asyncio.run(_run())
        except Exception as e:
            self.sinais.status_exportacao.emit(f"Status: Erro ao exportar - {e}{ATALHOS_TEXTO}")
        finally:
            self.sinais.resetar_botoes_exportacao.emit()

    def reset_ui_exportacao(self):
        self.btn_cancel_export.hide()
        self.btn_export.show()
        self.btn_export.setEnabled(True)

    def atualizar_status(self, mensagem):
        self.lbl_status.setText(mensagem)

    def atualizar_parametros_voz(self):
        self.voz_atual = self.combo_vozes.currentData()
        self.velocidade_atual = self.combo_velocidade.currentData()
        if self.btn_stop.isEnabled():
            self.mudou_parametro_flag = True

    def reset_ui_botoes(self):
        self.btn_read.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.is_paused = False
        self.btn_pause.setText("⏸ Pausar")
        self.lbl_status.setText(f"  Status: Pronto{ATALHOS_TEXTO}")

    def zoom_in(self):
        self.zoom_factor += 0.2
        self.recalcular_tamanho_paginas()

    def zoom_out(self):
        if self.zoom_factor > 0.4:
            self.zoom_factor -= 0.2
            self.recalcular_tamanho_paginas()

    def abrir_pdf_dialog(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Selecione um PDF", "", "Arquivos PDF (*.pdf)")
        if file_name:
            self.abrir_pdf(file_name, 0)

    def abrir_pdf(self, file_path, pagina_inicial):
        try:
            self.pdf_document = pymupdf.open(file_path)
            self.pdf_path = file_path
            self.btn_read.setEnabled(True)
            self.btn_export.setEnabled(True)
            
            self.detetar_idioma_e_ajustar_voz()
            self.carregar_capitulos()
            self.montar_esqueleto_paginas()
            self.current_page = pagina_inicial
            
            nome_arquivo = os.path.basename(self.pdf_path)
            self.setWindowTitle(f"MeuLeitorPDF - 📖 {nome_arquivo}")
            
            self.ignorar_scroll_inicial = True
            QTimer.singleShot(300, lambda: self.rolar_para_pagina(pagina_inicial))
        except Exception as e:
            print(f"Erro ao abrir PDF: {e}")

    def montar_esqueleto_paginas(self):
        for lbl in self.page_labels:
            lbl.setParent(None)
        self.page_labels.clear()

        page = self.pdf_document.load_page(0)
        self.base_width = page.rect.width
        self.base_height = page.rect.height
        largura_atual = int(self.base_width * self.zoom_factor)
        altura_atual = int(self.base_height * self.zoom_factor)

        for i in range(len(self.pdf_document)):
            lbl = QLabel(f"A carregar Página {i+1}...")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedSize(largura_atual, altura_atual)
            lbl.setStyleSheet("background-color: #ffffff; margin-bottom: 15px;")
            lbl.has_pixmap = False
            self.layout_paginas.addWidget(lbl)
            self.page_labels.append(lbl)
        self.atualizar_paginas_visiveis()

    def recalcular_tamanho_paginas(self):
        if not self.pdf_document: return
        largura = int(self.base_width * self.zoom_factor)
        altura = int(self.base_height * self.zoom_factor)
        for lbl in self.page_labels:
            lbl.setFixedSize(largura, altura)
            lbl.has_pixmap = False
        self.atualizar_paginas_visiveis()

    def rolar_para_pagina(self, num_pagina):
        if num_pagina < len(self.page_labels):
            pos_y = self.page_labels[num_pagina].pos().y()
            self.scroll_area.verticalScrollBar().setValue(pos_y)
            self.ignorar_scroll_inicial = False 
            self.atualizar_paginas_visiveis()

    def atualizar_paginas_visiveis(self):
        if not self.page_labels: return
        scrollbar = self.scroll_area.verticalScrollBar()
        viewport_top = scrollbar.value()
        viewport_bottom = viewport_top + self.scroll_area.viewport().height()
        buffer_seguranca = 1000 
        centro_tela = viewport_top + (self.scroll_area.viewport().height() // 2)

        for i, lbl in enumerate(self.page_labels):
            lbl_top = lbl.pos().y()
            lbl_bottom = lbl_top + lbl.height()

            if (lbl_bottom >= viewport_top - buffer_seguranca) and (lbl_top <= viewport_bottom + buffer_seguranca):
                if not lbl.has_pixmap:
                    self.renderizar_pagina_unica(i, lbl)
                
                if lbl_top <= centro_tela <= lbl_bottom:
                    if self.current_page != i:
                        self.current_page = i
                        if not self.ignorar_scroll_inicial:
                            self.salvar_checkpoint()
            else:
                if lbl.has_pixmap:
                    lbl.clear()
                    lbl.setText(f"Página {i+1}")
                    lbl.has_pixmap = False

    def renderizar_pagina_unica(self, num_pagina, label):
        page = self.pdf_document.load_page(num_pagina)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(self.zoom_factor, self.zoom_factor))
        fmt = QImage.Format.Format_RGB888
        qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
        
        if self.dark_mode:
            qimg.invertPixels(QImage.InvertMode.InvertRgb)
            
        label.setPixmap(QPixmap.fromImage(qimg))
        label.has_pixmap = True

    def destacar_texto_na_tela(self, num_pagina, frase):
        if not self.pdf_document or num_pagina >= len(self.page_labels): return
        page = self.pdf_document.load_page(num_pagina)
        
        for annot in page.annots():
            if annot.info.get("title") == "Marcador":
                page.delete_annot(annot)
                
        frase_limpa = frase.strip()
        if len(frase_limpa) > 2:
            rects = page.search_for(frase_limpa)
            if rects:
                primeiro_rect = rects[0]
                texto_y_escalado = primeiro_rect.y0 * self.zoom_factor
                label_pagina = self.page_labels[num_pagina]
                posicao_absoluta_y = label_pagina.pos().y() + texto_y_escalado
                
                scrollbar = self.scroll_area.verticalScrollBar()
                viewport_altura = self.scroll_area.viewport().height()
                
                nova_posicao = int(posicao_absoluta_y - (viewport_altura / 2))
                scrollbar.setValue(nova_posicao)

                for rect in rects:
                    annot = page.add_highlight_annot(rect)
                    cor = (0.2, 0.6, 1.0) if self.dark_mode else (1.0, 0.9, 0.3)
                    annot.set_colors(stroke=cor)
                    annot.set_info({"title": "Marcador"})
                    annot.update()
                    
        label = self.page_labels[num_pagina]
        if label.has_pixmap:
            self.renderizar_pagina_unica(num_pagina, label)

    def limpar_todos_destaques(self):
        if not self.pdf_document: return
        page = self.pdf_document.load_page(self.current_page)
        for annot in page.annots():
            if annot.info.get("title") == "Marcador":
                page.delete_annot(annot)
        
        if self.current_page < len(self.page_labels):
            label = self.page_labels[self.current_page]
            if label.has_pixmap:
                self.renderizar_pagina_unica(self.current_page, label)

    def obter_frases(self, pagina_num):
        page = self.pdf_document.load_page(pagina_num)
        blocos = page.get_text("blocks")
        frases_finais = []
        
        for bloco in blocos:
            texto_bloco = bloco[4].replace('\n', ' ').strip()
            if not texto_bloco:
                continue
            
            frases_bloco = re.split(r'(?<=[.!?]) +', texto_bloco)
            for f in frases_bloco:
                f_limpa = f.strip()
                if len(f_limpa) >= 2:
                    frases_finais.append(f_limpa)
                    
        return frases_finais

    def obter_proxima_frase_valida(self, pagina, frase_idx, frases_atuais):
        prox_idx = frase_idx + 1
        p = pagina
        f_list = frases_atuais
        while True:
            if prox_idx < len(f_list):
                if len(f_list[prox_idx].strip()) >= 2:
                    return p, prox_idx, f_list[prox_idx]
                prox_idx += 1
            else:
                p += 1
                if p >= len(self.pdf_document):
                    return None, None, None
                f_list = self.obter_frases(p)
                prox_idx = 0

    def gerar_audio_neural(self, texto, voz, taxa_velocidade, arquivo):
        async def _run():
            communicate = edge_tts.Communicate(texto, voz, rate=taxa_velocidade)
            await communicate.save(arquivo)
        asyncio.run(_run())

    def toggle_pause(self):
        if self.is_paused:
            pygame.mixer.music.unpause()
            self.is_paused = False
            self.btn_pause.setText("⏸ Pausar")
            self.lbl_status.setText(f"  Status: A ler...{ATALHOS_TEXTO}")
        else:
            pygame.mixer.music.pause()
            self.is_paused = True
            self.btn_pause.setText("▶ Retomar")
            self.lbl_status.setText(f"  Status: Em pausa{ATALHOS_TEXTO}")

    def iniciar_leitura(self):
        if not self.pdf_document: return
        self.btn_read.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_pause.setEnabled(True)
        self.lbl_status.setText(f"  Status: A ler...{ATALHOS_TEXTO}")
        self.parar_flag = False
        self.mudou_parametro_flag = False
        threading.Thread(target=self._motor_fala, args=(self.current_page,), daemon=True).start()

    def _motor_fala(self, pagina_inicial):
        pagina = pagina_inicial
        frase_idx = 0
        frases = self.obter_frases(pagina)
        
        arquivo_pre_gerado = None
        id_pre_gerado = None 

        try:
            while pagina < len(self.pdf_document):
                if self.parar_flag: break

                if frase_idx >= len(frases):
                    pagina += 1
                    if pagina < len(self.pdf_document):
                        frases = self.obter_frases(pagina)
                        frase_idx = 0
                        self.sinais.mudar_pagina_scroll.emit(pagina)
                    continue

                frase = frases[frase_idx].strip()
                if len(frase) < 2:
                    frase_idx += 1
                    continue

                self.sinais.destacar_frase.emit(pagina, frase)
                v_voz = self.voz_atual
                v_vel = self.velocidade_atual
                
                texto_tts = frase
                if not re.search(r'[.!?:]$', texto_tts):
                    texto_tts += "."

                if arquivo_pre_gerado and id_pre_gerado == (pagina, frase_idx, v_voz, v_vel):
                    temp_file = arquivo_pre_gerado
                else:
                    temp_file = f"temp_audio_{uuid.uuid4().hex}.mp3"
                    self.gerar_audio_neural(texto_tts, v_voz, v_vel, temp_file)

                arquivo_pre_gerado = None
                id_pre_gerado = None

                pygame.mixer.music.load(temp_file)
                pygame.mixer.music.play()

                prox_p, prox_idx, prox_frase = self.obter_proxima_frase_valida(pagina, frase_idx, frases)
                if prox_frase and not self.parar_flag and not self.mudou_parametro_flag:
                    
                    texto_prox_tts = prox_frase.strip()
                    if not re.search(r'[.!?:]$', texto_prox_tts):
                        texto_prox_tts += "."
                        
                    prox_temp = f"temp_audio_{uuid.uuid4().hex}.mp3"
                    self.gerar_audio_neural(texto_prox_tts, v_voz, v_vel, prox_temp)
                    arquivo_pre_gerado = prox_temp
                    id_pre_gerado = (prox_p, prox_idx, v_voz, v_vel)

                interrompido_por_mudanca = False
                
                while pygame.mixer.music.get_busy() or self.is_paused:
                    if self.parar_flag:
                        pygame.mixer.music.stop()
                        break
                    
                    if self.mudou_parametro_flag:
                        self.mudou_parametro_flag = False
                        interrompido_por_mudanca = True
                        pygame.mixer.music.stop()
                        break

                    pygame.time.Clock().tick(20)

                try: os.remove(temp_file)
                except: pass

                if interrompido_por_mudanca:
                    if arquivo_pre_gerado:
                        try: os.remove(arquivo_pre_gerado)
                        except: pass
                        arquivo_pre_gerado = None
                    continue

                frase_idx += 1

        except Exception as e:
            print(f"Erro no motor de leitura: {e}")
        finally:
            if arquivo_pre_gerado:
                try: os.remove(arquivo_pre_gerado)
                except: pass
            self.limpar_todos_destaques()
            self.sinais.resetar_botoes.emit()

    def parar_leitura(self):
        self.parar_flag = True
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
        self.limpar_todos_destaques()

    def salvar_checkpoint(self):
        if self.pdf_path:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({"ultimo_pdf": self.pdf_path, "pagina": self.current_page}, f)

    def carregar_checkpoint(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    dados = json.load(f)
                ultimo_pdf = dados.get("ultimo_pdf")
                if ultimo_pdf and os.path.exists(ultimo_pdf):
                    self.abrir_pdf(ultimo_pdf, dados.get("pagina", 0))
            except Exception:
                pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LeitorPDF()
    window.show()
    exit_code = app.exec()
    
    for file in os.listdir():
        if file.startswith("temp_audio_") and file.endswith(".mp3"):
            try: os.remove(file)
            except: pass
            
    sys.exit(exit_code)