from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./onboarding.db"
    log_level: str = "INFO"
    app_name: str = "erp-banking-onboarding-api"
    auth0_domain: str = ""
    auth0_audience: str = ""
    cors_origins: list[str] = ["http://localhost:5173"]
    port: int = 8081


settings = Settings()
