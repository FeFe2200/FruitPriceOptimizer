import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    session_secret: str
    credential_key: str
    admin_username: str
    admin_password: str
    secure_cookies: bool
    scrape_timeout_ms: int

    @classmethod
    def from_env(cls) -> "Settings":
        required = {
            "DATABASE_URL": os.getenv("DATABASE_URL"),
            "SESSION_SECRET": os.getenv("SESSION_SECRET"),
            "CREDENTIAL_KEY": os.getenv("CREDENTIAL_KEY"),
            "ADMIN_PASSWORD": os.getenv("ADMIN_PASSWORD"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"필수 환경변수가 없습니다: {', '.join(missing)}")
        return cls(
            database_url=required["DATABASE_URL"] or "",
            session_secret=required["SESSION_SECRET"] or "",
            credential_key=required["CREDENTIAL_KEY"] or "",
            admin_username=os.getenv("ADMIN_USERNAME", "admin"),
            admin_password=required["ADMIN_PASSWORD"] or "",
            secure_cookies=os.getenv("SECURE_COOKIES", "false").lower() == "true",
            scrape_timeout_ms=int(os.getenv("SCRAPE_TIMEOUT_MS", "30000")),
        )


settings = Settings.from_env()
