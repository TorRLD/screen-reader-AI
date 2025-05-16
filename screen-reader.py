"""
AI-NVDA: Leitor de tela aprimorado com IA
Uma alternativa leve ao NVDA que combina APIs de acessibilidade com visão computacional
"""

import os
import time
import logging
import configparser
import threading
import queue
import json
from enum import Enum
import sys
import keyboard
import numpy as np
import torch
from PIL import Image, ImageGrab
import cv2
import pyttsx3
from transformers import AutoTokenizer, AutoModelForCausalLM
from huggingface_hub import login
# Adicionar após as importações existentes
import easyocr
import ctypes
# Adicionar após as importações existentes (logo após AutoModelForCausalLM)
from transformers import AutoModelForCausalLM, AutoModelForSequenceClassification

# Verificar e instalar dependências
try:
    import comtypes
except ImportError:
    print("Instalando pacote comtypes...")
    import subprocess
    subprocess.check_call(["pip", "install", "comtypes"])
    import comtypes

try:
    import uiautomation
except ImportError:
    print("Instalando pacote uiautomation...")
    import subprocess
    subprocess.check_call(["pip", "install", "uiautomation"])
    import uiautomation
    
# Adicione seu token aqui - substitua "seu_token_aqui" pelo token que você gerou
login("")

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ai_screen_reader.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("AI-NVDA")

# Classe para diferentes tipos de elementos de UI
class UIElementType(Enum):
    BUTTON = "botão"
    TEXT_FIELD = "campo de texto"
    CHECKBOX = "caixa de seleção"
    RADIO = "botão de opção"
    DROPDOWN = "menu suspenso"
    LINK = "link"
    IMAGE = "imagem"
    HEADING = "título"
    PARAGRAPH = "texto"
    UNKNOWN = "elemento desconhecido"

class UIElement:
    """Representa um elemento de interface detectado na tela"""
    
    def __init__(self, element_type, position, text="", confidence=0.0, accessibility_id=None):
        self.element_type = element_type
        self.position = position  # (x1, y1, x2, y2)
        self.text = text
        self.confidence = confidence
        self.accessibility_id = accessibility_id
        self.description = ""
    
    def __str__(self):
        if self.text:
            return f"{self.element_type.value}: {self.text}"
        return f"{self.element_type.value}"

class HTMLAccessibilityManager:
    """Gerencia a extração de informações de acessibilidade de elementos HTML em navegadores"""
    
    def __init__(self, accessibility_manager=None):
        self.platform = sys.platform
        self.accessibility_manager = accessibility_manager
        logger.info(f"Inicializando gerenciador de acessibilidade HTML para plataforma: {self.platform}")
        
        # Importar bibliotecas específicas para cada navegador
        self.browsers = {
            'chrome': False,
            'firefox': False,
            'edge': False,
            'opera': False,
            'safari': False
        }
        
        # Inicializar atributos
        self.available = False
        self.has_uiautomation = False
        
        try:
            if self.platform == 'win32':
                import comtypes.client
                import win32gui
                import win32con
                
                self.comtypes = comtypes
                self.win32gui = win32gui
                self.win32con = win32con
                
                # Tentar importar uiautomation
                try:
                    import uiautomation as auto
                    self.auto = auto
                    self.has_uiautomation = True
                except ImportError:
                    self.has_uiautomation = False
                
                self.available = True
                logger.info("APIs de acessibilidade HTML para Windows inicializadas")
            elif self.platform == 'darwin':  # macOS
                # Importações para macOS
                try:
                    import AppKit
                    import Quartz
                    self.AppKit = AppKit
                    self.Quartz = Quartz
                    self.available = True
                    logger.info("APIs de acessibilidade HTML para macOS inicializadas")
                except ImportError:
                    self.available = False
            elif self.platform.startswith('linux'):
                # Importações para Linux
                try:
                    import pyatspi
                    self.pyatspi = pyatspi
                    self.available = True
                    logger.info("APIs de acessibilidade HTML para Linux inicializadas")
                except ImportError:
                    self.available = False
            else:
                logger.warning(f"Plataforma {self.platform} não suportada para acessibilidade HTML")
                self.available = False
                
        except Exception as e:
            logger.error(f"Erro ao inicializar gerenciador de acessibilidade HTML: {e}")
            self.available = False
    
    def detect_browser(self):
        """Detecta qual navegador está em uso atualmente"""
        try:
            if self.platform == 'win32':
                hwnd = self.win32gui.GetForegroundWindow()
                title = self.win32gui.GetWindowText(hwnd)
                class_name = self.win32gui.GetClassName(hwnd)
                
                browsers = {
                    'chrome': ('Chrome', 'Chrome_WidgetWin_1'),
                    'edge': ('Edge', 'Chrome_WidgetWin_1'),  # Edge usa mesma classe que Chrome
                    'firefox': ('Firefox', 'MozillaWindowClass'),
                    'opera': ('Opera', 'Chrome_WidgetWin_1'),  # Opera também usa Chrome
                    'safari': ('Safari', 'SafariWnd')
                }
                
                for browser, (name, cls) in browsers.items():
                    if name.lower() in title.lower() or cls == class_name:
                        logger.info(f"Navegador detectado: {browser}")
                        return browser
            
            elif self.platform == 'darwin':  # macOS
                try:
                    frontmost_app = self.AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
                    app_name = frontmost_app.localizedName().lower()
                    
                    if 'chrome' in app_name:
                        return 'chrome'
                    elif 'firefox' in app_name:
                        return 'firefox'
                    elif 'safari' in app_name:
                        return 'safari'
                    elif 'edge' in app_name:
                        return 'edge'
                    elif 'opera' in app_name:
                        return 'opera'
                except:
                    pass
            
            elif self.platform.startswith('linux'):
                try:
                    desktop = self.pyatspi.Registry.getDesktop(0)
                    for app in desktop:
                        app_name = app.name.lower()
                        if any(browser in app_name for browser in ['chrome', 'firefox', 'edge', 'opera']):
                            return next(browser for browser in ['chrome', 'firefox', 'edge', 'opera'] if browser in app_name)
                except:
                    pass
                    
            return None
        except Exception as e:
            logger.error(f"Erro ao detectar navegador: {e}")
            return None
    
    def get_html_accessibility_tree(self, region=None):
        """Obtém a árvore de acessibilidade da página web atual"""
        browser = self.detect_browser()
        if not browser or not self.available:
            return []
        
        try:
            if self.platform == 'win32':
                # Usar abordagem baseada em uiautomation
                if self.has_uiautomation:
                    return self._get_tree_with_uiautomation(region)
                else:
                    # Fallback para outro método
                    return []
            
            # Implementações para outras plataformas...
            return []
        
        except Exception as e:
            logger.error(f"Erro ao obter árvore de acessibilidade HTML: {e}")
            return []
    
    def _get_tree_with_uiautomation(self, region=None):
        """Obtém a árvore de acessibilidade usando a biblioteca uiautomation"""
        elements = []
        
        try:
            # Usar janela em primeiro plano
            hwnd = self.win32gui.GetForegroundWindow()
            
            # Obter elemento raiz
            root = self.auto.ControlFromHandle(hwnd)
            if not root:
                return []
            
            # Função recursiva para extrair elementos
            def extract_elements(element, depth=0):
                if depth > 10:  # Limitar profundidade para evitar loop infinito
                    return
                
                try:
                    # Extrair informações do elemento
                    name = element.Name
                    control_type = element.ControlTypeName
                    
                    # Obter retângulo
                    rect = element.BoundingRectangle
                    position = (rect.left, rect.top, rect.right, rect.bottom)
                    
                    # Verificar se está na região de interesse
                    if region:
                        x1, y1, x2, y2 = region
                        if rect.right < x1 or rect.left > x2 or rect.bottom < y1 or rect.top > y2:
                            # Processar filhos mesmo se o pai estiver fora da região
                            for child in element.GetChildren():
                                extract_elements(child, depth + 1)
                            return
                    
                    # Mapear tipo de elemento
                    element_type = UIElementType.UNKNOWN
                    if "button" in control_type.lower():
                        element_type = UIElementType.BUTTON
                    elif "edit" in control_type.lower():
                        element_type = UIElementType.TEXT_FIELD
                    elif "hyperlink" in control_type.lower():
                        element_type = UIElementType.LINK
                    elif "checkbox" in control_type.lower():
                        element_type = UIElementType.CHECKBOX
                    elif "radiobutton" in control_type.lower():
                        element_type = UIElementType.RADIO
                    elif "text" in control_type.lower():
                        element_type = UIElementType.PARAGRAPH
                    elif "image" in control_type.lower():
                        element_type = UIElementType.IMAGE
                    
                    # Adicionar elemento se tiver dimensão razoável
                    width = rect.right - rect.left
                    height = rect.bottom - rect.top
                    
                    if width > 5 and height > 5:
                        ui_element = UIElement(
                            element_type,
                            position,
                            text=name,
                            confidence=0.9,
                            accessibility_id="html_element"
                        )
                        
                        elements.append(ui_element)
                
                except Exception as e:
                    logger.debug(f"Erro ao extrair informações do elemento: {e}")
                
                # Processar filhos
                for child in element.GetChildren():
                    extract_elements(child, depth + 1)
            
            # Iniciar processamento
            extract_elements(root)
            
            return elements
        
        except Exception as e:
            logger.error(f"Erro ao usar uiautomation: {e}")
            return []
    
    def get_focused_html_element(self):
        """Obtém o elemento HTML atualmente em foco"""
        browser = self.detect_browser()
        if not browser or not self.available:
            return None
            
        try:
            if self.platform == 'win32' and self.has_uiautomation:
                # Usar uiautomation para obter elemento em foco
                try:
                    focused = self.auto.GetFocusedElement()
                    if not focused:
                        return None
                    
                    # Extrair informações
                    name = focused.Name
                    control_type = focused.ControlTypeName
                    
                    # Obter retângulo
                    rect = focused.BoundingRectangle
                    position = (rect.left, rect.top, rect.right, rect.bottom)
                    
                    # Mapear tipo de elemento
                    element_type = UIElementType.UNKNOWN
                    if "button" in control_type.lower():
                        element_type = UIElementType.BUTTON
                    elif "edit" in control_type.lower():
                        element_type = UIElementType.TEXT_FIELD
                    elif "hyperlink" in control_type.lower():
                        element_type = UIElementType.LINK
                    elif "checkbox" in control_type.lower():
                        element_type = UIElementType.CHECKBOX
                    elif "radiobutton" in control_type.lower():
                        element_type = UIElementType.RADIO
                    
                    # Criar elemento
                    element = UIElement(
                        element_type,
                        position,
                        text=name,
                        confidence=0.9,
                        accessibility_id="html_focused"
                    )
                    
                    return element
                
                except Exception as e:
                    logger.debug(f"Erro ao obter elemento em foco: {e}")
            
            return None
                
        except Exception as e:
            logger.error(f"Erro ao obter elemento HTML em foco: {e}")
            
        return None

class AccessibilityManager:
    """Gerencia a integração com APIs de acessibilidade do sistema operacional"""
    
    def __init__(self):
        self.platform = sys.platform
        logger.info(f"Inicializando gerenciador de acessibilidade para plataforma: {self.platform}")
        
        # Importa as bibliotecas específicas da plataforma apenas quando necessário
        if self.platform == 'win32':
            try:
                import pywinauto
                import comtypes.client
                import win32gui
                import win32con
                self.pywinauto = pywinauto
                self.comtypes = comtypes
                self.win32gui = win32gui
                self.win32con = win32con
                self.available = True
                logger.info("APIs de acessibilidade do Windows inicializadas com sucesso")
            except ImportError:
                logger.warning("Não foi possível importar as bibliotecas de acessibilidade do Windows")
                self.available = False
        elif self.platform == 'darwin':  # macOS
            try:
                import pyautogui
                import Quartz
                self.pyautogui = pyautogui
                self.Quartz = Quartz
                self.available = True
                logger.info("APIs de acessibilidade do macOS inicializadas com sucesso")
            except ImportError:
                logger.warning("Não foi possível importar as bibliotecas de acessibilidade do macOS")
                self.available = False
        elif self.platform.startswith('linux'):
            try:
                import pyatspi
                self.pyatspi = pyatspi
                self.available = True
                logger.info("APIs de acessibilidade do Linux (AT-SPI) inicializadas com sucesso")
            except ImportError:
                logger.warning("Não foi possível importar as bibliotecas de acessibilidade do Linux")
                self.available = False
        else:
            logger.warning(f"Plataforma {self.platform} não suportada para acessibilidade nativa")
            self.available = False
    
    def get_focused_element(self):
        """Obtém o elemento atualmente em foco no sistema"""
        if not self.available:
            logger.debug("APIs de acessibilidade não disponíveis para obter elemento em foco")
            return None
        
        try:
            if self.platform == 'win32':
                # Obtém informações básicas da janela em foco
                hwnd = self.win32gui.GetForegroundWindow()
                
                if not hwnd:
                    logger.debug("Nenhuma janela em foco encontrada")
                    return None
                    
                # Obter informações básicas com funções mais confiáveis
                try:
                    rect = self.win32gui.GetWindowRect(hwnd)
                    title = self.win32gui.GetWindowText(hwnd)
                    logger.debug(f"Janela em foco: title='{title}', hwnd={hwnd}")
                    
                    # Criar elemento básico com as informações que já temos
                    element = UIElement(
                        UIElementType.UNKNOWN,
                        rect,
                        text=title,
                        accessibility_id=str(hwnd)
                    )
                except Exception as e:
                    logger.error(f"Erro ao obter informações básicas da janela: {e}")
                    return None
                
                # Tentar obter informações adicionais através do UIAutomation (se falhar, ainda teremos o elemento básico)
                try:
                    automation = self.comtypes.client.CreateObject("UIAutomationClient.CUIAutomation")
                    ui_element = automation.ElementFromHandle(hwnd)
                    
                    if ui_element:
                        # Tentar obter nome através de propriedade mais básica
                        try:
                            name_property = ui_element.GetCurrentPropertyValue(automation.UIA_NamePropertyId)
                            if name_property and not element.text:
                                element.text = name_property
                                logger.debug(f"Nome obtido via UIA: {name_property}")
                        except Exception as e:
                            logger.debug(f"Não foi possível obter nome via UIA: {e}")
                        
                        # Tentar obter valor somente se necessário e de forma segura
                        if not element.text:
                            try:
                                # Verificar primeiro se o padrão é suportado
                                supported = ui_element.GetCurrentPropertyValue(automation.UIA_IsValuePatternAvailablePropertyId)
                                
                                if supported:
                                    pattern = ui_element.GetCurrentPattern(automation.UIA_ValuePatternId)
                                    if pattern:
                                        value_pattern = pattern.QueryInterface(automation.IUIAutomationValuePattern)
                                        value = value_pattern.CurrentValue
                                        element.text = value
                                        logger.debug(f"Valor obtido via UIA: {value}")
                            except Exception as e:
                                logger.debug(f"Não foi possível obter valor via UIA: {e}")
                
                except Exception as e:
                    logger.debug(f"UIAutomation avançado falhou, usando informações básicas: {e}")
                    # Continuamos com as informações básicas obtidas anteriormente
                    
                return element
                
            elif self.platform == 'darwin':
                # Implementação para macOS permanece a mesma
                active_app = self.Quartz.CGWindowListCopyWindowInfo(
                    self.Quartz.kCGWindowListOptionOnScreenOnly, 
                    self.Quartz.kCGNullWindowID
                )
                
                for app in active_app:
                    if app['kCGWindowLayer'] == 0:  # Janela em foco
                        bounds = app['kCGWindowBounds']
                        return UIElement(
                            UIElementType.UNKNOWN,
                            (bounds['X'], bounds['Y'], bounds['X'] + bounds['Width'], bounds['Y'] + bounds['Height']),
                            text=app.get('kCGWindowOwnerName', '')
                        )
            
            elif self.platform.startswith('linux'):
                # Implementação para Linux permanece a mesma
                desktop = self.pyatspi.Registry.getDesktop(0)
                active_window = None
                
                for app in desktop:
                    for window in app:
                        if window.getState().contains(self.pyatspi.STATE_ACTIVE):
                            active_window = window
                            break
                
                if active_window:
                    component = active_window.queryComponent()
                    extents = component.getExtents(self.pyatspi.DESKTOP_COORDS)
                    return UIElement(
                        UIElementType.UNKNOWN,
                        (extents.x, extents.y, extents.x + extents.width, extents.y + extents.height),
                        text=active_window.name
                    )
        
        except Exception as e:
            logger.error(f"Erro ao obter elemento em foco: {e}")
            logger.debug(f"Detalhes do erro:", exc_info=True)
        
        return None
    
    def get_elements_in_region(self, region):
        """Obtém todos os elementos da interface em uma região específica"""
        if not self.available:
            return []
        
        elements = []
        try:
            if self.platform == 'win32':
                # Implementação para Windows
                automation = self.comtypes.client.CreateObject("UIAutomationClient.CUIAutomation")
                root = automation.GetRootElement()
                
                # Cria uma condição para encontrar elementos dentro da região
                condition = automation.CreateTrueCondition()
                
                # Obtém todos os elementos
                walker = automation.CreateTreeWalker(condition)
                element = walker.GetFirstChildElement(root)
                
                while element:
                    try:
                        pattern = element.GetCurrentPattern(automation.UIA_LegacyIAccessiblePatternId)
                        if pattern:
                            acc_pattern = pattern.QueryInterface(automation.IUIAutomationLegacyIAccessiblePattern)
                            role = acc_pattern.CurrentRole
                            name = acc_pattern.CurrentName
                            
                            # Mapeia os roles para tipos de elementos
                            element_type = UIElementType.UNKNOWN
                            if role == 0x2B:  # ROLE_SYSTEM_PUSHBUTTON
                                element_type = UIElementType.BUTTON
                            elif role == 0x2A:  # ROLE_SYSTEM_WINDOW
                                element_type = UIElementType.UNKNOWN
                            elif role == 0x29:  # ROLE_SYSTEM_TEXT
                                element_type = UIElementType.TEXT_FIELD
                            elif role == 0x2C:  # ROLE_SYSTEM_CHECKBOX
                                element_type = UIElementType.CHECKBOX
                            elif role == 0x2D:  # ROLE_SYSTEM_RADIOBUTTON
                                element_type = UIElementType.RADIO
                            elif role == 0x2F:  # ROLE_SYSTEM_LINK
                                element_type = UIElementType.LINK
                            
                            # Obtém a posição do elemento
                            rect = element.CurrentBoundingRectangle
                            position = (rect.left, rect.top, rect.right, rect.bottom)
                            
                            # Verifica se o elemento está na região especificada
                            if (position[0] >= region[0] and position[1] >= region[1] and
                                position[2] <= region[2] and position[3] <= region[3]):
                                
                                elements.append(UIElement(
                                    element_type,
                                    position,
                                    text=name,
                                    accessibility_id=str(role)
                                ))
                    except Exception as e:
                        logger.debug(f"Erro ao processar elemento: {e}")
                    
                    element = walker.GetNextSiblingElement(element)
            
            # Implementações para outras plataformas podem ser adicionadas aqui
        
        except Exception as e:
            logger.error(f"Erro ao obter elementos na região: {e}")
        
        return elements
    def get_keyboard_focused_element(self):
        """Obtém o elemento atualmente em foco via teclado (TAB) usando abordagem alternativa"""
        if not self.available:
            logger.debug("APIs de acessibilidade não disponíveis para obter foco de teclado")
            return None
        
        try:
            if self.platform == 'win32':
                # Usar Win32 API direto em vez de UIA
                hwnd = self.win32gui.GetFocus()
                if not hwnd:
                    # Tentar obter a janela em primeiro plano
                    hwnd = self.win32gui.GetForegroundWindow()
                    
                if hwnd:
                    # Obter retângulo e título
                    rect = self.win32gui.GetWindowRect(hwnd)
                    title = self.win32gui.GetWindowText(hwnd)
                    classname = self.win32gui.GetClassName(hwnd)
                    
                    logger.info(f"Elemento focado por teclado: '{title}', classe: {classname}")
                    
                    # Determinar tipo baseado na classe da janela
                    element_type = UIElementType.UNKNOWN
                    if 'button' in classname.lower():
                        element_type = UIElementType.BUTTON
                    elif 'edit' in classname.lower():
                        element_type = UIElementType.TEXT_FIELD
                    elif 'check' in classname.lower():
                        element_type = UIElementType.CHECKBOX
                    elif 'link' in classname.lower():
                        element_type = UIElementType.LINK
                    
                    # Criar elemento
                    return UIElement(
                        element_type,
                        rect,  # (left, top, right, bottom)
                        text=title,
                        accessibility_id="tab_focused"
                    )
            
            return None
        
        except Exception as e:
            logger.error(f"Erro ao obter elemento em foco via teclado: {e}")
            logger.debug("Tentando método alternativo de detecção...")
            
            # Método alternativo: capturar a área ao redor do ponto de inserção de texto
            try:
                # Obter posição do cursor de texto (caret)
                import win32gui
                import win32con
                
                # Estrutura para receber informações sobre o cursor
                class POINT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
                
                # Obter posição do cursor
                pt = POINT()
                if ctypes.windll.user32.GetCaretPos(ctypes.byref(pt)):
                    x, y = pt.x, pt.y
                    
                    # Capturar região ao redor do cursor
                    region = (max(0, x - 50), max(0, y - 50), x + 50, y + 50)
                    
                    # Tentar obtenção visual
                    screenshot = self.capture_screen_region(region)
                    if screenshot:
                        # Usar visão computacional como fallback
                        elements = self.vision_manager.detect_elements(screenshot)
                        
                        if elements:
                            # Encontrar elemento mais próximo ao cursor
                            nearest = elements[0]
                            for elem in elements:
                                # Ajustar coordenadas para global
                                global_pos = (
                                    elem.position[0] + region[0],
                                    elem.position[1] + region[1],
                                    elem.position[2] + region[0],
                                    elem.position[3] + region[1]
                                )
                                
                                # Criar elemento com coordenadas globais
                                nearest = UIElement(
                                    elem.element_type,
                                    global_pos,
                                    elem.text,
                                    accessibility_id="tab_focused"
                                )
                                break
                            
                            return nearest
            except:
                pass
            
            return None

class VisionManager:
    """Gerencia a detecção visual de elementos da interface usando visão computacional"""
    
    def __init__(self, config):
        self.config = config
        
        # Configurações do modelo de visão
        model_path = self.config.get('vision', 'model_path', fallback='models')
        
        # Cache para resultados de OCR
        self.ocr_cache = {}  # Cache para resultados OCR
        self.cache_max_size = 100  # Limitar tamanho do cache
        
        # Carregar modelo de detecção de elementos UI (pode ser YOLO, Faster R-CNN, etc.)
        try:
            logger.info("Inicializando modelos de visão computacional")
            # Aqui usaremos um detector baseado em OpenCV por simplicidade
            # Em uma implementação real, seria melhor usar um modelo treinado específico
            self.initialize_cv_detectors()
            
            # Inicializar leitor OCR
            logger.info("Inicializando motor OCR para português...")
            try:
                # Lista de idiomas - 'pt' para português, 'en' para inglês
                self.reader = easyocr.Reader(['pt', 'en'], gpu=False)
                logger.info("Motor OCR inicializado com sucesso")
            except Exception as e:
                logger.error(f"Erro ao inicializar OCR: {e}")
                self.reader = None
            
            logger.info("Modelos de visão computacional carregados com sucesso")
        except Exception as e:
            logger.error(f"Erro ao carregar modelos de visão: {e}")
    
    def identify_social_media_button(self, image, position):
        """Identifica botões específicos de redes sociais usando templates e comparação de características"""
        try:
            # Definir padrões comuns de botões de redes sociais com seus textos correspondentes
            social_buttons = {
                "curtir": ["gosto", "curtir", "like", "curti"],
                "comentar": ["comentar", "comment", "comentário"],
                "compartilhar": ["compartilhar", "share", "partilhar"],
                "seguir": ["seguir", "follow", "adicionar amigo", "adicionar"],
                "enviar": ["enviar", "send", "publicar", "postar", "post"]
            }
            
            # Extrair a região do botão
            x1, y1, x2, y2 = position
            width = x2 - x1
            height = y2 - y1
            
            # Se é realmente pequeno, provavelmente é um ícone
            if width < 30 and height < 30:
                # Verificar características visuais específicas para ícones comuns
                
                # Converter para escala de cinza e processar
                if isinstance(image, Image.Image):
                    button_roi = image.crop((x1, y1, x2, y2))
                    button_cv = cv2.cvtColor(np.array(button_roi), cv2.COLOR_RGB2BGR)
                else:
                    button_cv = image[y1:y2, x1:x2]
                
                gray = cv2.cvtColor(button_cv, cv2.COLOR_BGR2GRAY)
                
                # Extrair características básicas
                mean_brightness = cv2.mean(gray)[0]
                _, thresholded = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
                white_ratio = np.sum(thresholded == 255) / (width * height)
                
                # Detectar formas
                contours, _ = cv2.findContours(thresholded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                # Baseado nas características, identificar ícones comuns
                if len(contours) == 1:
                    cnt = contours[0]
                    x, y, w, h = cv2.boundingRect(cnt)
                    aspect_ratio = float(w) / h if h > 0 else 0
                    
                    # Detectar ícone de curtir (forma de coração/polegar)
                    if 0.8 <= aspect_ratio <= 1.2 and white_ratio > 0.4:
                        return "curtir"
                    
                    # Detectar ícone de comentar (forma de balão)
                    if 0.9 <= aspect_ratio <= 1.5 and white_ratio > 0.3 and white_ratio < 0.7:
                        return "comentar"
                    
                    # Detectar ícone de compartilhar (geralmente uma seta)
                    if aspect_ratio > 1.5 and white_ratio < 0.4:
                        return "compartilhar"
                
                # Se não conseguiu identificar por forma, tente o OCR com limiar muito baixo
                text = self.extract_text_with_ocr(image, position, optimize_for_ui=True)
                
                if text:
                    text_lower = text.lower()
                    # Verificar se o texto corresponde a algum dos padrões conhecidos
                    for action, keywords in social_buttons.items():
                        if any(keyword in text_lower for keyword in keywords):
                            return action
            
            # Para botões maiores, confiar no OCR padrão
            else:
                text = self.extract_text_with_ocr(image, position, optimize_for_ui=True)
                if text:
                    text_lower = text.lower()
                    for action, keywords in social_buttons.items():
                        if any(keyword in text_lower for keyword in keywords):
                            return action
            
            return None
            
        except Exception as e:
            logger.error(f"Erro na identificação de botão de rede social: {e}")
            return None

    def initialize_cv_detectors(self):
        """Inicializa detectores baseados em OpenCV"""
        # Cascade para botões (aproximação simples)
        cascade_path = os.path.join('models', 'haarcascade_frontalface_default.xml')
        if os.path.exists(cascade_path):
            self.button_cascade = cv2.CascadeClassifier(cascade_path)
        else:
            logger.warning(f"Arquivo de cascade não encontrado: {cascade_path}")
            self.button_cascade = None
    
    def detect_elements(self, image):
        """Detecta elementos de UI em uma imagem usando visão computacional com regiões expandidas para melhor OCR"""
        elements = []
        
        try:
            # Converter imagem para formato OpenCV
            if isinstance(image, Image.Image):
                cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            else:
                cv_image = image
            
            # Dimensões da imagem
            altura, largura = cv_image.shape[:2]
            logger.info(f"Analisando imagem de {largura}x{altura} pixels")
            
            # Converter para escala de cinza para processamento
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
            
            # Aplicar suavização para reduzir ruído
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            
            # Detecção de bordas com limiar mais baixo para capturar mais elementos
            edges = cv2.Canny(blurred, 20, 80)  # Valores menores para maior sensibilidade
            
            # Dilatação para conectar bordas próximas
            kernel = np.ones((3, 3), np.uint8)
            dilated = cv2.dilate(edges, kernel, iterations=2)
            
            # Encontrar contornos
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            logger.info(f"Contornos detectados: {len(contours)}")
            
            # Filtrar contornos
            filtered_contours = []
            for contour in contours:
                area = cv2.contourArea(contour)
                # Reduzir o limite mínimo para capturar elementos menores
                if area > 20:  # Era 100, agora muito menor
                    filtered_contours.append(contour)
            
            logger.info(f"Contornos após filtragem: {len(filtered_contours)}")
            
            # Coletar regiões para OCR e informações dos elementos
            regions = []
            element_types = []
            element_positions = []
            
            # Classificar elementos e coletar regiões
            for contour in filtered_contours:
                x, y, w, h = cv2.boundingRect(contour)
                
                # Determinar tipo com base na forma
                aspect_ratio = float(w) / h if h > 0 else 0
                
                if w < 30 and h < 30 and abs(w - h) < 10:
                    # Elementos pequenos e quadrados (botões, checkboxes)
                    element_type = UIElementType.CHECKBOX
                elif 1.5 <= aspect_ratio <= 4 and w > 30:
                    # Retângulos horizontais de tamanho médio (botões)
                    element_type = UIElementType.BUTTON
                elif aspect_ratio > 4:
                    # Retângulos muito horizontais (campos de texto, barras)
                    element_type = UIElementType.TEXT_FIELD
                else:
                    element_type = UIElementType.UNKNOWN
                
                # Armazenar informações originais
                regions.append((x, y, x+w, y+h))
                element_types.append(element_type)
                element_positions.append((x, y, x+w, y+h))
            
            # Obter o título da janela atual para adaptar o OCR
            window_title = ""
            try:
                import win32gui
                hwnd = win32gui.GetForegroundWindow()
                window_title = win32gui.GetWindowText(hwnd)
            except:
                pass
            
            # Filtrar apenas regiões grandes o suficiente para OCR e expandir-las
            ocr_regions = []
            element_indices = []  # Para mapear regiões OCR de volta aos elementos
            
            for i, (x1, y1, x2, y2) in enumerate(regions):
                width = x2 - x1
                height = y2 - y1
                if width >= 20 and height >= 10:  # Mínimo de 20x10 pixels para ter texto legível
                    # Expandir a região em 8 pixels em cada direção para capturar palavras completas
                    expanded_region = (
                        max(0, x1 - 8),
                        max(0, y1 - 8),
                        min(largura, x2 + 8),
                        min(altura, y2 + 8)
                    )
                    ocr_regions.append(expanded_region)
                    element_indices.append(i)
            
            # Processar OCR apenas nas regiões filtradas e expandidas
            element_texts = [""] * len(regions)  # Inicializar todos com string vazia
            
            if ocr_regions:
                logger.info(f"Processando OCR em lote para {len(ocr_regions)} regiões de um total de {len(regions)}")
                
                # Processar OCR com regiões expandidas
                ocr_results = self.batch_process_ocr(cv_image, ocr_regions, max_batch=8, window_title=window_title)
                
                # Mapear resultados OCR de volta para os elementos corretos
                for i, text in enumerate(ocr_results):
                    if i < len(element_indices):
                        original_index = element_indices[i]
                        element_texts[original_index] = text
            
            # Criar os objetos UIElement com os resultados
            for i in range(len(regions)):
                elements.append(UIElement(
                    element_types[i],
                    element_positions[i],
                    text=element_texts[i],
                    confidence=0.6
                ))
            
            logger.info(f"Total de elementos UI identificados: {len(elements)}")
            
            # Contar elementos com texto para diagnóstico
            text_elements = 0
            for elem in elements:
                if elem.text and len(elem.text.strip()) > 0:
                    text_elements += 1
            
            logger.info(f"Elementos com texto detectado: {text_elements}")
            
            # Mostrar elementos detectados com texto para debug
            if len(filtered_contours) > 0:
                debug_img = cv_image.copy()
                
                for elem in elements:
                    p1 = (elem.position[0], elem.position[1])
                    p2 = (elem.position[2], elem.position[3])
                    
                    # Desenhar retângulo verde
                    cv2.rectangle(debug_img, p1, p2, (0, 255, 0), 2)
                    
                    # Adicionar texto detectado ao lado do retângulo
                    if elem.text:
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        cv2.putText(debug_img, elem.text, (p1[0], p1[1]-5), 
                                font, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
                
                # Salvar a cada 50 ciclos para não encher o disco
                if hasattr(self, '_debug_counter'):
                    self._debug_counter += 1
                else:
                    self._debug_counter = 0
                    
                if self._debug_counter % 50 == 0:
                    cv2.imwrite("debug_detection.png", debug_img)
        
        except Exception as e:
            logger.error(f"Erro na detecção visual: {e}")
            logger.error("Detalhes do erro:", exc_info=True)
        
        return elements
    
    def extract_text_with_ocr(self, image, region, optimize_for_ui=False):
        """Extrai texto de uma região específica da imagem usando OCR otimizado para UI"""
        if self.reader is None:
            return ""
        
        try:
            x1, y1, x2, y2 = region
            width = x2 - x1
            height = y2 - y1
            
            # Relaxar os limites mínimos para elementos de UI
            if optimize_for_ui:
                min_width = 10  # Era 20, agora menor para capturar ícones e botões pequenos
                min_height = 8  # Era 10, agora menor
            else:
                min_width = 20
                min_height = 10
                
            # Verificar se a região é grande o suficiente
            if width < min_width or height < min_height:
                return ""
            
            # Verificar cache
            region_key = f"{x1}_{y1}_{x2}_{y2}"
            if region_key in self.ocr_cache:
                return self.ocr_cache[region_key]
            
            # Recortar a região da imagem
            if isinstance(image, Image.Image):
                roi = image.crop((x1, y1, x2, y2))
                roi_cv = cv2.cvtColor(np.array(roi), cv2.COLOR_RGB2BGR)
            else:
                roi_cv = image[y1:y2, x1:x2]
            
            # Verificar se a região é muito pequena para processamento padrão
            if width < 30 or height < 30:
                # Para regiões pequenas (botões, ícones), aplicar super-resolução
                scale_factor = max(2, 40/min(height, width))
                new_width = int(width * scale_factor)
                new_height = int(height * scale_factor)
                roi_cv = cv2.resize(roi_cv, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
            
            # Aplicar técnicas de processamento diferenciadas para botões/ícones vs texto normal
            if optimize_for_ui:
                # TÉCNICA 1: Versão de alto contraste
                gray = cv2.cvtColor(roi_cv, cv2.COLOR_BGR2GRAY)
                gray = cv2.convertScaleAbs(gray, alpha=2.0, beta=10)  # Contraste aumentado
                
                # TÉCNICA 2: Versão com equalização de histograma adaptativa (CLAHE)
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
                clahe_img = clahe.apply(cv2.cvtColor(roi_cv, cv2.COLOR_BGR2GRAY))
                
                # TÉCNICA 3: Versão com detecção de bordas realçada
                edges = cv2.Canny(cv2.cvtColor(roi_cv, cv2.COLOR_BGR2GRAY), 50, 150)
                kernel = np.ones((2,2), np.uint8)
                edges = cv2.dilate(edges, kernel, iterations=1)
                edges_inverted = 255 - edges  # Inverter para texto branco em fundo preto
                
                # Aplicar OCR a cada versão processada, recolhendo todos os resultados
                results_combined = []
                
                # Processar versão de alto contraste
                results1 = self.reader.readtext(gray, detail=1, paragraph=False, 
                                            min_size=3, 
                                            allowlist='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,()-_/@#$%&+=:;')
                results_combined.extend(results1)
                
                # Processar versão CLAHE
                results2 = self.reader.readtext(clahe_img, detail=1, paragraph=False, 
                                            min_size=3, 
                                            allowlist='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,()-_/@#$%&+=:;')
                results_combined.extend(results2)
                
                # Processar versão de bordas para textos mais difíceis
                if width < 50 or height < 50:  # Apenas para elementos pequenos
                    results3 = self.reader.readtext(edges_inverted, detail=1, paragraph=False, 
                                                min_size=2,  # Tamanho mínimo ainda menor
                                                allowlist='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,()-_/@#$%&+=:;')
                    results_combined.extend(results3)
                
                # Filtragem e deduplicação inteligente dos resultados
                if results_combined:
                    # Coletar todos os textos encontrados
                    all_texts = {}
                    for bbox, text, prob in results_combined:
                        clean_text = text.strip()
                        if len(clean_text) > 0:
                            # Usar um limiar mais baixo para botões e elementos de UI
                            if prob > 0.15:  # Limiar reduzido de 0.3 para 0.15 para elementos UI
                                # Se o mesmo texto foi encontrado mais de uma vez, escolher a maior confiança
                                if clean_text not in all_texts or prob > all_texts[clean_text]:
                                    all_texts[clean_text] = prob
                    
                    # Ordenar textos por probabilidade
                    sorted_texts = sorted(all_texts.items(), key=lambda x: x[1], reverse=True)
                    
                    # Para botões e elementos de interface, geralmente queremos apenas o texto mais confiável
                    if sorted_texts:
                        best_text = sorted_texts[0][0]
                        
                        # Adicionar ao cache
                        self.ocr_cache[region_key] = best_text
                        
                        # Limitar tamanho do cache
                        if len(self.ocr_cache) > self.cache_max_size:
                            self.ocr_cache.pop(next(iter(self.ocr_cache)))
                        
                        logger.info(f"OCR UI otimizado detectou: '{best_text}' (confiança: {sorted_texts[0][1]:.2f})")
                        return best_text
                
                return ""
                            
            else:
                # Processamento OCR padrão para regiões maiores (não botões/ícones)
                # [Código original aqui...]
                gray = cv2.cvtColor(roi_cv, cv2.COLOR_BGR2GRAY)
                gray = cv2.equalizeHist(gray)
                denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
                binary = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                            cv2.THRESH_BINARY, 11, 2)
                
                # Realizar OCR na imagem pré-processada
                results = self.reader.readtext(binary)
                
                # Extrair texto dos resultados
                text_parts = []
                for (bbox, text, prob) in results:
                    # Filtrar resultados com baixa confiança
                    if prob > 0.3:
                        text_parts.append(text)
                
                # Combinar resultados em uma única string
                full_text = " ".join(text_parts)
                
                # Adicionar ao cache se encontrou texto
                if full_text:
                    self.ocr_cache[region_key] = full_text
                    # Limitar tamanho do cache
                    if len(self.ocr_cache) > self.cache_max_size:
                        self.ocr_cache.pop(next(iter(self.ocr_cache)))
                
                return full_text
        
        except Exception as e:
            logger.error(f"Erro na extração de texto com OCR: {e}")
            return ""
        
    def batch_process_ocr(self, image, regions, max_batch=5, window_title=""):
        """Processa múltiplas regiões para OCR com melhorias de detecção de texto"""
        if self.reader is None or not regions:
            return [""] * len(regions)
        
        try:
            # Resultados para todas as regiões
            results = []
            
            # Contador de regiões processadas
            processed_regions = 0
            
            # Verificar se estamos em um editor de código
            is_code_editor = "code" in window_title.lower() or "vscode" in window_title.lower()
            
            # Processar cada região
            for i, (x1, y1, x2, y2) in enumerate(regions):
                # Limitar número de regiões processadas por ciclo
                if processed_regions >= max_batch:
                    results.append("")  # Adicionar string vazia para regiões não processadas
                    continue
                    
                # Verificar se a região é grande o suficiente
                width = x2 - x1
                height = y2 - y1
                if width < 20 or height < 10:  # Muito pequeno para ter texto legível
                    results.append("")
                    continue
                
                # Verificar cache antes de processar
                region_key = f"{x1}_{y1}_{x2}_{y2}"
                if region_key in self.ocr_cache:
                    results.append(self.ocr_cache[region_key])
                    continue
                
                # Extrair região da imagem
                if isinstance(image, Image.Image):
                    roi = image.crop((x1, y1, x2, y2))
                    roi_cv = cv2.cvtColor(np.array(roi), cv2.COLOR_RGB2BGR)
                else:
                    roi_cv = image[y1:y2, x1:x2]
                
                # Pré-processamento avançado da imagem
                try:
                    # Converter para escala de cinza
                    gray = cv2.cvtColor(roi_cv, cv2.COLOR_BGR2GRAY)
                    
                    # Redimensionar se for muito pequena
                    if height < 30 or width < 30:
                        scale = max(2, 30 / min(height, width))
                        new_width = int(width * scale)
                        new_height = int(height * scale)
                        gray = cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
                    
                    # Para código-fonte, aumentar contraste para melhorar detecção de texto
                    if is_code_editor:
                        # Aumentar contraste para texto de código
                        gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=10)
                    
                    # Aumentar o contraste
                    gray = cv2.equalizeHist(gray)
                    
                    # Remover ruído
                    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
                    
                    # Configurações diferentes para editores de código vs. outros aplicativos
                    if is_code_editor:
                        # Configuração otimizada para código-fonte e editores
                        # Limiarização adaptativa para melhorar o contraste do texto de código
                        binary = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                    cv2.THRESH_BINARY, 11, 2)
                        
                        # OCR com configurações específicas para código
                        ocr_result = self.reader.readtext(
                            binary, 
                            detail=1,
                            paragraph=False,
                            # Incluir caracteres comuns em código-fonte
                            allowlist='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,()[]{}<>:;=+-*/_"\''
                        )
                    else:
                        # Configuração padrão para aplicações gerais
                        # Limiarização adaptativa normal
                        binary = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                    cv2.THRESH_BINARY, 11, 2)
                        
                        # OCR padrão
                        ocr_result = self.reader.readtext(binary)
                    
                    # Processar e combinar resultados do OCR
                    if ocr_result:
                        # Inicializar array para marcar fragmentos ignorados (já combinados)
                        ignored = [False] * len(ocr_result)
                        
                        # Melhorar a combinação de fragmentos na horizontal
                        for i, (bbox1, text1, conf1) in enumerate(ocr_result):
                            if ignored[i]:
                                continue
                            for j, (bbox2, text2, conf2) in enumerate(ocr_result):
                                if i != j and not ignored[j]:
                                    # Extrair coordenadas para comparação
                                    if isinstance(bbox1[0], (list, tuple)):
                                        # Formato detalhado: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                                        y1_center = (bbox1[0][1] + bbox1[3][1]) / 2
                                        y2_center = (bbox2[0][1] + bbox2[3][1]) / 2
                                        x1_right = max(bbox1[1][0], bbox1[2][0])
                                        x2_left = min(bbox2[0][0], bbox2[3][0])
                                    else:
                                        # Formato simplificado: [x, y, width, height]
                                        y1_center = bbox1[1] + bbox1[3]/2
                                        y2_center = bbox2[1] + bbox2[3]/2
                                        x1_right = bbox1[0] + bbox1[2]
                                        x2_left = bbox2[0]
                                    
                                    # Se os bboxes estão próximos horizontalmente e na mesma altura
                                    if abs(y1_center - y2_center) < 10 and abs(x1_right - x2_left) < 30:
                                        # Combinar os textos
                                        combined_text = text1 + " " + text2
                                        combined_conf = min(conf1, conf2)
                                        
                                        # Atualizar o primeiro elemento com o texto combinado
                                        ocr_result[i] = (bbox1, combined_text, combined_conf)
                                        ignored[j] = True  # Marcar o segundo como ignorado
                        
                        # Filtrar e processar resultados
                        filtered_texts = []
                        for i, (bbox, text, conf) in enumerate(ocr_result):
                            if ignored[i]:
                                continue  # Pular textos já combinados
                            
                            # Filtrar textos muito curtos ou sem sentido
                            if len(text) <= 2 or (len(text) <= 3 and not any(c.isalnum() for c in text)):
                                continue  # Ignorar textos muito curtos ou sem caracteres alfanuméricos
                            
                            if conf > 0.3:  # Filtrar resultados de baixa confiança
                                filtered_texts.append(text)
                        
                        # Juntar todos os textos com um espaço
                        full_text = " ".join(filtered_texts).strip()
                        
                        # Remover duplicações de espaços
                        full_text = " ".join(full_text.split())
                    else:
                        full_text = ""
                    
                    # Adicionar ao cache se texto encontrado
                    if full_text:
                        self.ocr_cache[region_key] = full_text
                        # Limitar tamanho do cache
                        if len(self.ocr_cache) > self.cache_max_size:
                            # Remover item mais antigo
                            self.ocr_cache.pop(next(iter(self.ocr_cache)))
                        logger.info(f"OCR detectou: '{full_text}' na região {x1},{y1},{x2},{y2}")
                    
                    results.append(full_text)
                    processed_regions += 1
                    
                except Exception as e:
                    logger.error(f"Erro no OCR da região {x1},{y1},{x2},{y2}: {e}")
                    logger.debug("Detalhes do erro:", exc_info=True)
                    results.append("")
            
            # Completar com strings vazias para regiões não processadas
            while len(results) < len(regions):
                results.append("")
            
            return results
        
        except Exception as e:
            logger.error(f"Erro no processamento OCR: {e}")
            logger.debug("Detalhes do erro:", exc_info=True)
            return [""] * len(regions)

class SmartCache:
    """Cache inteligente para elementos de UI que considera o contexto da aplicação"""
    
    def __init__(self, max_size=200):
        self.cache = {}
        self.app_specific_cache = {}
        self.max_size = max_size
        self.hit_counts = {}
    
    def get(self, key, app_context=None):
        """Obtém um item do cache considerando o contexto da aplicação"""
        if app_context and app_context in self.app_specific_cache and key in self.app_specific_cache[app_context]:
            # Incrementar contador de hits para este item
            if key in self.hit_counts:
                self.hit_counts[key] += 1
            else:
                self.hit_counts[key] = 1
            return self.app_specific_cache[app_context][key]
        
        if key in self.cache:
            # Incrementar contador de hits
            if key in self.hit_counts:
                self.hit_counts[key] += 1
            else:
                self.hit_counts[key] = 1
            return self.cache[key]
        
        return None
    
    def set(self, key, value, app_context=None):
        """Adiciona um item ao cache, opcionalmente associado a um contexto específico"""
        # Adicionar ao cache geral
        self.cache[key] = value
        
        # Se tiver contexto de aplicação, adicionar também ao cache específico
        if app_context:
            if app_context not in self.app_specific_cache:
                self.app_specific_cache[app_context] = {}
            self.app_specific_cache[app_context][key] = value
        
        # Inicializar contador de hits
        if key not in self.hit_counts:
            self.hit_counts[key] = 0
        
        # Verificar se precisa fazer limpeza
        self._cleanup_if_needed()
    
    def _cleanup_if_needed(self):
        """Limpa o cache se exceder o tamanho máximo, removendo os itens menos acessados"""
        if len(self.cache) > self.max_size:
            # Remover 20% dos itens menos acessados
            items_to_remove = int(self.max_size * 0.2)
            
            # Ordenar por contagem de hits (menor primeiro)
            sorted_items = sorted(self.hit_counts.items(), key=lambda x: x[1])
            
            # Remover os itens menos acessados
            for i in range(min(items_to_remove, len(sorted_items))):
                key_to_remove = sorted_items[i][0]
                if key_to_remove in self.cache:
                    del self.cache[key_to_remove]
                    del self.hit_counts[key_to_remove]
                    
                    # Remover também dos caches específicos de aplicação
                    for app_context in self.app_specific_cache:
                        if key_to_remove in self.app_specific_cache[app_context]:
                            del self.app_specific_cache[app_context][key_to_remove]

class AIManager:
    """Gerencia os modelos de IA para reconhecimento e descrição de elementos"""
    
    def __init__(self, config):
        self.config = config
        
        # Configurações do modelo de IA
        # Adicionar opção de modelo leve para sistemas com pouca memória
        model_name = self.config.get('ai', 'model_name', fallback='microsoft/Phi-3-mini-4k-instruct')
        use_8bit = self.config.getboolean('ai', 'use_8bit', fallback=True)
        use_lite_model = self.config.getboolean('ai', 'use_lite_model', fallback=False)
        
        # Carregar modelo de classificação/descrição
        try:
            # Primeiro, verificar a memória disponível
            memory_available = self.check_available_memory()
            logger.info(f"Memória disponível: {memory_available} GB")
            
            if memory_available < 4 or use_lite_model:
                # Se menos de 4GB disponível, usar modelo extremamente leve
                model_name = "google/mobilebert-uncased"
                logger.info(f"Usando modelo leve devido a restrições de memória: {model_name}")
                
                # Carregar modelo leve
                self.tokenizer = AutoTokenizer.from_pretrained(model_name)
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    model_name,
                    num_labels=8,  # Para classificar os diferentes tipos de elementos UI
                    problem_type="single_label_classification"
                )
                logger.info("Modelo leve carregado com sucesso")
                self.is_lite_model = True
            else:
                # Tentar carregar o modelo padrão
                logger.info(f"Carregando modelo de IA: {model_name}")
                
                try:
                    if use_8bit and torch.cuda.is_available():
                        # Carregamento com quantização de 8 bits se GPU disponível
                        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
                        self.model = AutoModelForCausalLM.from_pretrained(
                            model_name,
                            device_map="auto",
                            load_in_8bit=True,
                            torch_dtype=torch.float16
                        )
                    else:
                        # Fallback para CPU
                        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
                        self.model = AutoModelForCausalLM.from_pretrained(
                            model_name, 
                            device_map="cpu"
                        )
                        logger.info("Modelo carregado em modo CPU (mais lento)")
                    
                    self.is_lite_model = False
                    logger.info("Modelo de IA carregado com sucesso")
                except Exception as e:
                    # Se falhar, tentar modelo mais leve
                    logger.warning(f"Erro ao carregar modelo principal: {e}")
                    logger.info("Tentando carregar modelo alternativo mais leve...")
                    
                    model_name = "distilbert-base-uncased"
                    self.tokenizer = AutoTokenizer.from_pretrained(model_name)
                    self.model = AutoModelForSequenceClassification.from_pretrained(
                        model_name,
                        num_labels=8,
                        problem_type="single_label_classification"
                    )
                    self.is_lite_model = True
                    logger.info("Modelo leve alternativo carregado com sucesso")
        
        except Exception as e:
            logger.error(f"Erro ao carregar modelo de IA: {e}")
            # Fallback: usar um modelo mais simples ou regras baseadas em heurística
            self.tokenizer = None
            self.model = None
            self.is_lite_model = False

    def check_available_memory(self):
        """Verifica a quantidade de memória disponível em GB"""
        try:
            import psutil
            memory = psutil.virtual_memory()
            available_gb = memory.available / (1024 ** 3)  # Converter para GB
            return available_gb
        except:
            # Se não conseguir verificar, assumir valor conservador
            return 2.0  # Assumir 2GB disponível
    
    def classify_element(self, element, image=None):
        """Classifica um elemento de UI com base em suas características visuais"""
        if not self.model or not self.tokenizer:
            # Fallback para classificação baseada em heurística
            return element
        
        try:
            # Se já temos um tipo de elemento com alta confiança, não precisamos do modelo
            if element.confidence > 0.8:
                return element
            
            # Preparar descrição visual para o modelo
            visual_desc = f"Posição: {element.position}, Texto: {element.text or 'Nenhum'}"
            
            # Preparar prompt para o modelo
            prompt = f"<|system|>\nVocê é um assistente para acessibilidade que identifica elementos de interface.\n<|end|>\n<|user|>\nClassifique este elemento de interface: {visual_desc}. Escolha entre: botão, campo de texto, caixa de seleção, botão de opção, menu suspenso, link, imagem, título, texto.<|end|>\n<|assistant|>"
            
            # Tokenizar e gerar resposta
            input_ids = self.tokenizer.encode(prompt, return_tensors="pt").to(self.model.device)
            
            with torch.no_grad():
                output = self.model.generate(
                    input_ids,
                    max_length=50,
                    do_sample=False,
                    temperature=0.1
                )
            
            # Decodificar resposta
            response = self.tokenizer.decode(output[0], skip_special_tokens=True)
            
            # Analisar resposta para determinar o tipo de elemento
            response = response.lower()
            for elem_type in UIElementType:
                if elem_type.value in response:
                    element.element_type = elem_type
                    element.confidence = 0.9
                    break
        
        except Exception as e:
            logger.error(f"Erro ao classificar elemento: {e}")
        
        return element
    
    def generate_description(self, element, context=None):
        """Gera uma descrição contextual para um elemento de UI"""
        if not self.model or not self.tokenizer:
            # Fallback para descrição simples
            return f"{element.element_type.value}: {element.text}" if element.text else element.element_type.value
        
        try:
            # Preparar contexto de forma mais concisa
            prompt = f"Descreva brevemente: Tipo={element.element_type.value}, Texto={element.text or 'Nenhum'}"
            
            # Usar max_new_tokens em vez de max_length para evitar o erro
            inputs = self.tokenizer(prompt, return_tensors="pt", padding=True)
            inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
            
            with torch.no_grad():
                output = self.model.generate(
                    **inputs,
                    max_new_tokens=50,  # Gerar no máximo 50 novos tokens
                    do_sample=True,
                    temperature=0.7
                )
            
            # Decodificar resposta
            description = self.tokenizer.decode(output[0], skip_special_tokens=True)
            
            # Remover o prompt da resposta
            description = description.replace(prompt, "").strip()
            
            # Simplificar se for muito longa
            if len(description) > 100:
                description = description[:97] + "..."
            
            return description
        
        except Exception as e:
            logger.error(f"Erro ao gerar descrição com IA: {e}")
            
            # Fallback para descrição básica
            if element.text:
                return f"{element.element_type.value}: {element.text}"
            return element.element_type.value

class SpeechManager:
    """Gerencia a conversão de texto para fala"""
    
    def __init__(self, config):
        self.config = config
        
        # Configurações de TTS
        voice_id = self.config.get('speech', 'voice_id', fallback=None)
        rate = self.config.getint('speech', 'rate', fallback=200)
        
        # Inicializar mecanismo de TTS
        try:
            logger.info("Inicializando mecanismo de fala")
            self.engine = pyttsx3.init()
            
            # Configurar voz
            voices = self.engine.getProperty('voices')
            voice_selected = False
            
            if voices:  # Verifica se há vozes disponíveis
                for voice in voices:
                    try:
                        # Tenta usar voz específica configurada
                        if voice_id and voice.id == voice_id:
                            self.engine.setProperty('voice', voice.id)
                            voice_selected = True
                            logger.info(f"Voz específica selecionada: {voice.id}")
                            break
                        
                        # Tenta encontrar uma voz em português
                        elif not voice_id:
                            # Verifica se o atributo languages existe e tem elementos
                            if hasattr(voice, 'languages') and len(voice.languages) > 0:
                                # Converte para string para garantir que podemos usar .lower()
                                lang_str = str(voice.languages[0]).lower()
                                if 'portuguese' in lang_str or 'brasil' in lang_str or 'brazil' in lang_str:
                                    self.engine.setProperty('voice', voice.id)
                                    voice_selected = True
                                    logger.info(f"Voz em português selecionada: {voice.id}")
                                    break
                    
                    except Exception as e:
                        logger.debug(f"Erro ao verificar voz {voice.id}: {e}")
                        continue
                
                # Se não encontrou nenhuma voz específica, usa a primeira disponível
                if not voice_selected and voices:
                    self.engine.setProperty('voice', voices[0].id)
                    logger.info(f"Usando voz padrão: {voices[0].id}")
            else:
                logger.warning("Nenhuma voz encontrada no sistema")
            
            # Configurar taxa de fala
            self.engine.setProperty('rate', rate)
            
            logger.info("Mecanismo de fala inicializado com sucesso")
        
        except Exception as e:
            logger.error(f"Erro ao inicializar mecanismo de fala: {e}")
            self.engine = None
        
    def speak(self, text, interrupt=True):
        """Converte texto para fala"""
        if not self.engine:
            logger.error("Mecanismo de fala não disponível")
            return
        
        try:
            logger.info(f"Falando: '{text}'")
            
            # Tentar interromper fala anterior, mas ignorar erros
            if interrupt:
                try:
                    self.engine.stop()
                except:
                    pass
            
            # Criar novo motor a cada 20 chamadas para evitar problemas
            if hasattr(self, '_speak_counter'):
                self._speak_counter += 1
            else:
                self._speak_counter = 0
                
            # Reiniciar o motor periodicamente para evitar erros de loop
            if self._speak_counter % 20 == 0:
                try:
                    self.engine = pyttsx3.init()
                    voices = self.engine.getProperty('voices')
                    # Procurar voz em português
                    for voice in voices:
                        if 'pt' in voice.id.lower() or 'brazil' in voice.id.lower():
                            self.engine.setProperty('voice', voice.id)
                            break
                    rate = self.config.getint('speech', 'rate', fallback=200)
                    self.engine.setProperty('rate', rate)
                    logger.info("Motor de fala reiniciado preventivamente")
                except Exception as e:
                    logger.error(f"Erro ao reiniciar motor: {e}")
            
            # Falar o texto
            self.engine.say(text)
            
            # Executar em bloco try/except para capturar erros
            try:
                self.engine.runAndWait()
                logger.info("Fala concluída")
            except RuntimeError as re:
                if "run loop already started" in str(re):
                    logger.info("Ignorando erro de loop já iniciado")
                    # Criar novo motor
                    self.engine = pyttsx3.init()
                    rate = self.config.getint('speech', 'rate', fallback=200)
                    self.engine.setProperty('rate', rate)
                else:
                    raise
        
        except Exception as e:
            logger.error(f"Erro ao falar: {e}")
            
            # Tentar recuperar o mecanismo
            try:
                self.engine = pyttsx3.init()
                voices = self.engine.getProperty('voices')
                if voices:
                    self.engine.setProperty('voice', voices[0].id)
                rate = self.config.getint('speech', 'rate', fallback=200)
                self.engine.setProperty('rate', rate)
                logger.info("Mecanismo de fala reiniciado após erro")
            except Exception as e2:
                logger.error(f"Não foi possível reiniciar o mecanismo: {e2}")

class ScreenReader:
    """Classe principal que coordena todas as funcionalidades do leitor de tela"""
    
    def __init__(self):
        # Carregar configurações
        self.config = self.load_config()
        
        # Inicializar componentes
        self.accessibility_manager = AccessibilityManager()
        self.html_accessibility_manager = HTMLAccessibilityManager(self.accessibility_manager)  
        self.vision_manager = VisionManager(self.config)
        self.ai_manager = AIManager(self.config)
        self.speech_manager = SpeechManager(self.config)
        
        # Fila de comandos para processamento assíncrono
        self.command_queue = queue.Queue()
        
        # Estado do leitor
        self.running = False
        self.paused = False
        self.focused_element = None
        self.current_elements = []
        self.current_index = -1
        
        # Definir atalhos de teclado
        self.setup_keyboard_shortcuts()
        
        # Adicionar monitor de teclado de baixo nível
        self.setup_keyboard_monitoring()
        
        logger.info("Leitor de tela inicializado com sucesso")

    def load_config(self):
        """Carrega ou cria arquivo de configuração com melhorias para detecção de texto em botões"""
        config = configparser.ConfigParser()
        
        # Configurações padrão
        config['general'] = {
            'refresh_rate': '0.5',  # Taxa de atualização em segundos
            'use_accessibility_api': 'true',
            'use_vision': 'true',
            'debug_mode': 'false',
            'auto_adjust_performance': 'true'  # NOVO: ajustar configurações baseado no hardware
        }
        
        config['ai'] = {
            'model_name': 'microsoft/Phi-3-mini-4k-instruct',
            'use_8bit': 'true',
            'context_window': '10',
            'use_lite_model': 'false',  # NOVO: opção para usar modelo mais leve
            'enabled': 'true'           # NOVO: habilitar/desabilitar completamente
        }
        
        config['vision'] = {
            'model_path': 'models',
            'confidence_threshold': '0.5',  # ALTERADO: limiar mais baixo para melhor detecção
            'use_ocr': 'true',
            'ocr_confidence': '0.15',      # ALTERADO: limiar muito mais baixo para textos em botões
            'multi_processing': 'true',    # NOVO: processar imagem com múltiplas técnicas
            'enhance_small_elements': 'true'  # NOVO: melhoria para botões pequenos
        }
        
        config['speech'] = {
            'voice_id': '',
            'rate': '200',
            'volume': '100',             # NOVO: controle de volume
            'announcer_mode': 'false'    # NOVO: modo locutor (mais verboso)
        }

        # Seção para acessibilidade HTML (expandida)
        config['accessibility'] = {
            'use_html_accessibility': 'true',
            'html_priority': 'true',
            'max_depth': '5',
            'describe_images': 'true',       # NOVO: descrever imagens detectadas
            'high_contrast': 'false',        # NOVO: modo alto contraste 
            'simplify_descriptions': 'false', # NOVO: simplificar descrições
            'verbosity_level': '2',          # NOVO: nível de detalhes (1-3)
            'auto_highlight': 'true',        # NOVO: destacar elemento em foco
            'focus_border_color': 'yellow'   # NOVO: cor da borda para elementos em foco
        }
        
        # NOVA seção para feedback de áudio
        config['audio'] = {
            'use_enhanced_audio': 'true',    # Usar feedback sonoro além da fala
            'sounds_folder': 'sounds',       # Pasta com sons personalizados
            'voice_feedback': 'true',        # Feedback por voz
            'earcon_volume': '80'            # Volume para efeitos sonoros não-verbais
        }
        
        # NOVA seção para detecção social e contexto
        config['social'] = {
            'detect_social_buttons': 'true',  # Detectar botões específicos de redes sociais
            'facebook_support': 'true',       # Suporte otimizado para Facebook
            'instagram_support': 'true',      # Suporte otimizado para Instagram
            'twitter_support': 'true',        # Suporte otimizado para Twitter
            'linkedin_support': 'true'        # Suporte otimizado para LinkedIn
        }
        
        # NOVA seção para recuperação de erros
        config['recovery'] = {
            'auto_recovery': 'true',          # Recuperação automática de erros
            'max_ocr_errors': '3',            # Erros máximos antes de reiniciar OCR
            'max_speech_errors': '5',         # Erros máximos antes de reiniciar fala
            'health_check_interval': '300'    # Intervalo para verificar saúde do sistema (segundos)
        }
        
        # Tentar carregar configurações do arquivo
        config_file = 'ai_screen_reader.ini'
        if os.path.exists(config_file):
            try:
                config.read(config_file)
                logger.info("Configurações carregadas do arquivo")
            except Exception as e:
                logger.error(f"Erro ao carregar configurações: {e}")
        else:
            # Salvar configurações padrão
            try:
                with open(config_file, 'w') as f:
                    config.write(f)
                logger.info("Arquivo de configuração padrão criado com melhorias para botões")
            except Exception as e:
                logger.error(f"Erro ao criar arquivo de configuração: {e}")
        
        return config
    
    def setup_keyboard_shortcuts(self):
        """Configura atalhos de teclado para o leitor de tela"""
        try:
            # Tecla de pausa/retomar: Alt+Ctrl+P
            keyboard.add_hotkey('alt+ctrl+p', self.toggle_pause)
            
            # Navegar para o próximo elemento: Alt+Ctrl+Right
            keyboard.add_hotkey('alt+ctrl+right', lambda: self.command_queue.put(('next', None)))
            
            # Navegar para o elemento anterior: Alt+Ctrl+Left
            keyboard.add_hotkey('alt+ctrl+left', lambda: self.command_queue.put(('prev', None)))
            
            # Ler elemento atual: Alt+Ctrl+Space
            keyboard.add_hotkey('alt+ctrl+space', lambda: self.command_queue.put(('read_current', None)))
            
            # Ler tudo: Alt+Ctrl+A
            keyboard.add_hotkey('alt+ctrl+a', lambda: self.command_queue.put(('read_all', None)))
            
            # Capturar elemento sob o cursor: Alt+Ctrl+C
            keyboard.add_hotkey('alt+ctrl+c', lambda: self.command_queue.put(('capture_at_cursor', None)))
            
            # NOVO: Monitorar pressionamento de TAB
            keyboard.on_press_key('tab', lambda _: self.command_queue.put(('tab_pressed', None)))
            
            # Sair: Alt+Ctrl+Q
            keyboard.add_hotkey('alt+ctrl+q', self.stop)
            
            logger.info("Atalhos de teclado configurados com sucesso")
        except Exception as e:
            logger.error(f"Erro ao configurar atalhos de teclado: {e}")

    def generate_contextual_description(self, element, parent_context=None):
        """Gera descrição contextual rica para elementos, considerando o contexto da aplicação e página"""
        try:
            # Obter informações da aplicação atual
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            window_title = win32gui.GetWindowText(hwnd)
            
            # Identificar o tipo de aplicação
            is_browser = any(browser in window_title.lower() for browser in ["chrome", "firefox", "edge", "safari", "opera"])
            is_social_media = any(site in window_title.lower() for site in ["facebook", "instagram", "twitter", "linkedin", "youtube"])
            is_document = any(app in window_title.lower() for app in ["word", "excel", "powerpoint", "pdf", "doc", "documento"])
            is_code_editor = any(editor in window_title.lower() for editor in ["code", "visual studio", "intellij", "pycharm", "sublime"])
            
            # Obter tipo e texto do elemento
            element_type = element.element_type.value
            element_text = element.text.strip() if element.text else ""
            
            # 1. Descrição básica baseada no tipo de elemento
            if element_text:
                basic_desc = f"{element_type} com texto '{element_text}'"
            else:
                width = element.position[2] - element.position[0]
                height = element.position[3] - element.position[1]
                basic_desc = f"{element_type} de {width} por {height} pixels"
            
            # 2. Adicionar contexto de posição
            position_context = self._get_position_description(element.position)
            
            # 3. Adicionar contexto específico da aplicação
            app_context = ""
            
            if is_browser:
                if is_social_media:
                    # Contexto para redes sociais
                    if "curtir" in element_text.lower() or "like" in element_text.lower():
                        app_context = " - botão para curtir publicação"
                    elif "comentar" in element_text.lower() or "comment" in element_text.lower():
                        app_context = " - botão para comentar publicação"
                    elif "compartilhar" in element_text.lower() or "share" in element_text.lower():
                        app_context = " - botão para compartilhar publicação"
                    elif "seguir" in element_text.lower() or "follow" in element_text.lower():
                        app_context = " - botão para seguir usuário"
                    elif "mensagem" in element_text.lower() or "message" in element_text.lower():
                        app_context = " - botão para enviar mensagem"
                elif "gmail" in window_title.lower():
                    # Contexto para Gmail
                    if "enviar" in element_text.lower() or "send" in element_text.lower():
                        app_context = " - botão para enviar email"
                    elif "anexar" in element_text.lower() or "attach" in element_text.lower():
                        app_context = " - botão para anexar arquivo"
                    elif "responder" in element_text.lower() or "reply" in element_text.lower():
                        app_context = " - botão para responder email"
            elif is_document:
                # Contexto para editores de documento
                if element_type == "botão":
                    if any(action in element_text.lower() for action in ["salvar", "save"]):
                        app_context = " - botão para salvar documento"
                    elif any(action in element_text.lower() for action in ["imprimir", "print"]):
                        app_context = " - botão para imprimir documento"
            elif is_code_editor:
                # Contexto para editores de código
                if element_type == "botão":
                    if any(action in element_text.lower() for action in ["executar", "run", "debug"]):
                        app_context = " - botão para executar código"
                    elif any(action in element_text.lower() for action in ["commit", "push", "git"]):
                        app_context = " - botão para operação git"
            
            # 4. Integrar todas as partes da descrição
            full_description = f"{basic_desc}{position_context}"
            if app_context:
                full_description += app_context
                
            # 5. Adicionar estado de foco se aplicável
            if hasattr(element, 'is_focused') and element.is_focused:
                full_description += " (em foco)"
            
            return full_description
            
        except Exception as e:
            logger.error(f"Erro ao gerar descrição contextual: {e}")
            # Fallback para descrição simples
            if element.text:
                return f"{element.element_type.value}: {element.text}"
            return element.element_type.value
        
    def _get_position_description(self, position):
        """Gera descrição de posição mais natural"""
        x1, y1, x2, y2 = position
        width = x2 - x1
        height = y2 - y1
        
        # Obter posição relativa na tela
        screen_width, screen_height = 1920, 1080  # Valores padrão
        try:
            import pyautogui
            screen_width, screen_height = pyautogui.size()
        except:
            pass
        
        x_center = (x1 + x2) / 2
        y_center = (y1 + y2) / 2
        
        # Posição horizontal
        if x_center < screen_width * 0.25:
            h_position = " no lado esquerdo"
        elif x_center < screen_width * 0.5:
            h_position = " na parte central-esquerda"
        elif x_center < screen_width * 0.75:
            h_position = " na parte central-direita"
        else:
            h_position = " no lado direito"
        
        # Posição vertical
        if y_center < screen_height * 0.25:
            v_position = " superior"
        elif y_center < screen_height * 0.75:
            v_position = " inferior"
        else:
            v_position = ""
        
        return h_position + v_position

    def setup_keyboard_monitoring(self):
        """Configura um monitor de teclado de baixo nível para detectar TAB"""
        try:
            import ctypes
            import win32con
            
            # Definir callback que será chamado quando uma tecla for pressionada
            def keyboard_callback(nCode, wParam, lParam):
                # Estrutura para informações de tecla
                class KBDLLHOOKSTRUCT(ctypes.Structure):
                    _fields_ = [
                        ("vkCode", ctypes.c_int),
                        ("scanCode", ctypes.c_int),
                        ("flags", ctypes.c_int),
                        ("time", ctypes.c_int),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_int))
                    ]
                
                # Verificar se é um pressionamento de tecla (não um release)
                if wParam == win32con.WM_KEYDOWN:
                    kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    
                    # Verificar se é a tecla TAB (código virtual 9)
                    if kb.vkCode == 9:
                        # Adicionar comando à fila
                        self.command_queue.put(('tab_pressed', None))
                
                # Passar para o próximo hook
                return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)
            
            # Converter a função de callback para um tipo compatível
            callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
            self.keyboard_hook_proc = callback_type(keyboard_callback)
            
            # Instalar o hook de teclado
            self.keyboard_hook = ctypes.windll.user32.SetWindowsHookExA(
                win32con.WH_KEYBOARD_LL,
                self.keyboard_hook_proc,
                ctypes.windll.kernel32.GetModuleHandleW(None),
                0
            )
            
            logger.info("Monitor de teclado de baixo nível instalado com sucesso")
        except Exception as e:
            logger.error(f"Erro ao configurar monitor de teclado: {e}")

    def toggle_pause(self):
        """Pausa ou retoma o leitor de tela"""
        self.paused = not self.paused
        if self.paused:
            self.speech_manager.speak("Leitor de tela pausado")
        else:
            self.speech_manager.speak("Leitor de tela ativado")
    
    def capture_screen_region(self, region=None):
        """Captura uma região específica da tela"""
        try:
            if region:
                x1, y1, x2, y2 = region
                screenshot = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            else:
                screenshot = ImageGrab.grab()
            
            return screenshot
        except Exception as e:
            logger.error(f"Erro ao capturar tela: {e}")
            return None
    
    def process_screen(self):
        """Processa a tela para encontrar e descrever elementos (modificado para priorizar HTML)"""
        if self.paused:
            return
        
        try:
            # Log a cada 20 ciclos aproximadamente
            if hasattr(self, '_cycle_counter'):
                self._cycle_counter += 1
            else:
                self._cycle_counter = 0
                
            is_log_cycle = self._cycle_counter % 20 == 0
            
            if is_log_cycle:
                logger.info("Processando tela...")
            
            # Registrar posição atual do mouse
            import pyautogui
            current_x, current_y = pyautogui.position()
            
            # Armazenar posição anterior (se não existir, criar)
            if not hasattr(self, 'previous_mouse_position'):
                self.previous_mouse_position = (current_x, current_y)
            
            # Verificar se o mouse se moveu significativamente (mais de 5 pixels)
            mouse_distance = ((current_x - self.previous_mouse_position[0])**2 + 
                            (current_y - self.previous_mouse_position[1])**2)**0.5
            
            # Apenas processar se o mouse moveu significativamente ou é a primeira execução
            if mouse_distance > 5 or not hasattr(self, 'processed_once'):
                self.processed_once = True
                self.previous_mouse_position = (current_x, current_y)
                
                logger.info(f"Mouse moveu para: ({current_x}, {current_y}), processando região...")
                
                # Capturar região ao redor do cursor
                region = (max(0, current_x - 150), max(0, current_y - 150), 
                        current_x + 150, current_y + 150)
                
                # NOVA LÓGICA: Verificar se estamos em um navegador ou app com suporte a acessibilidade
                browser = self.html_accessibility_manager.detect_browser()
                
                if browser:
                    logger.info(f"Processando elemento em navegador: {browser}")
                    
                    # PRIORIDADE 1: Tentar obter elementos via acessibilidade HTML
                    html_elements = self.html_accessibility_manager.get_html_accessibility_tree(region)
                    
                    if html_elements:
                        logger.info(f"Elementos HTML detectados: {len(html_elements)}")
                        
                        # Encontrar elemento sob o cursor
                        cursor_element = None
                        min_distance = float('inf')
                        
                        for elem in html_elements:
                            # Verificar se o cursor está dentro do elemento
                            if (elem.position[0] <= current_x <= elem.position[2] and
                                elem.position[1] <= current_y <= elem.position[3]):
                                cursor_element = elem
                                break
                            
                            # Se não está diretamente sobre um elemento, encontrar o mais próximo
                            cx = (elem.position[0] + elem.position[2]) / 2
                            cy = (elem.position[1] + elem.position[3]) / 2
                            dist = ((cx - current_x)**2 + (cy - current_y)**2)**0.5
                            
                            if dist < min_distance:
                                min_distance = dist
                                cursor_element = elem
                        
                        if cursor_element:
                            # Verificar se este elemento é diferente do último processado
                            is_new_element = self._is_new_element(cursor_element)
                            
                            if is_new_element:
                                # Gerar descrição para o elemento
                                description = self.generate_html_description(cursor_element)
                                cursor_element.description = description
                                
                                # Atualizar elemento em foco
                                self.focused_element = cursor_element
                                
                                # Falar a descrição
                                logger.info(f"Falando descrição HTML: {description}")
                                self.speech_manager.speak(description)
                                
                                # Como encontramos um elemento HTML, podemos retornar
                                return
                
                # PRIORIDADE 2: Se não encontrou elementos HTML ou não estamos em navegador, usar OCR
                screenshot = self.capture_screen_region(region)
                if screenshot:
                    elements = self.vision_manager.detect_elements(screenshot)
                    
                    logger.info(f"Elementos detectados visualmente: {len(elements)}")
                    
                    if elements:
                        # Encontrar elemento sob o cursor ou mais próximo
                        cursor_element = None
                        min_distance = float('inf')
                        
                        for elem in elements:
                            # Ajustar posições para coordenadas globais
                            global_pos = (
                                elem.position[0] + region[0],
                                elem.position[1] + region[1],
                                elem.position[2] + region[0],
                                elem.position[3] + region[1]
                            )
                            
                            # Verificar se o cursor está dentro do elemento
                            if (global_pos[0] <= current_x <= global_pos[2] and
                                global_pos[1] <= current_y <= global_pos[3]):
                                cursor_element = UIElement(
                                    elem.element_type,
                                    global_pos,
                                    elem.text,
                                    elem.confidence
                                )
                                break
                            
                            # Se não está diretamente sobre um elemento, encontrar o mais próximo
                            cx = (global_pos[0] + global_pos[2]) / 2
                            cy = (global_pos[1] + global_pos[3]) / 2
                            dist = ((cx - current_x)**2 + (cy - current_y)**2)**0.5
                            
                            if dist < min_distance:
                                min_distance = dist
                                cursor_element = UIElement(
                                    elem.element_type,
                                    global_pos,
                                    elem.text,
                                    elem.confidence
                                )
                        
                        if cursor_element:
                            # Verificar se este elemento é diferente do último processado
                            is_new_element = True
                            
                            if self.focused_element:
                                # Verificar sobreposição significativa com elemento anterior
                                old_area = (self.focused_element.position[2] - self.focused_element.position[0]) * \
                                        (self.focused_element.position[3] - self.focused_element.position[1])
                                new_area = (cursor_element.position[2] - cursor_element.position[0]) * \
                                        (cursor_element.position[3] - cursor_element.position[1])
                                
                                # Calcular interseção
                                x_overlap = max(0, min(self.focused_element.position[2], cursor_element.position[2]) - 
                                            max(self.focused_element.position[0], cursor_element.position[0]))
                                y_overlap = max(0, min(self.focused_element.position[3], cursor_element.position[3]) - 
                                            max(self.focused_element.position[1], cursor_element.position[1]))
                                
                                overlap_area = x_overlap * y_overlap
                                smaller_area = min(old_area, new_area)
                                
                                # Se a sobreposição é mais de 70% da área do menor elemento, considerar como o mesmo
                                if smaller_area > 0 and overlap_area / smaller_area > 0.7:
                                    # Se o texto for o mesmo, considerar como o mesmo elemento
                                    if self.focused_element.text == cursor_element.text:
                                        is_new_element = False
                                        logger.info("Elemento sobreposto ao anterior, considerando igual")
                            
                            if is_new_element:
                                # Gerar descrição para o elemento
                                description = self.generate_simple_description(cursor_element)
                                cursor_element.description = description
                                
                                # Atualizar elemento em foco
                                self.focused_element = cursor_element
                                
                                # Falar a descrição
                                logger.info(f"Falando nova descrição: {description}")
                                self.speech_manager.speak(description)
            
        except Exception as e:
            logger.error(f"Erro ao processar tela: {e}")
            logger.error("Detalhes do erro:", exc_info=True)

    def _is_new_element(self, new_element):
        """Verifica se um elemento é diferente do elemento atual em foco"""
        if not self.focused_element:
            return True
            
        # Verificar se os IDs de acessibilidade são diferentes
        if hasattr(new_element, 'accessibility_id') and hasattr(self.focused_element, 'accessibility_id'):
            if new_element.accessibility_id != self.focused_element.accessibility_id:
                return True
                
        # Verificar sobreposição significativa
        old_area = (self.focused_element.position[2] - self.focused_element.position[0]) * \
                (self.focused_element.position[3] - self.focused_element.position[1])
        new_area = (new_element.position[2] - new_element.position[0]) * \
                (new_element.position[3] - new_element.position[1])
        
        # Calcular interseção
        x_overlap = max(0, min(self.focused_element.position[2], new_element.position[2]) - 
                    max(self.focused_element.position[0], new_element.position[0]))
        y_overlap = max(0, min(self.focused_element.position[3], new_element.position[3]) - 
                    max(self.focused_element.position[1], new_element.position[1]))
        
        overlap_area = x_overlap * y_overlap
        smaller_area = min(old_area, new_area)
        
        # Se a sobreposição é mais de 70% da área do menor elemento, considerar como o mesmo
        if smaller_area > 0 and overlap_area / smaller_area > 0.7:
            # Se o texto for o mesmo, considerar como o mesmo elemento
            if self.focused_element.text == new_element.text:
                return False
                
        return True

    def generate_html_description(self, element):
        """Gera uma descrição para elementos HTML que usa informações de acessibilidade"""
        # Usar informações de acessibilidade para gerar uma descrição mais rica
        element_type = element.element_type.value
        
        # Se o elemento já tem uma descrição de acessibilidade, usá-la
        if hasattr(element, 'description') and element.description:
            return f"{element_type}: {element.description}"
            
        # Se tem texto, usar o texto
        if element.text:
            # Limpar texto
            clean_text = element.text.strip()
            
            # Truncar textos longos
            if len(clean_text) > 50:
                clean_text = clean_text[:47] + "..."
                
            description = f"{element_type} com texto '{clean_text}'"
            
            # Adicionar posição para elementos importantes
            if element_type in ["botão", "link", "caixa de seleção"]:
                x_center = (element.position[0] + element.position[2]) // 2
                y_center = (element.position[1] + element.position[3]) // 2
                
                # Adicionar posição relativa
                if x_center < 400:
                    description += " no lado esquerdo"
                elif x_center > 800:
                    description += " no lado direito"
                    
                if y_center < 300:
                    description += " superior"
                elif y_center > 600:
                    description += " inferior"
                    
            return description
        
        # Se não há texto, usar descrição baseada no tipo e tamanho
        width = element.position[2] - element.position[0]
        height = element.position[3] - element.position[1]
        
        description = f"{element_type} de {width} por {height} pixels"
        
        # Adicionar posição relativa
        x_center = (element.position[0] + element.position[2]) // 2
        y_center = (element.position[1] + element.position[3]) // 2
        
        if x_center < 400:
            description += " no lado esquerdo"
        elif x_center > 800:
            description += " no lado direito"
        else:
            description += " no centro"
            
        if y_center < 300:
            description += " superior"
        elif y_center > 600:
            description += " inferior"
            
        return description

    def detect_visual_changes_after_tab(self):
        """Detecta mudanças visuais precisas após Tab ser pressionado"""
        try:
            # Verificar se estamos em um navegador
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            
            is_browser = any(browser in title.lower() for browser in ["chrome", "firefox", "edge", "safari", "opera"])
            
            if not is_browser:
                return False
            
            # Capturar screenshot da janela ativa
            screenshot = self.capture_active_window()
            
            if not screenshot:
                return False
                
            # Converter para array numpy
            img_array = np.array(screenshot)
            
            # **** NOVA ABORDAGEM: Detectar mudanças de cor/contraste típicas de foco ****
            
            # 1. Detectar áreas de alto contraste (elementos em foco geralmente têm bordas ou highlights)
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edges = cv2.Canny(blurred, 30, 100)  # Valores mais sensíveis
            
            # 2. Aplicar transformações para destacar regiões em foco 
            kernel = np.ones((3, 3), np.uint8)
            dilated = cv2.dilate(edges, kernel, iterations=2)
            
            # 3. Encontrar contornos de regiões ativas
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # 4. Filtrar contornos muito pequenos (ruído) e muito grandes (toda a página)
            height, width = gray.shape
            min_area = 100  # Menor que isso é provavelmente ruído
            max_area = width * height * 0.3  # Maior que 30% da tela é muito grande
            
            filtered_contours = [c for c in contours if min_area < cv2.contourArea(c) < max_area]
            
            if not filtered_contours:
                return False
                
            # 5. Identificar o contorno mais provável de ser o elemento em foco
            # Elementos em foco geralmente são mais retangulares e têm áreas medianas
            focus_candidates = []
            
            for contour in filtered_contours:
                x, y, w, h = cv2.boundingRect(contour)
                area = w * h
                aspect_ratio = float(w) / h if h > 0 else 0
                
                # Calcular um score de "probabilidade de foco" (heurística)
                focus_score = 0
                
                # Elementos de UI geralmente são mais largos que altos
                if 1.5 < aspect_ratio < 8:
                    focus_score += 2
                    
                # Elementos de UI típicos não são nem muito pequenos nem muito grandes
                if area > 1000 and area < 30000:
                    focus_score += 3
                    
                # Elementos em foco geralmente estão em posições "clicáveis"
                if y > height * 0.1 and y < height * 0.9:  # Não muito no topo ou rodapé
                    focus_score += 1
                    
                focus_candidates.append((x, y, w, h, focus_score))
                
            # Ordenar por score e selecionar o melhor candidato
            if focus_candidates:
                focus_candidates.sort(key=lambda c: c[4], reverse=True)
                x, y, w, h, _ = focus_candidates[0]
                
                # 6. Extrair texto da região de foco usando OCR
                # Expandir a região ligeiramente para capturar texto completo
                padding = 5
                x1 = max(0, x - padding)
                y1 = max(0, y - padding) 
                x2 = min(width, x + w + padding)
                y2 = min(height, y + h + padding)
                
                focus_region = img_array[y1:y2, x1:x2]
                
                # Converter para PIL para OCR
                pil_img = Image.fromarray(focus_region)
                
                # Extrair texto com OCR mais sensível para elementos de UI
                text = self.vision_manager.extract_text_with_ocr(
                    pil_img, 
                    (0, 0, x2-x1, y2-y1), 
                    optimize_for_ui=True  # Novo parâmetro para otimizar OCR para elementos de UI
                )
                
                # Determinar tipo com base na forma e posição
                element_type = UIElementType.BUTTON  # Padrão para elementos clicáveis
                
                # Refinar baseado no texto e proporções
                if text:
                    text_lower = text.lower()
                    if any(term in text_lower for term in ["pesquisa", "busca", "search", "procurar"]):
                        element_type = UIElementType.TEXT_FIELD
                    elif any(term in text_lower for term in [".com", "http", "www", "link"]):
                        element_type = UIElementType.LINK
                    elif any(term in text_lower for term in ["comentar", "enviar", "postar", "curtir", "publicar"]):
                        element_type = UIElementType.BUTTON
                elif w > h * 3:  # Muito mais largo que alto
                    element_type = UIElementType.TEXT_FIELD
                elif w < h:  # Mais alto que largo
                    element_type = UIElementType.UNKNOWN
                    
                # Criar elemento UI com posição global na tela
                global_pos = (x1, y1, x2, y2)
                
                focus_element = UIElement(
                    element_type,
                    global_pos,
                    text=text,
                    confidence=0.9,
                    accessibility_id="tab_focused_visual"
                )
                
                # Gerar descrição
                description = self.generate_simple_description(focus_element)
                focus_element.description = description
                
                # Atualizar elemento em foco
                self.focused_element = focus_element
                
                # Falar a descrição
                logger.info(f"Elemento destacado detectado após TAB: {description}")
                self.speech_manager.speak(description)
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Erro na detecção visual após TAB: {e}")
            return False
    
    def is_accessibility_compatible_app(self):
        """Verifica se o aplicativo atual suporta APIs de acessibilidade avançadas"""
        try:
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            
            # Lista de aplicações conhecidas com bom suporte a acessibilidade
            compatible_apps = [
                # Navegadores (já tratados pelo HTML Accessibility Manager)
                'chrome', 'firefox', 'edge', 'opera', 'safari',
                # Aplicações Office
                'word', 'excel', 'powerpoint', 'outlook',
                # Editores de código
                'vscode', 'visual studio', 'intellij', 'pycharm',
                # Outras aplicações
                'adobe', 'reader'
            ]
            
            for app in compatible_apps:
                if app.lower() in title.lower():
                    return True
                    
            return False
        except:
            return False

    def process_commands(self):
        """Processa comandos da fila de comandos"""
        try:
            if not self.command_queue.empty():
                command, args = self.command_queue.get(block=False)
                
                if command == 'next':
                    self.navigate_next()
                elif command == 'prev':
                    self.navigate_prev()
                elif command == 'read_current':
                    self.read_current()
                elif command == 'read_all':
                    self.read_all()
                elif command == 'capture_at_cursor':
                    self.capture_at_cursor()
                elif command == 'tab_pressed':  # Nova condição para TAB
                    self.handle_tab_press()
                    
        except queue.Empty:
            pass
        except Exception as e:
            logger.error(f"Erro ao processar comandos: {e}")
            logger.error("Detalhes:", exc_info=True)
    
    def navigate_next(self):
        """Navega para o próximo elemento"""
        if not self.current_elements:
            self.speech_manager.speak("Nenhum elemento disponível")
            return
        
        self.current_index = (self.current_index + 1) % len(self.current_elements)
        self.focused_element = self.current_elements[self.current_index]
        self.read_current()
    
    def navigate_prev(self):
        """Navega para o elemento anterior"""
        if not self.current_elements:
            self.speech_manager.speak("Nenhum elemento disponível")
            return
        
        self.current_index = (self.current_index - 1) % len(self.current_elements)
        self.focused_element = self.current_elements[self.current_index]
        self.read_current()
    
    def read_current(self):
        """Lê o elemento atual"""
        if self.focused_element:
            if not self.focused_element.description:
                self.focused_element.description = self.ai_manager.generate_description(self.focused_element)
            
            self.speech_manager.speak(self.focused_element.description)
        else:
            self.speech_manager.speak("Nenhum elemento em foco")
    
    def read_all(self):
        """Lê todos os elementos na tela"""
        if not self.current_elements:
            self.speech_manager.speak("Nenhum elemento disponível")
            return
        
        descriptions = []
        for elem in self.current_elements:
            if not elem.description:
                elem.description = self.ai_manager.generate_description(elem)
            
            descriptions.append(elem.description)
        
        self.speech_manager.speak(". ".join(descriptions))
    
    def capture_at_cursor(self):
        """Captura o elemento sob o cursor"""
        import pyautogui
        x, y = pyautogui.position()
        
        # Capturar região ao redor do cursor
        region = (max(0, x - 200), max(0, y - 200), x + 200, y + 200)
        screenshot = self.capture_screen_region(region)
        
        if screenshot:
            # Detectar elementos
            elements = self.vision_manager.detect_elements(screenshot)
            
            # Encontrar elemento sob o cursor
            for elem in elements:
                if (elem.position[0] <= x <= elem.position[2] and
                    elem.position[1] <= y <= elem.position[3]):
                    
                    # Classificar elemento
                    classified = self.ai_manager.classify_element(elem, screenshot)
                    
                    # Gerar descrição
                    description = self.ai_manager.generate_description(classified)
                    classified.description = description
                    
                    # Atualizar elemento em foco
                    self.focused_element = classified
                    
                    # Adicionar à lista de elementos
                    if classified not in self.current_elements:
                        self.current_elements.append(classified)
                        self.current_index = len(self.current_elements) - 1
                    
                    # Falar descrição
                    self.speech_manager.speak(description)
                    return
            
            self.speech_manager.speak("Nenhum elemento detectado sob o cursor")
    
    def detect_visual_changes_for_tab(self):
        """Detecta mudanças visuais na tela após pressionar TAB"""
        try:
            # Capturar screenshot atual
            screenshot = self.capture_active_window()
            
            if screenshot:
                # Detectar elementos
                elements = self.vision_manager.detect_elements(screenshot)
                
                if elements:
                    # Encontrar elemento que parece estar em foco
                    focused_elements = []
                    
                    for elem in elements:
                        # Verificar se o elemento tem texto
                        if elem.text:
                            focused_elements.append(elem)
                    
                    if focused_elements:
                        # Escolher o elemento mais provável (com texto)
                        best_element = max(focused_elements, key=lambda e: len(e.text) if e.text else 0)
                        
                        # Gerar descrição
                        description = self.generate_simple_description(best_element)
                        best_element.description = description
                        
                        # Atualizar elemento em foco
                        self.focused_element = best_element
                        
                        # Falar descrição
                        logger.info(f"Elemento detectado por mudança visual: {description}")
                        self.speech_manager.speak(description)
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Erro na detecção visual de mudanças: {e}")
            return False
    
    def start(self):
        """Inicia o leitor de tela"""
        if self.running:
            return
        
        self.running = True
        self.paused = False  # Garante que não está pausado
        
        # Anunciar início
        logger.info("Anunciando início do leitor de tela...")
        self.speech_manager.speak("Leitor de tela iniciado. Pressione Alt+Ctrl+P para pausar, Alt+Ctrl+Q para sair.")
        
        # Obter taxa de atualização das configurações
        refresh_rate = self.config.getfloat('general', 'refresh_rate', fallback=0.5)
        logger.info(f"Taxa de atualização: {refresh_rate} segundos")
        
        logger.info(f"Estado inicial - Rodando: {self.running}, Pausado: {self.paused}")
        
        # Iniciar contador para log periódico
        contador = 0
        
        try:
            logger.info("Iniciando loop principal...")
            while self.running:
                # Log periódico para confirmar que o loop está rodando
                contador += 1
                if contador % 20 == 0:  # Aproximadamente a cada 10 segundos
                    logger.info(f"Loop principal: iteração {contador}")
                    # Verificar estado atual
                    logger.info(f"Estado atual - Pausado: {self.paused}, Elementos: {len(self.current_elements)}")
                    
                    # Forçar uma atualização para diagnóstico
                    if contador % 100 == 0 and self.focused_element:
                        logger.info("Forçando leitura do elemento em foco para diagnóstico")
                        self.speech_manager.speak("Verificação diagnóstica do leitor de tela")
                
                # Processar comandos
                self.process_commands()
                
                # Processar tela
                if not self.paused:
                    self.process_screen()
                else:
                    logger.debug("Processamento de tela pausado")
                
                # Aguardar antes da próxima atualização
                time.sleep(refresh_rate)
        
        except Exception as e:
            logger.error(f"Erro no loop principal: {e}")
            logger.error("Detalhes do erro:", exc_info=True)
        finally:
            logger.info("Finalizando leitor de tela...")
            self.cleanup()
    
    def stop(self):
        """Para o leitor de tela"""
        self.running = False
        self.speech_manager.speak("Encerrando leitor de tela")
    
    def cleanup(self):
        """Limpa recursos antes de encerrar"""
        try:
            # Liberar recursos do mecanismo de fala
            if hasattr(self, 'speech_manager') and self.speech_manager.engine:
                self.speech_manager.engine.stop()
            
            # Remover hook de teclado se estiver instalado
            if hasattr(self, 'keyboard_hook') and self.keyboard_hook:
                import ctypes
                ctypes.windll.user32.UnhookWindowsHookEx(self.keyboard_hook)
                logger.info("Hook de teclado removido")
            
            logger.info("Recursos liberados com sucesso")
        except Exception as e:
            logger.error(f"Erro ao liberar recursos: {e}")

    def generate_simple_description(self, element):
        """Gera descrições que incluem o texto detectado pelo OCR, otimizado para navegadores"""
        element_type = element.element_type.value
        position = element.position
        width = position[2] - position[0]
        height = position[3] - position[1]
        
        # Verificar se estamos em um navegador
        is_browser_element = hasattr(element, 'accessibility_id') and element.accessibility_id == "browser_element"
        
        # Determinar tipo baseado no texto para elementos de navegador
        if is_browser_element and hasattr(element, 'text') and element.text:
            text = element.text.lower()
            if any(term in text for term in ["curtir", "like", "seguir", "follow", "enviar", "send", "postar", "post"]):
                element_type = "botão"
            elif any(term in text for term in ["buscar", "pesquisar", "search", "procurar"]):
                element_type = "campo de pesquisa"
            elif text.startswith("http") or text.endswith(".com") or text.endswith(".br") or text.endswith(".net"):
                element_type = "link"
        
        # Definir tipo com base nas proporções
        if element_type == "elemento desconhecido":
            if width < 50 and height < 50 and abs(width - height) < 10:
                element_type = "botão"
            elif width > height * 3:
                element_type = "campo de texto"
            elif height > width * 1.5:
                element_type = "barra de rolagem"
            else:
                element_type = "elemento"
        
        # IMPORTANTE: Verificar DIRETAMENTE se há texto detectado pelo OCR
        # e usar esse texto na descrição
        if hasattr(element, 'text') and element.text and len(element.text.strip()) > 0:
            # Limpar texto para não ter caracteres estranhos
            clean_text = element.text.strip()
            
            # Verificar se não é apenas a posição padrão ("Elemento em X,Y")
            if not clean_text.startswith("Elemento em"):
                # Para textos longos, truncar
                if len(clean_text) > 30:
                    clean_text = clean_text[:27] + "..."
                    
                # Esta é a chave: incluir o texto detectado na descrição!
                description = f"{element_type} com texto '{clean_text}'"
                
                # Debug para confirmar que o texto está sendo usado
                logger.debug(f"Usando texto OCR na descrição: '{clean_text}'")
                
                # Adicionar informação de posição para elementos importantes
                x_center = (position[0] + position[2]) // 2
                y_center = (position[1] + position[3]) // 2
                
                if element_type in ["botão", "link", "checkbox"]:
                    # Adicionar posição relativa para facilitar localização
                    if x_center < 400:
                        description += " no lado esquerdo"
                    elif x_center > 800:
                        description += " no lado direito"
                        
                    if y_center < 300:
                        description += " superior"
                    elif y_center > 600:
                        description += " inferior"
                
                return description
        
        # Se não há texto ou não passou nas verificações, usar descrição de posição/tamanho
        x_center = (position[0] + position[2]) // 2
        y_center = (position[1] + position[3]) // 2
        
        description = f"{element_type} de {width} por {height} pixels"
        
        # Adicionar informação de posição relativa
        if x_center < 400:
            description += " no lado esquerdo"
        elif x_center > 800:
            description += " no lado direito"
        else:
            description += " no centro"
            
        if y_center < 300:
            description += " superior"
        elif y_center > 600:
            description += " inferior"
        
        # Adicionar informação sobre foco de teclado quando relevante
        if hasattr(element, 'accessibility_id') and element.accessibility_id == "tab_focused":
            description += " (em foco)"
        
        return description
    
    def handle_tab_press(self):
        """Processa o pressionamento da tecla TAB para focar em novo elemento"""
        try:
            # Dar um tempo para o sistema operacional atualizar o foco
            time.sleep(0.2)
            
            # Evitar eventos TAB repetidos em rápida sucessão
            current_time = time.time()
            if hasattr(self, 'last_tab_time') and current_time - self.last_tab_time < 0.7:
                logger.info("Ignorando evento TAB repetido")
                return
                
            self.last_tab_time = current_time
            
            # Verificar se estamos em um navegador
            browser = self.html_accessibility_manager.detect_browser()
            
            if browser:
                logger.info(f"Processando TAB em navegador: {browser}")
                
                # Tentar obter elemento HTML em foco
                html_element = self.html_accessibility_manager.get_focused_html_element()
                
                if html_element:
                    # Gerar descrição para o elemento
                    description = self.generate_html_description(html_element)
                    html_element.description = description
                    
                    # Atualizar elemento em foco
                    self.focused_element = html_element
                    
                    # Falar a descrição
                    logger.info(f"Elemento HTML em foco após TAB: {description}")
                    self.speech_manager.speak(description)
                    return
                    
                # Se não encontrou elemento HTML, tentar métodos visuais
                logger.info("Elemento HTML não encontrado, tentando métodos visuais")
                
                # Primeiro tentar detectar realce visual (mais preciso)
                if self.detect_visual_changes_after_tab():
                    return
                
                # Se não detectar realce, tentar o método alternativo
                if self.handle_tab_press_for_browsers():
                    return
            
            # Para aplicativos não-navegador, usar o método padrão
            # Capturar screenshot da área ativa por segurança
            screenshot = self.capture_active_window()
            
            # Tentar obter o elemento em foco via teclado
            element = self.accessibility_manager.get_keyboard_focused_element()
            
            if element:
                # Gerar descrição para o elemento
                description = self.generate_simple_description(element)
                element.description = description
                
                # Atualizar elemento em foco
                self.focused_element = element
                
                # Falar a descrição
                logger.info(f"Foco de teclado (TAB): {description}")
                self.speech_manager.speak(description)
            else:
                # Plano alternativo: detectar mudanças visuais na tela
                logger.debug("Nenhum elemento detectado após TAB usando APIs, tentando detecção visual")
                
                # Usar detecção visual como backup
                self.detect_visual_changes_for_tab()
        except Exception as e:
            logger.error(f"Erro ao processar pressionamento de TAB: {e}")

    def capture_active_window(self):
        """Captura um screenshot da janela ativa"""
        try:
            import win32gui
            
            # Obter handle e retângulo da janela em primeiro plano
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                rect = win32gui.GetWindowRect(hwnd)
                x1, y1, x2, y2 = rect
                
                # Capturar apenas a área da janela
                screenshot = ImageGrab.grab(bbox=rect)
                return screenshot
        except Exception as e:
            logger.error(f"Erro ao capturar janela ativa: {e}")
        
        # Fallback para captura de tela inteira
        return ImageGrab.grab()
    
    def handle_tab_press_for_browsers(self):
        """Versão aprimorada para navegadores do método handle_tab_press que detecta o elemento visual destacado pelo Tab"""
        try:
            # Verificar se estamos em um navegador
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            
            is_browser = any(browser in title.lower() for browser in ["chrome", "firefox", "edge", "safari", "opera"])
            
            if is_browser:
                logger.info(f"Detectado navegador: {title}")
                
                # Capturar screenshot ANTES do tab
                rect = win32gui.GetWindowRect(hwnd)
                x1, y1, x2, y2 = rect
                content_top = y1 + 100  # Pular barra de endereço
                before_screenshot = self.capture_screen_region((x1, content_top, x2, y2))
                
                # Aguardar brevemente para o foco de seleção aparecer
                time.sleep(0.1)
                
                # Capturar screenshot DEPOIS do tab
                after_screenshot = self.capture_screen_region((x1, content_top, x2, y2))
                
                if before_screenshot and after_screenshot:
                    # Converter screenshots para arrays numpy
                    before_array = np.array(before_screenshot)
                    after_array = np.array(after_screenshot)
                    
                    # Calcular a diferença entre as imagens
                    diff = cv2.absdiff(before_array, after_array)
                    
                    # Converter para escala de cinza
                    gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
                    
                    # Aplicar threshold para identificar alterações significativas
                    _, thresh = cv2.threshold(gray_diff, 15, 255, cv2.THRESH_BINARY)
                    
                    # Dilatação para conectar áreas próximas
                    kernel = np.ones((5, 5), np.uint8)
                    dilated = cv2.dilate(thresh, kernel, iterations=1)
                    
                    # Encontrar contornos das áreas que mudaram
                    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    
                    # Se encontrou áreas de mudança
                    if contours:
                        # Filtrar pequenas alterações (ruído)
                        significant_contours = [cnt for cnt in contours if cv2.contourArea(cnt) > 100]
                        
                        # Se houver alterações significativas
                        if significant_contours:
                            # Encontrar a maior área alterada (provavelmente o elemento em foco)
                            largest_contour = max(significant_contours, key=cv2.contourArea)
                            x, y, w, h = cv2.boundingRect(largest_contour)
                            
                            # Expandir a região para incluir o elemento completo
                            padding = 10
                            focus_region = (
                                max(0, x - padding),
                                max(0, y - padding),
                                min(after_array.shape[1], x + w + padding),
                                min(after_array.shape[0], y + h + padding)
                            )
                            
                            # Capturar região do elemento em foco
                            focus_screenshot = after_array[
                                focus_region[1]:focus_region[3], 
                                focus_region[0]:focus_region[2]
                            ]
                            
                            # Salvar para debug ocasionalmente
                            if hasattr(self, '_focus_debug_counter'):
                                self._focus_debug_counter += 1
                            else:
                                self._focus_debug_counter = 0
                                
                            if self._focus_debug_counter % 10 == 0:
                                cv2.imwrite("focus_element.png", cv2.cvtColor(focus_screenshot, cv2.COLOR_RGB2BGR))
                            
                            # Extrair texto do elemento focado usando OCR
                            focus_pil = Image.fromarray(focus_screenshot)
                            text = self.vision_manager.extract_text_with_ocr(focus_pil, (0, 0, focus_screenshot.shape[1], focus_screenshot.shape[0]))
                            
                            # Se encontrou texto
                            element_type = UIElementType.BUTTON  # Assumir que é um botão por padrão
                            
                            # Determinar tipo melhor com base no texto
                            if text:
                                text_lower = text.lower()
                                if any(term in text_lower for term in ["pesquisa", "busca", "search"]):
                                    element_type = UIElementType.TEXT_FIELD
                                elif any(term in text_lower for term in ["link", "http", ".com", ".br"]):
                                    element_type = UIElementType.LINK
                            
                            # Posição global do elemento
                            global_pos = (
                                focus_region[0] + x1,
                                focus_region[1] + content_top,
                                focus_region[2] + x1,
                                focus_region[3] + content_top
                            )
                            
                            # Criar elemento UI
                            focus_element = UIElement(
                                element_type,
                                global_pos,
                                text=text,
                                confidence=0.9,
                                accessibility_id="tab_focused"
                            )
                            
                            # Gerar descrição para o elemento
                            description = self.generate_simple_description(focus_element)
                            focus_element.description = description
                            
                            # Atualizar elemento em foco
                            self.focused_element = focus_element
                            
                            # Falar a descrição
                            logger.info(f"Elemento em foco após TAB: {description}")
                            self.speech_manager.speak(description)
                            return True
                        
                # Se chegou aqui, tente a abordagem alternativa
                return self.detect_visual_changes_for_tab()
                    
            return False
            
        except Exception as e:
            logger.error(f"Erro ao processar TAB em navegador: {e}")
            logger.debug("Detalhes:", exc_info=True)
            return False
        
    def setup_structured_navigation(self):
        """Configura navegação estruturada para páginas web e documentos"""
        # Adicionar atalhos especiais para navegação estruturada
        try:
            # Navegação por cabeçalhos: Alt+Ctrl+H
            keyboard.add_hotkey('alt+ctrl+h', lambda: self.command_queue.put(('navigate_headings', None)))
            
            # Navegação por links: Alt+Ctrl+L
            keyboard.add_hotkey('alt+ctrl+l', lambda: self.command_queue.put(('navigate_links', None)))
            
            # Navegação por landmarks/regiões: Alt+Ctrl+R
            keyboard.add_hotkey('alt+ctrl+r', lambda: self.command_queue.put(('navigate_regions', None)))
            
            # Navegação por tabelas: Alt+Ctrl+T
            keyboard.add_hotkey('alt+ctrl+t', lambda: self.command_queue.put(('navigate_tables', None)))
            
            # Navegação por formulários: Alt+Ctrl+F
            keyboard.add_hotkey('alt+ctrl+f', lambda: self.command_queue.put(('navigate_forms', None)))
            
            # Alternar modo de navegação: Alt+Ctrl+M
            keyboard.add_hotkey('alt+ctrl+m', lambda: self.command_queue.put(('toggle_navigation_mode', None)))
            
            # Anunciar página atual: Alt+Ctrl+I
            keyboard.add_hotkey('alt+ctrl+i', lambda: self.command_queue.put(('page_info', None)))
            
            logger.info("Atalhos de navegação estruturada configurados com sucesso")
        except Exception as e:
            logger.error(f"Erro ao configurar navegação estruturada: {e}")

    def navigate_web_elements(self, element_type):
        """Navega pelos elementos estruturais de uma página web"""
        browser = self.html_accessibility_manager.detect_browser()
        
        if not browser:
            self.speech_manager.speak("Navegação estruturada disponível apenas em navegadores")
            return
        
        try:
            # Capturar elementos HTML relevantes
            elements = []
            
            if element_type == 'headings':
                # Obter todos os cabeçalhos
                elements = self._extract_elements_by_role(role='heading')
                self.speech_manager.speak(f"Navegando por {len(elements)} cabeçalhos")
                
            elif element_type == 'links':
                # Obter todos os links
                elements = self._extract_elements_by_role(role='link')
                self.speech_manager.speak(f"Navegando por {len(elements)} links")
                
            elif element_type == 'regions':
                # Obter todas as regiões/landmarks
                elements = self._extract_elements_by_role(role=['region', 'landmark', 'main', 'navigation'])
                self.speech_manager.speak(f"Navegando por {len(elements)} regiões")
                
            elif element_type == 'forms':
                # Obter elementos de formulário
                elements = self._extract_elements_by_role(role=['textbox', 'button', 'checkbox', 'radio', 'combobox'])
                self.speech_manager.speak(f"Navegando por {len(elements)} elementos de formulário")
                
            elif element_type == 'tables':
                # Obter tabelas
                elements = self._extract_elements_by_role(role='table')
                self.speech_manager.speak(f"Navegando por {len(elements)} tabelas")
                
            # Armazenar elementos para navegação
            if elements:
                self.current_elements = elements
                self.current_index = 0
                self.focused_element = elements[0]
                
                # Ler o primeiro elemento
                self.read_current()
            else:
                self.speech_manager.speak(f"Nenhum elemento do tipo solicitado encontrado")
                
        except Exception as e:
            logger.error(f"Erro na navegação estruturada: {e}")
            self.speech_manager.speak("Erro durante navegação estruturada")

    def _extract_elements_by_role(self, role):
        """Extrai elementos HTML com base em seu papel (role) de acessibilidade"""
        try:
            if isinstance(role, str):
                role = [role]  # Converter para lista para facilitar
                
            elements = []
            
            # Usar Puppeteer ou biblioteca similar para extrair elementos por role
            # Este é um método que precisa ser implementado com a biblioteca web específica
            
            # Exemplo simplificado usando a instância de HTMLAccessibilityManager existente
            all_elements = self.html_accessibility_manager.get_html_accessibility_tree()
            
            for elem in all_elements:
                # Mapear tipo de elemento para roles de acessibilidade
                elem_role = ""
                
                if elem.element_type == UIElementType.BUTTON:
                    elem_role = "button"
                elif elem.element_type == UIElementType.LINK:
                    elem_role = "link"
                elif elem.element_type == UIElementType.TEXT_FIELD:
                    elem_role = "textbox"
                elif elem.element_type == UIElementType.CHECKBOX:
                    elem_role = "checkbox"
                elif elem.element_type == UIElementType.RADIO:
                    elem_role = "radio"
                elif elem.element_type == UIElementType.HEADING:
                    elem_role = "heading"
                
                # Se o role do elemento corresponde a um dos solicitados, adicionar à lista
                if elem_role in role:
                    elements.append(elem)
            
            return elements
        
        except Exception as e:
            logger.error(f"Erro ao extrair elementos por role: {e}")
            return []

    def page_info(self):
        """Fornece informações resumidas sobre a página atual"""
        try:
            browser = self.html_accessibility_manager.detect_browser()
            
            if not browser:
                self.speech_manager.speak("Informações de página disponíveis apenas em navegadores")
                return
                
            # Capturar screenshot da janela ativa
            screenshot = self.capture_active_window()
            
            if not screenshot:
                self.speech_manager.speak("Não foi possível capturar a página atual")
                return
                
            # Extrair elementos principais
            elements = self.html_accessibility_manager.get_html_accessibility_tree()
            
            # Contar elementos por tipo
            headings = 0
            links = 0
            buttons = 0
            forms = 0
            images = 0
            
            for elem in elements:
                if elem.element_type == UIElementType.HEADING:
                    headings += 1
                elif elem.element_type == UIElementType.LINK:
                    links += 1
                elif elem.element_type == UIElementType.BUTTON:
                    buttons += 1
                elif elem.element_type == UIElementType.TEXT_FIELD:
                    forms += 1
                elif elem.element_type == UIElementType.IMAGE:
                    images += 1
            
            # Obter título da página
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            page_title = win32gui.GetWindowText(hwnd)
            
            # Gerar resumo
            summary = f"Página atual: {page_title}. "
            summary += f"Contém {headings} cabeçalhos, {links} links, {buttons} botões, "
            summary += f"{forms} campos de formulário e {images} imagens."
            
            # Adicionar sugestão de atalhos
            summary += " Use ALT+CTRL+H para navegar por cabeçalhos ou ALT+CTRL+L para navegar por links."
            
            # Falar o resumo
            self.speech_manager.speak(summary)
            
        except Exception as e:
            logger.error(f"Erro ao obter informações da página: {e}")
            self.speech_manager.speak("Erro ao obter informações da página")

    def adjust_settings_for_performance(self):
        """Ajusta configurações com base nas capacidades do sistema"""
        try:
            import psutil
            
            # Verificar recursos disponíveis
            cpu_count = psutil.cpu_count(logical=False)  # Núcleos físicos
            memory = psutil.virtual_memory()
            available_memory_gb = memory.available / (1024 ** 3)
            
            logger.info(f"CPU cores: {cpu_count}, Memória disponível: {available_memory_gb:.2f}GB")
            
            # Ajustar OCR baseado em CPU
            if cpu_count <= 2:
                # CPU fraca, reduzir o número de threads para OCR
                if hasattr(self.vision_manager, 'reader') and self.vision_manager.reader:
                    self.vision_manager.reader = easyocr.Reader(['pt', 'en'], gpu=False, recog_network='standard')
                    logger.info("Configuração de OCR ajustada para desempenho em CPUs limitadas")
            
            # Ajustar uso de memória para o modelo
            if available_memory_gb < 4:
                # Pouca memória, usar modelo mais leve ou desabilitar
                self.config.set('ai', 'use_lite_model', 'true')
                if available_memory_gb < 2:
                    # Memória muito limitada, desabilitar modelo completamente
                    self.config.set('ai', 'enabled', 'false')
                    logger.warning("Modelo de IA desabilitado devido a restrições de memória")
                else:
                    # Memória limitada, usar modelo extremamente leve
                    logger.info("Usando modelo de IA extremamente leve devido a restrições de memória")
                
                # Recarregar o gerenciador de IA
                self.ai_manager = AIManager(self.config)
            
            # Ajustar taxa de atualização baseado na CPU
            if cpu_count <= 2:
                # CPU fraca, reduzir a taxa de atualização
                refresh_rate = 1.0  # 1 segundo
                self.config.set('general', 'refresh_rate', str(refresh_rate))
                logger.info(f"Taxa de atualização ajustada para {refresh_rate}s devido a CPU limitada")
            
            # Salvar configurações atualizadas
            with open('ai_screen_reader.ini', 'w') as f:
                self.config.write(f)
            
        except Exception as e:
            logger.error(f"Erro ao ajustar configurações para desempenho: {e}")
        
class EnhancedAudioFeedback:
    """Fornece feedback sonoro avançado além da síntese de voz"""
    
    def __init__(self, config):
        self.config = config
        self.enabled = self.config.getboolean('audio', 'use_enhanced_audio', fallback=True)
        # Pasta onde estão os arquivos de som
        self.sounds_folder = self.config.get('audio', 'sounds_folder', fallback='sounds')
        
        # Garantir que a pasta de sons existe
        if not os.path.exists(self.sounds_folder):
            try:
                os.makedirs(self.sounds_folder)
            except:
                pass
        
        # Inicializar biblioteca de áudio
        try:
            import winsound
            self.winsound = winsound
            self.audio_available = True
        except:
            self.audio_available = False
    
    def play_earcon(self, sound_type):
        """Toca um som não-verbal para indicar diferentes tipos de elementos"""
        if not self.enabled or not self.audio_available:
            return
        
        try:
            sound_file = None
            
            # Mapear tipo para arquivo de som
            if sound_type == "button":
                sound_file = os.path.join(self.sounds_folder, "button.wav")
            elif sound_type == "link":
                sound_file = os.path.join(self.sounds_folder, "link.wav")
            elif sound_type == "text_field":
                sound_file = os.path.join(self.sounds_folder, "textfield.wav")
            elif sound_type == "error":
                sound_file = os.path.join(self.sounds_folder, "error.wav")
            elif sound_type == "success":
                sound_file = os.path.join(self.sounds_folder, "success.wav")
            elif sound_type == "navigation":
                sound_file = os.path.join(self.sounds_folder, "navigation.wav")
            
            # Se não tiver arquivo customizado, usar sons do sistema
            if sound_file and os.path.exists(sound_file):
                self.winsound.PlaySound(sound_file, self.winsound.SND_FILENAME | self.winsound.SND_ASYNC)
            elif sound_type == "error":
                self.winsound.PlaySound("SystemHand", self.winsound.SND_ALIAS | self.winsound.SND_ASYNC)
            elif sound_type == "success":
                self.winsound.PlaySound("SystemAsterisk", self.winsound.SND_ALIAS | self.winsound.SND_ASYNC)
            elif sound_type in ["button", "link"]:
                self.winsound.PlaySound("SystemQuestion", self.winsound.SND_ALIAS | self.winsound.SND_ASYNC)
            else:
                # Som padrão para outros casos
                self.winsound.Beep(500, 100)
                
        except Exception as e:
            logger.error(f"Erro ao reproduzir earcon: {e}")

class ImageDescriber:
    """Gera descrições acessíveis para imagens e gráficos"""
    
    def __init__(self, config):
        self.config = config
        # Flag para habilitar/desabilitar o recurso
        self.enabled = self.config.getboolean('accessibility', 'describe_images', fallback=True)
        
        # Inicializar modelo de reconhecimento de imagens (se disponível)
        try:
            if self.enabled:
                # Tentar modelo leve primeiro
                import torchvision.models as models
                import torchvision.transforms as transforms
                
                # Usar um modelo pré-treinado mais leve (MobileNet em vez de ResNet)
                self.model = models.mobilenet_v2(pretrained=True)
                self.model.eval()
                
                # Transformações para processamento da imagem
                self.transform = transforms.Compose([
                    transforms.Resize(256),
                    transforms.CenterCrop(224),
                    transforms.ToTensor(),
                    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
                ])
                
                # Carregar classes do ImageNet
                with open('imagenet_classes.txt') as f:
                    self.classes = [line.strip() for line in f.readlines()]
                
                logger.info("Modelo de descrição de imagens inicializado com sucesso")
                
                # Inicializar OCR para texto em imagens
                self.ocr_available = hasattr(self, 'reader') and self.reader is not None
                
                self.model_available = True
            else:
                self.model_available = False
                
        except Exception as e:
            logger.error(f"Erro ao inicializar modelo de descrição de imagens: {e}")
            logger.info("Descrição avançada de imagens desabilitada")
            self.model_available = False
    
    def describe_image(self, image):
        """Gera uma descrição para uma imagem"""
        if not self.enabled or not self.model_available:
            return "Imagem detectada. Descrição avançada não disponível."
        
        try:
            # Converter para formato do PyTorch
            if isinstance(image, Image.Image):
                pil_image = image
            else:
                pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            
            # Aplicar transformações
            input_tensor = self.transform(pil_image)
            input_batch = input_tensor.unsqueeze(0)
            
            # Realizar predição
            with torch.no_grad():
                output = self.model(input_batch)
            
            # Obter as 3 classes mais prováveis
            _, indices = torch.sort(output, descending=True)
            top_classes = [self.classes[idx] for idx in indices[0][:3]]
            
            # Extrair texto da imagem usando OCR
            ocr_text = ""
            if self.ocr_available:
                width, height = pil_image.size
                results = self.reader.readtext(np.array(pil_image))
                ocr_texts = [text for _, text, conf in results if conf > 0.4]
                if ocr_texts:
                    ocr_text = f" com texto: {', '.join(ocr_texts)}"
            
            # Gerar descrição
            description = f"Imagem contendo {', '.join(top_classes)}{ocr_text}"
            return description
            
        except Exception as e:
            logger.error(f"Erro ao descrever imagem: {e}")
            return "Imagem detectada. Erro na geração da descrição."

class AppProfiler:
    """Gerencia perfis otimizados para diferentes aplicações"""
    
    def __init__(self):
        # Dicionário de perfis para aplicações populares
        self.app_profiles = {
            # Redes Sociais
            "facebook": {
                "common_elements": {
                    "curtir": ["Like", "Curtir", "Gostei"],
                    "comentar": ["Comment", "Comentar", "Comentário"],
                    "compartilhar": ["Share", "Compartilhar", "Compartilhe"],
                    "publicar": ["Post", "Publicar", "Postar"],
                    "stories": ["Stories", "Story"],
                    "feed": ["Feed", "Notícias", "Timeline"]
                },
                "regions": ["Feed", "Stories", "Conversas", "Menu", "Perfil"]
            },
            "instagram": {
                "common_elements": {
                    "curtir": ["Like", "Curtir", "Gostei", "♥"],
                    "comentar": ["Comment", "Comentar"],
                    "salvar": ["Save", "Salvar", "Guardar"],
                    "publicar": ["Post", "Share", "Publicar"],
                    "stories": ["Stories", "Story"],
                    "reels": ["Reels", "Reel", "Video"]
                },
                "regions": ["Feed", "Stories", "Explorar", "Reels", "Perfil"]
            },
            
            # Produtividade
            "gmail": {
                "common_elements": {
                    "escrever": ["Compose", "Escrever", "Novo email"],
                    "enviar": ["Send", "Enviar"],
                    "anexar": ["Attach", "Anexar", "Anexo"],
                    "responder": ["Reply", "Responder"],
                    "encaminhar": ["Forward", "Encaminhar"]
                },
                "regions": ["Caixa de entrada", "Enviados", "Rascunhos", "Categorias"]
            },
            "outlook": {
                "common_elements": {
                    "novo": ["New", "Novo", "Novo email"],
                    "enviar": ["Send", "Enviar"],
                    "anexar": ["Attach", "Anexar"],
                    "responder": ["Reply", "Responder"],
                    "encaminhar": ["Forward", "Encaminhar"]
                },
                "regions": ["Caixa de entrada", "Enviados", "Rascunhos", "Calendário"]
            },
            
            # Edição de textos
            "word": {
                "common_elements": {
                    "salvar": ["Save", "Salvar"],
                    "imprimir": ["Print", "Imprimir"],
                    "formatar": ["Format", "Formatar"],
                    "inserir": ["Insert", "Inserir"],
                    "revisar": ["Review", "Revisar"]
                },
                "shortcuts": {
                    "ctrl+b": "Negrito",
                    "ctrl+i": "Itálico",
                    "ctrl+u": "Sublinhado",
                    "ctrl+z": "Desfazer",
                    "ctrl+s": "Salvar"
                }
            },
            
            # Navegadores
            "chrome": {
                "common_elements": {
                    "guia": ["Tab", "Guia", "Nova guia"],
                    "favoritos": ["Bookmark", "Favorito"],
                    "voltar": ["Back", "Voltar"],
                    "avançar": ["Forward", "Avançar"],
                    "atualizar": ["Refresh", "Reload", "Atualizar"]
                },
                "shortcuts": {
                    "ctrl+t": "Nova guia",
                    "ctrl+w": "Fechar guia",
                    "ctrl+l": "Focar na barra de endereço",
                    "ctrl+f": "Buscar na página"
                }
            }
        }
        
        # Atalhos de teclado padrão para auxiliar usuários
        self.common_shortcuts = {
            "alt+tab": "Alternar entre aplicações",
            "alt+f4": "Fechar aplicação",
            "windows+d": "Mostrar área de trabalho",
            "windows+e": "Abrir explorador de arquivos",
            "ctrl+c": "Copiar",
            "ctrl+v": "Colar",
            "ctrl+x": "Recortar",
            "ctrl+z": "Desfazer",
            "ctrl+y": "Refazer"
        }
    
    def get_app_profile(self, window_title):
        """Identifica a aplicação atual e retorna seu perfil"""
        window_title_lower = window_title.lower()
        
        for app_name, profile in self.app_profiles.items():
            if app_name in window_title_lower:
                return app_name, profile
        
        # Se não encontrou perfil específico, retornar perfil genérico
        return "generic", {"common_elements": {}, "regions": []}
    
    def get_element_context(self, app_name, element_text):
        """Interpreta o elemento no contexto da aplicação"""
        if not element_text:
            return None
            
        element_text_lower = element_text.lower()
        
        # Obter perfil da aplicação
        if app_name in self.app_profiles:
            profile = self.app_profiles[app_name]
            
            # Verificar se o texto corresponde a algum elemento comum
            for action, keywords in profile.get("common_elements", {}).items():
                for keyword in keywords:
                    if keyword.lower() in element_text_lower:
                        return action
        
        return None
    
    def suggest_shortcuts(self, app_name):
        """Sugere atalhos úteis para a aplicação atual"""
        shortcuts = []
        
        # Adicionar atalhos específicos da aplicação
        if app_name in self.app_profiles and "shortcuts" in self.app_profiles[app_name]:
            shortcuts.extend([f"{key}: {desc}" for key, desc in self.app_profiles[app_name]["shortcuts"].items()])
        
        # Adicionar alguns atalhos comuns
        shortcuts.extend([f"{key}: {desc}" for key, desc in list(self.common_shortcuts.items())[:5]])
        
        return shortcuts
    

class ErrorRecovery:
    """Sistema de recuperação de erros e monitoramento de estabilidade"""
    
    def __init__(self, screen_reader):
        self.screen_reader = screen_reader
        self.error_counts = {}
        self.error_thresholds = {
            "speech": 5,  # Número máximo de erros antes de reiniciar o componente
            "ocr": 3,
            "model": 2,
            "accessibility": 4
        }
        self.component_last_restart = {
            "speech": 0,
            "ocr": 0,
            "model": 0,
            "accessibility": 0
        }
        self.min_restart_interval = 60  # Segundos mínimos entre reinícios
    
    def log_error(self, component, error):
        """Registra um erro e tenta recuperação se necessário"""
        logger.error(f"Erro no componente {component}: {error}")
        
        # Incrementar contador de erros
        if component in self.error_counts:
            self.error_counts[component] += 1
        else:
            self.error_counts[component] = 1
        
        # Verificar se ultrapassou o limite
        if (component in self.error_thresholds and 
            self.error_counts[component] >= self.error_thresholds[component]):
            
            # Verificar se já se passou tempo suficiente desde o último reinício
            current_time = time.time()
            if (current_time - self.component_last_restart.get(component, 0) > 
                self.min_restart_interval):
                
                logger.warning(f"Tentando recuperar componente: {component}")
                
                # Tentar reiniciar o componente
                success = self.restart_component(component)
                
                if success:
                    # Limpar contador de erros e atualizar horário do último reinício
                    self.error_counts[component] = 0
                    self.component_last_restart[component] = current_time
                    logger.info(f"Componente {component} reiniciado com sucesso")
                    
                    # Anunciar a recuperação para o usuário
                    self.screen_reader.speech_manager.speak(
                        f"Componente {component} foi reiniciado para resolver um problema."
                    )
    
    def restart_component(self, component):
        """Reinicia um componente específico do sistema"""
        try:
            if component == "speech":
                # Reiniciar mecanismo de fala
                self.screen_reader.speech_manager = SpeechManager(self.screen_reader.config)
                return True
                
            elif component == "ocr":
                # Reiniciar motor OCR
                self.screen_reader.vision_manager.reader = easyocr.Reader(['pt', 'en'], gpu=False)
                self.screen_reader.vision_manager.ocr_cache = {}  # Limpar cache
                return True
                
            elif component == "model":
                # Tentar reiniciar modelo com configurações mais leves
                config = self.screen_reader.config
                config.set('ai', 'use_lite_model', 'true')
                self.screen_reader.ai_manager = AIManager(config)
                return True
                
            elif component == "accessibility":
                # Reiniciar gerenciadores de acessibilidade
                self.screen_reader.accessibility_manager = AccessibilityManager()
                self.screen_reader.html_accessibility_manager = HTMLAccessibilityManager(
                    self.screen_reader.accessibility_manager
                )
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Erro ao tentar reiniciar componente {component}: {e}")
            return False
    
    def check_system_health(self):
        """Verifica a saúde geral do sistema e faz ajustes preventivos"""
        try:
            # Verificar uso de memória
            import psutil
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            
            if memory_percent > 90:
                # Alto uso de memória, tomar medidas preventivas
                logger.warning(f"Uso de memória crítico: {memory_percent}%, tomando medidas preventivas")
                
                # Limpar caches
                self.screen_reader.vision_manager.ocr_cache = {}
                
                # Forçar coleta de lixo Python
                import gc
                gc.collect()
                
                # Notificar o usuário sobre a situação
                self.screen_reader.speech_manager.speak(
                    "Sistema com pouca memória disponível. Desempenho pode ser afetado."
                )
        
        except Exception as e:
            logger.error(f"Erro ao verificar saúde do sistema: {e}")

def main():
    """Função principal"""
    try:
        # Mostrar mensagem de boas-vindas
        print("=== AI-NVDA: Leitor de Tela Aprimorado com IA ===")
        print("Iniciando componentes...")
        
        # Criar e iniciar o leitor de tela
        reader = ScreenReader()
        reader.start()
    
    except Exception as e:
        logger.critical(f"Erro fatal: {e}")
        print(f"Erro ao iniciar o leitor de tela: {e}")
    
    finally:
        print("Leitor de tela encerrado.")

# Função para testar componentes básicos
def testar_componentes():
    print("=== TESTE DE COMPONENTES DO LEITOR DE TELA ===")
    
    # Carregar configuração
    config = configparser.ConfigParser()
    config['general'] = {'refresh_rate': '0.5', 'use_accessibility_api': 'true', 'use_vision': 'true'}
    config['ai'] = {'model_name': 'microsoft/Phi-3-mini-4k-instruct', 'use_8bit': 'false'}
    config['speech'] = {'voice_id': '', 'rate': '200'}
    
    # Testar mecanismo de fala
    print("1. Testando mecanismo de fala...")
    speech = SpeechManager(config)
    speech.speak("Teste do mecanismo de fala. Se você está ouvindo esta mensagem, a fala está funcionando.")
    time.sleep(3)
    
    # Testar captura de tela
    print("2. Testando captura de tela...")
    try:
        screenshot = ImageGrab.grab()
        screenshot.save("teste_screenshot.png")
        print("   Screenshot salvo como 'teste_screenshot.png'")
        speech.speak("Captura de tela realizada com sucesso")
    except Exception as e:
        print(f"   Erro na captura: {e}")
    
    # Testar janela em foco
    print("3. Testando detecção de janela em foco...")
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        print(f"   Janela em foco: '{title}', posição: {rect}")
        speech.speak(f"Janela atual: {title}")
    except Exception as e:
        print(f"   Erro na detecção: {e}")
    
    # Testar modelo de IA (simples)
    print("4. Testando modelo de IA...")
    try:
        ai = AIManager(config)
        if ai.model and ai.tokenizer:
            element = UIElement(UIElementType.BUTTON, (10, 10, 100, 50), text="Botão de Teste")
            description = ai.generate_description(element)
            print(f"   Descrição gerada: {description}")
            speech.speak(f"Descrição: {description}")
        else:
            print("   Modelo de IA não disponível")
    except Exception as e:
        print(f"   Erro no teste de IA: {e}")
    
    print("\nTestes concluídos. Verifique se você ouviu todas as mensagens de voz.")
    print("=== FIM DOS TESTES ===")


if __name__ == "__main__":
    main()
    testar_componentes()  # Executa apenas o teste de componentes