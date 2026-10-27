import io
import json
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from openai import OpenAI

load_dotenv()

app = Flask(__name__)

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5000,http://127.0.0.1:5000,https://caleberezende.github.io",
    ).split(",")
    if origin.strip()
]
CORS(app, origins=ALLOWED_ORIGINS)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"

QWEN_API_KEY = os.getenv("DASHSCOPE_API_KEY")
QWEN_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-max-latest")
QWEN_VL_MODEL = os.getenv("QWEN_VL_MODEL", "qwen-vl-ocr")

client_qwen = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL) if QWEN_API_KEY else None


def get_drive_service():
    """Autentica (via OAuth local, ou via variáveis de ambiente em produção)
    e retorna o serviço do Google Drive.

    Em um host sem navegador (Render/Railway), não é possível abrir a janela
    de autorização. Nesses casos, gere `token.json` uma vez localmente
    (rodando o backend na sua máquina) e cole o conteúdo do arquivo na
    variável de ambiente `GOOGLE_TOKEN_JSON` do serviço hospedado.
    """
    creds = None

    token_json_env = os.getenv("GOOGLE_TOKEN_JSON")
    if token_json_env:
        creds = Credentials.from_authorized_user_info(json.loads(token_json_env), SCOPES)
    elif os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif token_json_env:
            raise RuntimeError(
                "GOOGLE_TOKEN_JSON está definido mas o token expirou e não pôde "
                "ser renovado. Gere um novo token.json localmente e atualize a "
                "variável de ambiente."
            )
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise RuntimeError(
                    "Arquivo credentials.json não encontrado. Baixe-o no Google Cloud "
                    "Console (Credenciais > ID do cliente OAuth 2.0 > Aplicativo para "
                    "computador) e salve-o na raiz do projeto."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        if not token_json_env:
            with open(TOKEN_FILE, "w") as token:
                token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def analisar_com_qwen(texto_editado):
    """Chama a API da Qwen para analisar/formatar o texto. Retorna (resposta, raciocinio)."""
    if client_qwen is None:
        return None, None

    prompt = (
        "Analise e formate o seguinte texto extraído de uma imagem histórica:\n\n"
        f"{texto_editado}"
    )
    response = client_qwen.chat.completions.create(
        model=QWEN_MODEL,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": True},
    )
    mensagem = response.choices[0].message
    return mensagem.content, getattr(mensagem, "reasoning_content", None)


def extrair_texto_da_imagem(imagem_data_url):
    """Envia a imagem (data URL base64) para o modelo de visão da Qwen e
    retorna o texto extraído."""
    if client_qwen is None:
        raise RuntimeError(
            "DASHSCOPE_API_KEY não configurada no servidor. Configure a chave "
            "para habilitar a extração automática de texto da imagem."
        )

    response = client_qwen.chat.completions.create(
        model=QWEN_VL_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": imagem_data_url}},
                    {
                        "type": "text",
                        "text": (
                            "Extraia todo o texto visível nesta imagem, preservando "
                            "quebras de linha e pontuação. Responda apenas com o "
                            "texto extraído, sem comentários adicionais."
                        ),
                    },
                ],
            }
        ],
    )
    return response.choices[0].message.content.strip()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "qwen_configured": client_qwen is not None})


@app.route("/ocr", methods=["POST"])
def ocr():
    data = request.get_json(silent=True) or {}
    imagem_data_url = data.get("imagem")

    if not imagem_data_url or not imagem_data_url.startswith("data:image"):
        return jsonify({"success": False, "error": "Imagem inválida ou ausente."}), 400

    try:
        texto = extrair_texto_da_imagem(imagem_data_url)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({"success": True, "texto": texto})


@app.route("/processar", methods=["POST"])
def processar():
    data = request.get_json(silent=True) or {}
    texto_editado = (data.get("textoCorrigido") or "").strip()
    nome_arquivo = (data.get("nomeArquivo") or "documento.txt").strip() or "documento.txt"
    id_pasta = data.get("idPastaDrive") or None

    if not texto_editado:
        return jsonify({"success": False, "error": "Texto vazio. Edite o texto antes de salvar."}), 400

    if not nome_arquivo.lower().endswith(".txt"):
        nome_arquivo += ".txt"

    try:
        resposta_ia, raciocinio_ia = analisar_com_qwen(texto_editado)
    except Exception as e:
        print(f"Aviso: falha ao chamar a API Qwen: {e}")
        resposta_ia, raciocinio_ia = None, None

    try:
        service = get_drive_service()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    partes = [f"=== TEXTO EDITADO ===\n{texto_editado}"]
    if resposta_ia:
        partes.append(f"=== ANÁLISE DA IA ===\n{resposta_ia}")
    conteudo_final = "\n\n".join(partes)

    file_metadata = {"name": nome_arquivo}
    if id_pasta:
        file_metadata["parents"] = [id_pasta]

    media = MediaIoBaseUpload(
        io.BytesIO(conteudo_final.encode("utf-8")),
        mimetype="text/plain",
        resumable=True,
    )

    try:
        file = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id, webViewLink")
            .execute()
        )
    except Exception as e:
        return jsonify({"success": False, "error": f"Erro ao salvar no Google Drive: {e}"}), 500

    raciocinio_resumido = None
    if raciocinio_ia:
        raciocinio_resumido = (
            raciocinio_ia[:500] + "..." if len(raciocinio_ia) > 500 else raciocinio_ia
        )

    return jsonify(
        {
            "success": True,
            "link": file.get("webViewLink"),
            "raciocinio": raciocinio_resumido
            or "Raciocínio não disponível (DASHSCOPE_API_KEY não configurada ou modelo sem 'thinking').",
            "resposta": resposta_ia
            or "Nenhuma análise de IA foi executada (DASHSCOPE_API_KEY não configurada).",
        }
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"Servidor rodando em http://localhost:{port}")
    print("Na primeira execução, uma janela do navegador abrirá para autorizar o Google Drive.")
    app.run(debug=True, port=port)
