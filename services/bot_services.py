import boto3
import tempfile
import os
import json
import requests
from dotenv import load_dotenv

from langchain_community.document_loaders import PyPDFLoader
from langchain_chroma import Chroma
from langchain_aws import BedrockEmbeddings
from langchain_aws.llms.bedrock import BedrockLLM

load_dotenv()

# 🔐 AWS Credentials
aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
aws_session_token = os.getenv("AWS_SESSION_TOKEN")
aws_region_name=os.getenv("AWS_REGION", "us-east-1")

# 🤖 Modelos
bedrock_llm = BedrockLLM(
    model_id="amazon.titan-text-premier-v1:0",
    region_name=aws_region_name,
    model_kwargs={"temperature": 0.1, "max_tokens": 2000},
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    aws_session_token=aws_session_token,
)

embedding_model = BedrockEmbeddings(
    model_id="amazon.titan-embed-text-v2:0",
    region_name=aws_region_name,
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    aws_session_token=aws_session_token,
)

def send_telegram_response(chat_id, text, bot_token):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

def list_pdfs(bucket_name):
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket_name)

    pdf_keys = []
    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".pdf"):
                pdf_keys.append(key)
    return pdf_keys

def load_pdfs(bucket_name, pdf_keys):
    s3 = boto3.client("s3")
    documents = []

    for key in pdf_keys:
        file_obj = s3.get_object(Bucket=bucket_name, Key=key)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file_obj["Body"].read())
            tmp_path = tmp.name

        loader = PyPDFLoader(tmp_path)
        docs = loader.load()
        documents.extend(docs)

        os.remove(tmp_path)

    return documents

def index_documents(documents, embedding_model, persist_path="chroma_index"):
    os.makedirs(persist_path, exist_ok=True)
    vectorstore = Chroma.from_documents(
        documents=documents,
        embedding=embedding_model,
        persist_directory=persist_path
    )

    return vectorstore

def load_existing_index(path="vetorizados.json"):
    if os.path.exists(path):
        with open(path, "r") as f:
            return set(json.load(f))
    return set()

def save_index(indexed, path="vetorizados.json"):
    with open(path, "w") as f:
        json.dump(list(indexed), f)

def vectorize_new_pdfs(bucket_name, persist_path="chroma_index"):
    all_pdfs = list_pdfs(bucket_name)
    existing_index = load_existing_index()

    new_pdfs = [key for key in all_pdfs if key not in existing_index]
    print(f"Encontrados {len(new_pdfs)} novos PDFs para vetorização.")

    if not new_pdfs:
        print("Nenhum novo PDF encontrado.")
        return

    documents = load_pdfs(bucket_name, new_pdfs)
    vectorstore = index_documents(documents, embedding_model, persist_path)
    save_index(existing_index.union(new_pdfs))
    print("Vetorização concluída.")
    return vectorstore

def generate_rag_response(text, persist_path="chroma_index"):
    vectorstore = Chroma(
        persist_directory=persist_path,
        embedding_function=embedding_model
    )
    print("passou vetorStore ", vectorstore)
    results = vectorstore.as_retriever(search_type="similarity", search_kwargs={"k":3})
    print("passou similaridade")
    if not results:
        return "Não foram encontrados documentos relevantes para responder à pergunta."

    summaries = []
    for i, doc in enumerate(results):
        try:
            resumo = bedrock_llm.invoke(f"Resuma este documento jurídico de forma concisa:\n{doc.page_content[:1000]}")
            summaries.append(resumo)
            print(resumo)
        except Exception as e:
            summaries.append(f"Resumo indisponível para documento {i+1}")

    context = "\n\n".join(summaries)

    prompt = f"""
Você é JusIA, um assistente jurídico especializado em direito brasileiro. Sua função é analisar perguntas enviadas em formato de texto e responder de forma clara, objetiva e fundamentada, utilizando legislação, jurisprudência e doutrina pertinentes. Não reconheço ou processo mídias, documentos ou qualquer formato que não seja texto.

**Instruções para Resposta:**
- Responda de forma assertiva e objetiva.
- Evite divagações e mantenha o foco exclusivamente em questões jurídicas.
- Se a pergunta não se relacionar com o campo jurídico, informe que não pode ajudar.
- Para perguntas vagas ou incompletas, responda: "A pergunta não está clara. Por favor, forneça mais detalhes sobre o que você gostaria de saber."
- Para interações anteriores, responda: "Não tenho acesso a mensagens anteriores. Por favor, reformule sua pergunta."
- Para mal-entendidos, responda: "Parece que houve um mal-entendido. Por favor, forneça mais informações para que eu possa ajudar."

Documentos:
{context}

Pergunta:
{text}

Resposta:
"""

    try:
        response = bedrock_llm.invoke(prompt)
    except Exception as e:
        return f"Erro ao gerar resposta: {str(e)}"

    return response
