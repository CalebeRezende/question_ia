import io
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
CORS(app)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"

QWEN_API_KEY = os.getenv("DASHSCOPE_API_KEY")
QWEN_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-max-latest")

client_qwen = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL) if QWEN_API_KEY else None


def get_drive_service():
    """Autentica (via OAuth local) e retorna o serviço do Google Drive."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise RuntimeError(
                    "Arquivo credentials.json não encontrado. Baixe-o no Google Cloud "
                    "Console (Credenciais > ID do cliente OAuth 2.0 > Aplicativo para "
                    "computador) e salve-o na raiz do projeto."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

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


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "qwen_configured": client_qwen is not None})


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
    print("Servidor rodando em http://localhost:5000")
    print("Na primeira execução, uma janela do navegador abrirá para autorizar o Google Drive.")
    app.run(debug=True, port=5000)
