from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    rabbitmq_url: str = "amqp://guest:guest@192.168.1.50:5672/"
    minio_endpoint: str = "192.168.1.50:9000"
    minio_access_key: str = "comfyops"
    minio_secret_key: str = "comfyops"
    minio_bucket: str = "comfyops-images"
    redis_url: str = "redis://192.168.1.50:6379/0"
    job_queue: str = "generation-jobs"
    result_ttl_seconds: int = 86400

    class Config:
        env_file = ".env"
        env_prefix = "COMFYOPS_"


settings = Settings()