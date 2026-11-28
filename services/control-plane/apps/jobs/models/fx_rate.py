from django.db import models
from django.db.models import Q

from apps.base.models.base_model import TimestampsOnlyBaseModel


class FxRate(TimestampsOnlyBaseModel):
    currency_code = models.CharField(max_length=3, unique=True)
    units_per_usd = models.DecimalField(max_digits=18, decimal_places=8)
    source = models.CharField(max_length=32, default="static_fallback")
    as_of_date = models.DateField()

    class Meta:
        ordering = ["currency_code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(units_per_usd__gt=0),
                name="ck_fx_rate_units_per_usd_gt_zero",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.currency_code}={self.units_per_usd} ({self.source}, {self.as_of_date})"
