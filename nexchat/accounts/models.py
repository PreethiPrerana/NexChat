from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model — extends AbstractUser so we can add fields
    in Phase 2 (avatar, status) without a migration headache.
    """

    display_name = models.CharField(max_length=60, blank=True)

    class Meta:
        db_table = "accounts_user"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def get_display_name(self) -> str:
        return self.display_name or self.username

    def __str__(self) -> str:
        return self.get_display_name()