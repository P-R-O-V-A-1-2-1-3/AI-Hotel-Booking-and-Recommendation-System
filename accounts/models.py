from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class EmailUserManager(UserManager):
    """Users sign in with email; username is set to the email automatically."""

    def _create_user(self, username, email, password, **extra_fields):
        email = self.normalize_email(email)
        return super()._create_user(username or email, email, password, **extra_fields)

    def create_user(self, email=None, password=None, **extra_fields):
        return super().create_user(extra_fields.pop('username', None), email, password, **extra_fields)

    def create_superuser(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', User.Role.ADMIN)
        return super().create_superuser(extra_fields.pop('username', None), email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        TRAVELER = 'traveler', 'Traveler'
        OWNER = 'owner', 'Hotel Owner'
        ADMIN = 'admin', 'Admin'

    class Language(models.TextChoices):
        EN = 'EN', 'English'
        BN = 'BN', 'Bangla'

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.TRAVELER)
    preferred_language = models.CharField(max_length=2, choices=Language.choices, default=Language.EN)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = EmailUserManager()

    def save(self, *args, **kwargs):
        # username is unique but unused (we log in by email); keep it filled for every creation path
        if not self.username:
            self.username = self.email
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email
