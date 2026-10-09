"""Runtime configuration; secrets are injected by Modal, never committed."""

import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Settings:
    model: str = "gpt-4o-mini"
    monthly_budget_eur: Decimal = Decimal("15")
    input_usd_per_million: Decimal = Decimal("0.15")
    output_usd_per_million: Decimal = Decimal("0.60")
    eur_per_usd: Decimal = Decimal("1.10")
    max_output_tokens: int = 512
    cooldown_seconds: int = 15
    max_input_chars: int = 4000
    history_messages: int = 12
    history_bytes: int = 16000

    def __post_init__(self):
        for value in (
            self.monthly_budget_eur,
            self.input_usd_per_million,
            self.output_usd_per_million,
            self.eur_per_usd,
        ):
            if not value.is_finite() or value <= 0:
                raise ValueError("Budgets, prices and exchange rates must be finite and positive")
        if not 1 <= self.max_output_tokens <= 1024:
            raise ValueError("MAX_OUTPUT_TOKENS must be between 1 and 1024")
        if self.cooldown_seconds < 1:
            raise ValueError("COOLDOWN_SECONDS must be positive")

    @classmethod
    def from_env(cls):
        model = os.getenv("CHAT_MODEL", "gpt-4o-mini")
        if model != "gpt-4o-mini" and not all(
            key in os.environ for key in ("INPUT_USD_PER_MILLION", "OUTPUT_USD_PER_MILLION")
        ):
            raise ValueError("Set both token prices when changing CHAT_MODEL")
        return cls(
            model=model,
            monthly_budget_eur=Decimal(os.getenv("MONTHLY_BUDGET_EUR", "15")),
            input_usd_per_million=Decimal(os.getenv("INPUT_USD_PER_MILLION", "0.15")),
            output_usd_per_million=Decimal(os.getenv("OUTPUT_USD_PER_MILLION", "0.60")),
            eur_per_usd=Decimal(os.getenv("EUR_PER_USD", "1.10")),
            max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "512")),
            cooldown_seconds=int(os.getenv("COOLDOWN_SECONDS", "15")),
        )
