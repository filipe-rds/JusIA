from functools import wraps
import time
from services.utils import cloudwatch_logger

def log_execution_time(func):
    """Decorator para logar tempo de execução"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        
        try:
            result = await func(*args, **kwargs)
            end_time = time.time()
            
            # Log de performance
            cloudwatch_logger.log_system_event(
                "function_performance",
                f"Função {func.__name__} executada com sucesso",
                {
                    "execution_time": end_time - start_time,
                    "function_name": func.__name__
                }
            )
            
            return result
            
        except Exception as e:
            end_time = time.time()
            
            cloudwatch_logger.log_error(
                error_type="function_execution_error",
                error_message=str(e),
                context={
                    "function_name": func.__name__,
                    "execution_time": end_time - start_time
                }
            )
            
            raise
    
    return wrapper