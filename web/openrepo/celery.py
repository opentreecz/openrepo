"""Celery application configuration for OpenRepo."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openrepo.settings")

app = Celery("openrepo")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
