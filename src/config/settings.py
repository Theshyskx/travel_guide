import os
from pathlib import Path
from dotenv import load_dotenv

class Config:
    def __init__(self, env_path=None):
        if env_path is None:
            env_path = Path(__file__).parent.parent.parent / '.env'
        load_dotenv(env_path)
        
        self.SERVER_HOST = os.getenv('SERVER_HOST', '0.0.0.0')
        self.SERVER_PORT = int(os.getenv('SERVER_PORT', 8081))
        
        self.DB_HOST = os.getenv('DB_HOST', 'localhost')
        self.DB_PORT = int(os.getenv('DB_PORT', 3306))
        self.DB_USER = os.getenv('DB_USER', 'root')
        self.DB_PASSWORD = os.getenv('DB_PASSWORD', '')
        self.DB_NAME = os.getenv('DB_NAME', 'travel')
        
        self.SESSION_TIMEOUT = int(os.getenv('SESSION_TIMEOUT', 1800))
        
        self.OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
        self.OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL', '')
        self.MODEL_NAME = os.getenv('MODEL_NAME', 'glm-4-flash')
        self.EMBEDDING_MODEL_PATH = os.getenv('EMBEDDING_MODEL_PATH', '')
        self.VECTOR_STORE_PATH = os.getenv('VECTOR_STORE_PATH', 'chroma_db')
        
        self.LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
        self.LOG_DIR = os.getenv('LOG_DIR', 'logs')
    
    def get_db_url(self):
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    def get_model_config(self):
        return {
            'model_type': 'openai',
            'config_name': 'glm_model',
            'model': self.MODEL_NAME,
            'api_key': self.OPENAI_API_KEY,
            'base_url': self.OPENAI_BASE_URL,
        }

config = Config()
