# OCR Qwen + Google Drive

Interface web para editar um texto extraído de uma imagem (OCR), enviá-lo para
análise pela API da Qwen e salvar o resultado como arquivo `.txt` no Google
Drive.

O navegador (`index.html`) não roda Python nem acessa o Google Drive
diretamente, então a ponte é feita por um servidor Flask local
(`backend.py`), que:

1. recebe o texto editado pelo navegador;
2. (opcional) envia o texto para a API da Qwen para análise/formatação;
3. salva o texto final no Google Drive via OAuth 2.0.

## 1. Instalar dependências

```bash
cd qwen-ocr-drive
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configurar o Google Drive

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/), crie
   um projeto e ative a **Google Drive API**.
2. Em "Credenciais", crie um **ID de Cliente OAuth 2.0** do tipo
   **Aplicativo para computador**.
3. Baixe o JSON gerado e salve-o como `credentials.json` dentro desta pasta
   (`qwen-ocr-drive/credentials.json`).

Na primeira execução do `backend.py`, uma janela do navegador abrirá pedindo
para você fazer login e autorizar o acesso. Isso gera automaticamente o
arquivo `token.json`, reutilizado nas próximas execuções.

## 3. Configurar a API da Qwen

Copie `.env.example` para `.env` e preencha sua chave:

```bash
cp .env.example .env
```

```
DASHSCOPE_API_KEY=sua_chave_aqui
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-max-latest
```

Ajuste `DASHSCOPE_BASE_URL` e `QWEN_MODEL` conforme a região/modelo da sua
conta DashScope. Se `DASHSCOPE_API_KEY` não for configurada, o servidor ainda
funciona — ele salva o texto direto no Drive, apenas sem a etapa de análise
por IA.

## 4. Rodar o servidor

```bash
python backend.py
```

O servidor sobe em `http://localhost:5000`.

## 5. Abrir a interface

Abra `index.html` diretamente no navegador (duplo clique ou
`file:///.../qwen-ocr-drive/index.html`). Edite o texto, informe o nome do
arquivo e, opcionalmente, o ID da pasta de destino no Drive, depois clique em
**"Processar com IA e salvar no Google Drive"**.

O link do arquivo salvo aparece na tela ao final do processo.

## Arquivos

| Arquivo             | Descrição                                               |
| -------------------- | -------------------------------------------------------- |
| `backend.py`         | Servidor Flask: autenticação com o Drive e chamada à Qwen |
| `index.html`         | Interface para editar o texto e disparar o salvamento    |
| `requirements.txt`   | Dependências Python                                      |
| `.env.example`       | Modelo de variáveis de ambiente                           |

`credentials.json` e `token.json` **não** devem ser commitados — já estão no
`.gitignore`.
