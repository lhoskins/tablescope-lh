from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_url: str = "http://ollama:11434"
    qdrant_url: str = "http://qdrant:6333"
    tablescope_app_url: str = "http://localhost:8000"
    ai_signing_secret: str = ""
    idle_timeout_minutes: int = 60
    data_mount: str = "/mnt/tablescope-ai"

    # Default AI policies
    cross_project_enabled: bool = False
    tenant_scope_enabled: bool = False

    # Model routing
    sql_model: str = "qwen2.5-coder:7b"
    reasoning_model: str = "llama3.1:8b"
    embedding_model: str = "nomic-embed-text"

    class Config:
        env_file = ".env"


settings = Settings()
