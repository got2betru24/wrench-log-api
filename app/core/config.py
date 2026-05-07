from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "WrenchLog Auto Maintenance Tracker"
    debug: bool = False

    # Database
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "wrench_log"
    db_user: str = "wrench_log_user"
    db_password: str = ""

    # File storage
    upload_dir: str = "/uploads"
    max_upload_mb: int = 20

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", 
    "http://localhost:3000",
    "http://wrenchlog.local", # Production self-hosted
    ]  

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def database_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
