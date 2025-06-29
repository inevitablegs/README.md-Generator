from django.db import models

# Create your models here.
from django.db import models
from django.core.validators import URLValidator

class Repository(models.Model):
    url = models.URLField(
        max_length=255,
        validators=[URLValidator()],
        unique=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    readme_content = models.TextField(blank=True)
    language_stats = models.JSONField(default=dict, blank=True)
    topics = models.JSONField(default=list, blank=True)
    
    def __str__(self):
        return self.url
    
    class Meta:
        verbose_name_plural = "Repositories"
        ordering = ['-created_at']