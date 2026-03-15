import os

class Settings:
    fastapi_host = os.getenv('FASTAPI_HOST', '0.0.0.0')
    fastapi_port = int(os.getenv('FASTAPI_PORT', '8080'))

settings = Settings()
