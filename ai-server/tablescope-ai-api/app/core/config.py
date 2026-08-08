from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_url: str = "http://ollama:11434"
    qdrant_url: str = "http://qdrant:6333"
    tablescope_app_url: str = "http://localhost:8000"
    # When True, refuse to build AI context if the platform-api permission
    # service is unreachable (fail closed) rather than proceeding with an empty,
    # ungrounded context. Set False only for local development.
    require_app_server: bool = True
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

    # Voice transcription (CPU-based faster-whisper by default)
    voice_transcription_enabled: bool = False
    voice_transcription_model: str = "tiny"  # faster-whisper model size or path
    voice_transcription_device: str = "cpu"
    voice_transcription_compute_type: str = "int8"
    voice_transcription_beam_size: int = 5
    voice_transcription_model_path: str = ""  # optional local path; empty = download
    voice_max_duration_seconds: int = 120
    voice_max_upload_bytes: int = 20 * 1024 * 1024

    class Config:
        env_file = ".env"


settings = Settings()
