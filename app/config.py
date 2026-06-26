from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str
    telegram_allowed_user_ids: str = ""

    database_url: str = "postgresql+asyncpg://lombard:lombard@postgres:5432/lombard"
    site_base_url: str = "https://lombard-perspectiva.ru"

    scan_interval_hours: int = 6
    request_delay_seconds: float = 1.5

    report_daily_hour: int = 9
    report_weekly_day: int = 0
    report_monthly_day: int = 1
    timezone: str = "Europe/Moscow"

    @property
    def allowed_user_ids(self) -> list[int]:
        return [int(item.strip()) for item in self.telegram_allowed_user_ids.split(",") if item.strip()]


settings = Settings()
