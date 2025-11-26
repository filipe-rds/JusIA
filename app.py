from flask import Flask, jsonify, request
import os
from dotenv import load_dotenv
from rich import print_json
import json
import time
from datetime import datetime

from services.bot_services import (
    send_telegram_response,
    embedding_model,
    vectorize_new_pdfs,
    generate_rag_response,
    bedrock_llm
)

from services.utils.cloudwatch_logger import cloudwatch_logger

load_dotenv()

bot_token = os.getenv("BOT_TOKEN")
bucket_name = os.getenv("BUCKET_NAME")
persist_path = "./chroma_index"

app = Flask(__name__)

# Middleware para log de todas as requisições
@app.before_request
def log_request():
    if request.path != '/favicon.ico':  # Ignorar favicon
        cloudwatch_logger.log_system_event(
            "http_request_start",
            f"Requisição recebida: {request.method} {request.path}",
            {
                "path": request.path,
                "method": request.method,
                "remote_addr": request.remote_addr,
                "user_agent": request.user_agent.string
            }
        )

@app.after_request
def log_response(response):
    if request.path != '/favicon.ico':
        cloudwatch_logger.log_system_event(
            "http_request_complete",
            f"Resposta enviada: {response.status_code}",
            {
                "path": request.path,
                "method": request.method,
                "status_code": response.status_code,
                "response_size": response.calculate_content_length()
            }
        )
    return response

@app.errorhandler(Exception)
def handle_error(error):
    cloudwatch_logger.log_error(
        error_type="flask_error",
        error_message=str(error),
        stack_trace=str(error.__traceback__),
        context={
            "path": request.path,
            "method": request.method,
            "remote_addr": request.remote_addr
        }
    )
    return jsonify({"error": "Internal Server Error"}), 500

@app.route("/")
def index():
    cloudwatch_logger.log_system_event(
        "root_access",
        "Acesso à raiz do servidor",
        {"client_ip": request.remote_addr}
    )
    
    return jsonify({
        "status": "Servidor Flask está rodando!",
        "webhook": "/webhook"
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    start_time = time.time()
    
    try:
        data = request.get_json()
        cloudwatch_logger.log_system_event(
            "webhook_received",
            "Webhook do Telegram recebido",
            {
                "data_type": str(type(data)),
                "has_text": "text" in data.get("message", {}) if data else False
            }
        )

        print(type(data))
        print_json(data=data)
        
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text")
        user_id = data["message"]["from"]["id"]
        username = data["message"]["from"].get("username", "unknown")

        if not text:
            cloudwatch_logger.log_system_event(
                "empty_message",
                "Mensagem vazia recebida",
                {"chat_id": chat_id, "user_id": user_id}
            )
            
            send_telegram_response(chat_id, "Por favor, envie uma mensagem de texto.", bot_token)
            return "OK", 200

        cloudwatch_logger.log_query(
            user_id=user_id,
            query=text,
            response_time=0,  
            success=True,
            additional_context={
                "username": username,
                "chat_id": chat_id,
                "message_length": len(text)
            }
        )

        print(f"Mensagem recebida de {chat_id}: {text}")

        # Processar a consulta RAG
        rag_start_time = time.time()
        llm_response = generate_rag_response(text=text)
        rag_time = time.time() - rag_start_time

        cloudwatch_logger.log_system_event(
            "rag_processed",
            "Consulta RAG processada",
            {
                "processing_time": rag_time,
                "response_length": len(llm_response),
                "user_id": user_id
            }
        )

        # Enviar resposta para o Telegram
        send_telegram_response(chat_id=chat_id, text=llm_response, bot_token=bot_token)

        total_time = time.time() - start_time
        
        # Atualizar log da consulta com tempo total
        cloudwatch_logger.log_query(
            user_id=user_id,
            query=text,
            response_time=total_time,
            success=True,
            additional_context={
                "rag_processing_time": rag_time,
                "total_processing_time": total_time,
                "response_length": len(llm_response)
            }
        )

        return "OK", 200

    except Exception as e:
        total_time = time.time() - start_time
        error_message = str(e)
        
        cloudwatch_logger.log_error(
            error_type="webhook_processing_error",
            error_message=error_message,
            stack_trace=str(e.__traceback__),
            context={
                "processing_time": total_time,
                "data_received": str(data)[:500] if 'data' in locals() else "No data"
            }
        )

        # Tentar enviar mensagem de erro se chat_id estiver disponível
        try:
            if 'chat_id' in locals():
                send_telegram_response(
                    chat_id=chat_id, 
                    text="Desculpe, ocorreu um erro ao processar sua mensagem.", 
                    bot_token=bot_token
                )
        except Exception as send_error:
            cloudwatch_logger.log_error(
                error_type="error_message_send_failed",
                error_message=str(send_error),
                context={"original_error": error_message}
            )

        return "OK", 200  # Sempre retornar OK para o Telegram

def initialize_chroma_index():
    """Função para inicializar o índice Chroma com logging"""
    try:
        cloudwatch_logger.log_system_event(
            "chroma_init_start",
            "Iniciando verificação do índice Chroma",
            {"persist_path": persist_path}
        )
        
        if not os.path.exists(persist_path) or len(os.listdir(persist_path)) == 0:
            cloudwatch_logger.log_system_event(
                "chroma_index_not_found",
                "Nenhum índice encontrado. Iniciando vetorização...",
                {"bucket_name": bucket_name}
            )
            
            print("Nenhum índice encontrado. Iniciando vetorização...")
            start_time = time.time()
            
            vectorize_new_pdfs(bucket_name, persist_path)
            
            processing_time = time.time() - start_time
            cloudwatch_logger.log_rag_operation(
                operation_type="initial_vectorization",
                document_count="unknown",  
                processing_time=processing_time,
                documents={"bucket": bucket_name}
            )
            
            cloudwatch_logger.log_system_event(
                "chroma_index_created",
                "Índice Chroma criado com sucesso",
                {"processing_time": processing_time}
            )
        else:
            cloudwatch_logger.log_system_event(
                "chroma_index_found",
                "Embeddings já existentes. Pulando vetorização.",
                {"persist_path": persist_path}
            )
            print("Embeddings já existentes. Pulando vetorização.")
            
    except Exception as e:
        cloudwatch_logger.log_error(
            error_type="chroma_init_error",
            error_message=str(e),
            stack_trace=str(e.__traceback__),
            context={
                "bucket_name": bucket_name,
                "persist_path": persist_path
            }
        )
        raise

if __name__ == '__main__':
    # Log de inicialização da aplicação
    cloudwatch_logger.log_system_event(
        "application_start",
        "Servidor Flask iniciando",
        {
            "port": 5000,
            "debug": True,
            "bucket_name": bucket_name
        }
    )
    
    # Inicializar índice Chroma
    initialize_chroma_index()
    
    cloudwatch_logger.log_system_event(
        "server_starting",
        "Servidor Flask iniciando na porta 5000",
        {"status": "ready"}
    )
    
    app.run(host='0.0.0.0',debug=True, port=5000)