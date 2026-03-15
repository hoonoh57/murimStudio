import os


class Settings:
    fastapi_host: str = os.getenv('FASTAPI_HOST', '0.0.0.0')
    fastapi_port: int = int(os.getenv('FASTAPI_PORT', '8080'))
    claude_api_key: str = os.getenv('CLAUDE_API_KEY', '')
    elevenlabs_api_key: str = os.getenv('ELEVENLABS_API_KEY', '')
    youtube_api_key: str = os.getenv('YOUTUBE_API_KEY', '')
    midjourney_api_url: str = os.getenv('MIDJOURNEY_API_URL', '')
    db_path: str = os.getenv('DB_PATH', 'app.db')
    storage_secret: str = os.getenv('STORAGE_SECRET', 'change-me')
    monthly_budget_usd: float = float(os.getenv('MONTHLY_BUDGET_USD', '200'))


settings = Settings()
