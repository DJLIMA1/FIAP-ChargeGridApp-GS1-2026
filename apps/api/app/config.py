from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://localhost/chargegrid"
    migration_database_url: str | None = None
    supabase_url: str = "https://example.supabase.co"
    supabase_anon_key: str = ""
    cors_origins: list[str] = []
    # Assistente de IA (OpenRouter). A chave existe somente no backend.
    openrouter_api_key: str = ""
    openrouter_model: str = "deepseek/deepseek-v4.1-flash"
    openrouter_fallback_models: str = "anthropic/claude-haiku-5.5,qwen/qwen3.7-flash"
    openrouter_reasoning_effort: str = "low"
    openrouter_site_url: str = "https://github.com/DJLIMA1/FIAP-ChargeGridApp-GS1-2026"
    ai_enabled: bool = True
    # Atualização do APK: manifesto público no Vercel Blob (tools/release_apk.py o publica).
    app_manifest_url: str = "https://9x2lhsbjqbuqehzd.public.blob.vercel-storage.com/app/latest.json"
    # Pagamentos Stripe em MODO TESTE. A chave secreta existe somente no backend (env da Vercel);
    # chave que não seja de teste (sk_test_/rk_test_) desliga os pagamentos.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Métodos ativos no Dashboard da Stripe (informativo para o app): "card" ou "card,pix".
    stripe_methods: str = "card"
    # URL pública desta API (retorno da Checkout e QR do painel). Nunca chargegrid-api.vercel.app.
    public_base_url: str = ""
    payments_start_window_minutes: int = 15
    payments_kiosk_start_minutes: int = 10
    # Environment variables supplied by Vercel or the shell take precedence over
    # this optional local-development file.
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")


@lru_cache
def settings():
    return Settings()
