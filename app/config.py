from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./onboarding.db"
    log_level: str = "INFO"
    app_name: str = "erp-banking-onboarding-api"


settings = Settings()
