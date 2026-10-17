from decimal import Decimal, ROUND_HALF_UP
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class User(AbstractUser):
    email = models.EmailField(unique=True)
    height_cm = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(50), MaxValueValidator(300)],
    )
    weight_kg = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(20), MaxValueValidator(500)],
    )
    date_of_birth = models.DateField(null=True, blank=True)

    muscle_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(100)],
    )
    body_fat_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(100)],
    )

    @property
    def missing_profile_fields(self):
        fields = ["first_name", "last_name", "date_of_birth", "height_cm", "weight_kg"]
        return [name for name in fields if not getattr(self, name)]

    @property
    def profile_complete(self):
        return not self.missing_profile_fields

    @property
    def bmi(self):
        if self.height_cm and self.weight_kg:
            return (self.weight_kg / (self.height_cm / Decimal(100)) ** 2).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
        return None
