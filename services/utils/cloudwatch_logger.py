import logging
import boto3
from watchtower import CloudWatchLogHandler
import json
from datetime import datetime
import os
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

class CloudWatchLogger:
    def __init__(self, log_group_name, log_stream_name, region_name='us-east-1'):
        self.log_group_name = log_group_name
        self.log_stream_name = log_stream_name
        self.region_name = region_name
        
        # Configurar cliente CloudWatch Logs
        self.client = boto3.client('logs', region_name=region_name)
        
        # Verificar se o log group existe, se não, criar
        self._ensure_log_group_exists()
        
        # Configurar logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        # Remover handlers existentes para evitar duplicação
        if self.logger.handlers:
            self.logger.handlers.clear()
        
        # Configurar CloudWatch handler
        self.handler = CloudWatchLogHandler(
            log_group_name=log_group_name,
            log_stream_name=log_stream_name,
            boto3_client=self.client
        )
        
        # Formato do log
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.handler.setFormatter(formatter)
        
        self.logger.addHandler(self.handler)
    
    def _ensure_log_group_exists(self):
        """Verifica se o log group existe, caso contrário cria"""
        try:
            self.client.describe_log_groups(logGroupNamePrefix=self.log_group_name)
        except self.client.exceptions.ResourceNotFoundException:
            self.client.create_log_group(logGroupName=self.log_group_name)
    
    def log_query(self, user_id, query, response_time, success=True, error_message=None, additional_context=None):
        """Log de consultas do usuário"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "query": query,
            "response_time": response_time,
            "success": success,
            "error_message": error_message,
            "type": "query",
            "additional_context": additional_context 
        }
        
        self.logger.info(json.dumps(log_data))

    
    def log_system_event(self, event_type, message, additional_data=None):
        """Log de eventos do sistema"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "message": message,
            "additional_data": additional_data or {},
            "type": "system"
        }
        
        self.logger.info(json.dumps(log_data))
    
    def log_error(self, error_type, error_message, stack_trace=None, context=None):
        """Log de erros"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "error_type": error_type,
            "error_message": error_message,
            "stack_trace": stack_trace,
            "context": context or {},
            "type": "error"
        }
        
        self.logger.error(json.dumps(log_data))
    
    def log_rag_operation(self, operation_type, document_count, processing_time, documents=None):
        """Log de operações RAG"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "operation_type": operation_type,
            "document_count": document_count,
            "processing_time": processing_time,
            "documents": documents or [],
            "type": "rag_operation"
        }
        
        self.logger.info(json.dumps(log_data))

# Instância global do logger
cloudwatch_logger = CloudWatchLogger(
    log_group_name=os.getenv("LOG_GROUP_NAME", "JusIA-chatbot-logs"),
    log_stream_name=f"chatbot-stream-{datetime.utcnow().strftime('%Y-%m-%d')}",
    region_name=os.getenv("AWS_REGION", "us-east-1")
)