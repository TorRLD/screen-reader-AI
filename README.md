# AI‑NVDA – Leitor de Tela Aprimorado com IA

Uma alternativa leve ao NVDA que combina **APIs de acessibilidade** nativas, **visão computacional**, **OCR** e **modelos de linguagem** para identificar, descrever e navegar por elementos de interface em tempo real.

## Principais recursos
| Categoria | Descrição resumida |
|-----------|--------------------|
| Acessibilidade nativa | Integra‑se às APIs do Windows, macOS e Linux (AT‑SPI) para obter foco, árvore de elementos e funções de automação |
| Visão computacional | Detecta botões, campos, textos e ícones via OpenCV; aplica OCR otimizado *EasyOCR* para textos pequenos |
| IA generativa | Usa **Phi‑3‑mini‑4k‑instruct** por padrão (8‑bit GPU ou CPU) e alterna para modelos menores se a memória for limitada |
| TTS | Conversão texto‑para‑fala local com *pyttsx3*, seleção automática de voz em português se disponível |
| Atalhos de teclado | Controle completo sem mouse (lista abaixo) |
| Navegação estruturada | Cabeçalhos, links, regiões, formulários, tabelas |
| Recuperação automática | Monitor de erros reinicia componentes de OCR, fala, modelo ou acessibilidade se necessário |
| Perfis de apps | Otimizações para Facebook, Instagram, Gmail, Word, Chrome etc. |

## Estrutura de pastas
```
.
├── models/              # Pesos adicionais de CV (ex.: cascades do OpenCV)
├── screen/              # Módulos auxiliares
├── screen-reader.py     # Arquivo principal
├── ai_screen_reader.ini # Configurações geradas na primeira execução
└── ai_screen_reader.log # Log detalhado
```

## Pré‑requisitos
* Python ≥ 3.9 (64 bit recomendado)  
* Acesso à internet para baixar modelos da Hugging Face na primeira execução  
* Windows: **VC++ Redistributable 2015‑2022** (necessário para *pyttsx3* e *pywin32*)

## Instalação rápida
```bash
# 1) Crie e ative um ambiente virtual
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS / Linux
source .venv/bin/activate

# 2) Instale as dependências
pip install -r requirements.txt
```
> **Dica:** em máquinas sem GPU ou com \< 4 GB de RAM, edite `ai_screen_reader.ini` após a primeira execução e defina `use_lite_model = true` na seção `[ai]`.

## Configuração inicial
1. Gere um **Access Token** (*Read*) em <https://huggingface.co/settings/tokens>.  
2. Abra `screen-reader.py` e substitua `login("")` pelo seu token.  
3. Execute o leitor uma vez para que `ai_screen_reader.ini` seja criado com valores padrão personalizáveis.

## Como executar
```bash
python screen-reader.py
```

Na inicialização você ouvirá: “Leitor de tela iniciado. Pressione Alt+Ctrl+P para pausar e Alt+Ctrl+Q para sair.”

### Atalhos principais
| Combinação | Ação |
|------------|------|
| **Alt + Ctrl + P** | Pausar / retomar leitura |
| **Alt + Ctrl + Q** | Encerrar o leitor |
| **Alt + Ctrl + → / ←** | Próximo / anterior elemento |
| **Alt + Ctrl + Espaço** | Ler elemento em foco |
| **Alt + Ctrl + A** | Ler todos os elementos da tela |
| **Alt + Ctrl + C** | Descrever elemento sob o cursor |
| **Tab** | Foco nativo; leitor descreve o novo elemento |
| **Navegação estruturada** | Alt + Ctrl + H (cabeçalhos), L (links), R (regiões), F (formulários), T (tabelas) |

## Personalização
* **Modelos de IA** – altere `model_name` ou defina `use_lite_model` em `[ai]`.  
* **Voz e velocidade** – ajuste `voice_id` e `rate` em `[speech]`.  
* **Sensibilidade do OCR** – parâmetros em `[vision]`, por ex. `ocr_confidence`.  
* **Earcons personalizados** – adicione WAVs em `sounds/` e mapeie no código.

## Solução de problemas
| Sintoma | Possível causa | Ação recomendada |
|---------|----------------|------------------|
| “Mecanismo de fala não disponível” | Falha ao iniciar *pyttsx3* | Instalar driver SAPI5 (Win) ou `espeak` (Linux) |
| Modelo cai para CPU | Sem GPU ou pouca RAM | Definir `use_8bit = false` e/ou `use_lite_model = true` |
| OCR não detecta botões pequenos | Resolução ou threshold baixo | Desativar `enhance_small_elements` e elevar `ocr_confidence` |

## Desenvolvimento & contribuição
1. Faça fork e crie branches temáticos.  
2. Siga *PEP 8* e documente o código.  
3. Envie PR com descrição clara.  
4. Ao alterar dependências, atualize `requirements.txt`.

## Licença
Distribuído sob a [MIT License](LICENSE).

---

**Happy hacking & keep it accessible!**
