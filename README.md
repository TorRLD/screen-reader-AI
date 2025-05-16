<!-- README.md - AI‑NVDA -->

<h1 align="center">
  🦾🎙️ <strong>AI‑NVDA</strong><br>
  <small>Leitor de Tela Aprimorado com IA</small>
</h1>

<p align="center">
  <em>Uma alternativa leve ao NVDA que mescla APIs de acessibilidade nativas, visão computacional, OCR e LLMs para tornar qualquer interface verdadeiramente falável.</em>
</p>

<p align="center">
  <img alt="GitHub last commit" src="https://img.shields.io/github/last-commit/your-org/ai-nvda?style=for-the-badge">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-blue.svg?style=for-the-badge">
  <img alt="Python" src="https://img.shields.io/badge/python-3.9%2B-yellow.svg?style=for-the-badge">
</p>

---

## ✨ Principais Recursos

| 🚀 Categoria | ⚡ Descrição |
|--------------|-------------|
| **Acessibilidade nativa** | Integra‑se às APIs do Windows (UIA), macOS (Quartz) e Linux (AT‑SPI) para obter foco, árvore de elementos e eventos de interface. |
| **Visão computacional** | OpenCV + EasyOCR identificam botões, campos, itens de menu e texto em tempo real. |
| **IA generativa** | **Phi‑3‑mini‑4k‑instruct** é carregado em 8‑bit (GPU ou CPU) e alterna para modelos menores se faltar memória. |
| **TTS local** | *pyttsx3* seleciona automaticamente a melhor voz no idioma do sistema. |
| **Atalhos de teclado** | Navegue sem mouse: Alt + Ctrl + →/←, Alt + Ctrl + C, etc. |
| **Recuperação automática** | Monitor watchdog reinicializa módulos de OCR, TTS ou IA em caso de falha. |
| **Perfis de apps** | Ajustes dedicados para Facebook, Gmail, Word, Chrome, VS Code e mais. |

---

## 📂 Estrutura de Pastas

```text
.
├── models/              # Pesos adicionais (OpenCV, quantização etc.)
├── screen/              # Módulos auxiliares
├── screen-reader.py     # Arquivo principal
├── ai_screen_reader.ini # Config gerada na primeira execução
└── ai_screen_reader.log # Log detalhado
```

---

## ⚙️ Pré‑requisitos

* **Python ≥ 3.9 (64‑bit)**  
* Internet para baixar modelos da Hugging Face¹ na primeira execução  
* **Windows:** VC++ Redistributable 2015‑2022 (para *pyttsx3* / *pywin32*)

> ¹ Cache local após o primeiro download — não é necessário conexão constante.

---

## 🚀 Instalação Rápida

```bash
# Crie e ative um ambiente virtual
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Instale as dependências
pip install -r requirements.txt
```

> 💡 **Dica:** em máquinas sem GPU ou com menos de 4 GB de RAM, execute uma vez para gerar `ai_screen_reader.ini` e então defina `use_lite_model = true` na seção `[ai]`.

---

## 🔑 Configuração Inicial

1. Gere um **Access Token (Read)** em <https://huggingface.co/settings/tokens>.  
2. Abra `screen-reader.py` e substitua `login("")` pelo token.  
3. Execute `python screen-reader.py` uma vez para gerar `ai_screen_reader.ini`.

---

## ▶️ Uso Básico

```bash
python screen-reader.py
```

> Na inicialização você ouvirá:  
> “Leitor de tela iniciado. Pressione **Alt + Ctrl + P** para pausar ou **Alt + Ctrl + Q** para sair.”

### ⌨️ Atalhos Essenciais

| Combinação                      | Ação |
|---------------------------------|------|
| Alt + Ctrl + P                  | Pausar / retomar leitura |
| Alt + Ctrl + Q                  | Encerrar o leitor |
| Alt + Ctrl + → / ←             | Próximo / anterior elemento |
| Alt + Ctrl + Espaço             | Descrever elemento em foco |
| Alt + Ctrl + A                  | Ler todos os elementos da tela |
| Alt + Ctrl + C                  | Descrever elemento sob o cursor |
| Tab                             | Segue foco do SO + leitura automática |
| Navegação Estruturada           | **Alt + Ctrl +** H (Headers), L (Links), R (Regiões), F (Forms), T (Tables) |

---

## 🛠️ Personalização

| Arquivo | O que mudar |
|---------|-------------|
| `ai_screen_reader.ini` | Modelo, TTS, idioma, sensibilidade de OCR, earcons. |
| `models/` | Substitua ou adicione checkpoints de visão / LLM. |

---

## 🚧 Problemas Conhecidos / Roadmap

| Prioridade | Problema | Status |
|------------|----------|--------|
| 🔴 Alto | **Imprecisão no reconhecimento** de botões muito pequenos ou com baixo contraste. | Refinar pré‑processamento OCR; treinar cascades personalizados. |
| 🔴 Alto | **Navegação com Tab** – alguns elementos focáveis não são anunciados, especialmente em apps Electron. | Mapear os eventos de foco via UIA/AT‑SPI; fallback por heurísticas visuais. |
| 🟠 Médio | Latência perceptível ao alternar rapidamente entre janelas. | Implementar diff de framebuffer para reduzir OCR redundante. |
| 🟠 Médio | Consumo de CPU acima de 30 % em telas dinâmicas (vídeos, animações). | Processamento por pipeline assíncrono + throttling adaptativo. |
| 🟡 Baixo | Memória do modelo ainda alta (~2 GB) em CPUs antigas. | Explorar LoRA + quantização 4‑bit. |

Acompanhe o progresso na aba **Issues** e sinta‑se convidado(a) a contribuir!

---

## 🤝 Contribuição

1. **Fork** → **Branch** → **PR**.  
2. Siga **PEP 8** e documente funções em português ou inglês consistente.  
3. Inclua testes unitários para novas features.  
4. Atualize `requirements.txt` se adicionar libs externas.

---

## 📜 Licença

Distribuído sob a [MIT License](LICENSE).

---

<p align="center"><em>Happy hacking & keep it accessible! 💙</em></p>
