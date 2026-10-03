from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Dev defaults target localhost Docker services; the Asus k3s cluster
    # overrides these via env vars (COMFYOPS_*) in production.
    rabbitmq_url: str = "amqp://guest:guest@127.0.0.1:5672/"
    rabbitmq_mgmt_url: str = "http://guest:guest@127.0.0.1:15672/"
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "comfyops"
    minio_secret_key: str = "comfyops"
    minio_bucket: str = "comfyops-images"
    redis_url: str = "redis://127.0.0.1:6379/0"
    job_queue: str = "generation-jobs"
    result_ttl_seconds: int = 86400

    class Config:
        env_file = ".env"
        env_prefix = "COMFYOPS_"


settings = Settings()