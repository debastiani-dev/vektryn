from django.conf import settings
from django.db import IntegrityError, models, transaction

from apps.base.models.base_model import BaseModel


class PreferredCurrency(models.TextChoices):
    USD = "USD", "US Dollar (USD)"
    BRL = "BRL", "Brazilian Real (BRL)"
    EUR = "EUR", "Euro (EUR)"
    GBP = "GBP", "British Pound (GBP)"


class CopilotToneChoice(models.TextChoices):
    BALANCED = "balanced", "Balanced"
    CONCISE = "concise", "Concise"
    EXECUTIVE = "executive", "Executive"
    TECHNICAL = "technical", "Technical"
    CONVERSATIONAL = "conversational", "Conversational"


class PreferredGeminiModelChoice(models.TextChoices):
    AUTO = "auto", "Auto (Recommended)"
    GEMINI_4_CARBON = "gemini-4-carbon", "Gemini 4 Carbon"
    GEMINI_4_NEON = "gemini-4-neon", "Gemini 4 Neon"
    GEMINI_4_ARGON = "gemini-4-argon", "Gemini 4 Argon"
    GEMINI_4_HYDROGEN = "gemini-4-hydrogen", "Gemini 4 Hydrogen"
    GEMINI_3_8_FLASH = "gemini-3.8-flash", "Gemini 3.8 Flash"
    GEMINI_3_5_FLASH_LITE = "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite"


class UserProfile(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    display_name = models.CharField(max_length=120, blank=True, default="")
    timezone = models.CharField(max_length=64, default="UTC")
    preferred_currency = models.CharField(
        max_length=3,
        choices=PreferredCurrency.choices,
        default=PreferredCurrency.USD,
    )
    default_copilot_tone = models.CharField(
        max_length=24,
        choices=CopilotToneChoice.choices,
        default=CopilotToneChoice.BALANCED,
    )
    linkedin_url = models.URLField(max_length=300, blank=True, default="")
    github_url = models.URLField(max_length=300, blank=True, default="")
    portfolio_url = models.URLField(max_length=300, blank=True, default="")
    gemini_api_key_encrypted = models.TextField(blank=True, default="")
    gemini_api_key_last4 = models.CharField(max_length=4, blank=True, default="")
    preferred_gemini_model = models.CharField(
        max_length=48,
        choices=PreferredGeminiModelChoice.choices,
        default=PreferredGeminiModelChoice.AUTO,
    )
    allow_model_fallback = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def has_gemini_api_key(self) -> bool:
        return bool((self.gemini_api_key_encrypted or "").strip())

    def __str__(self) -> str:
        return f"UserProfile<{self.user_id}>"


def get_or_create_user_profile(user) -> UserProfile:
    """Lazily provision a UserProfile using an inner savepoint for race safety."""
    try:
        with transaction.atomic():
            profile, _ = UserProfile.all_objects.get_or_create(user=user)
    except IntegrityError:
        profile = UserProfile.all_objects.get(user=user)
    if profile.is_deleted:
        profile.restore()
    return profile
