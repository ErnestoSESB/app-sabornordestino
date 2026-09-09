import re
from django.utils.html import strip_tags, escape
from django.core.exceptions import ValidationError
from django.db import models 
import logging
logger = logging.getLogger(__name__)


def sanitize_text(value: str, max_length: int | None = None, allowed_re: str | None = None) -> str:
    v = strip_tags(str(value)).strip()
    if max_length:
        v = v[:max_length]
    if allowed_re and not re.match(allowed_re, v):
        raise ValidationError("Formato inválido")
    return escape(v)

class SanitizedModelMixin:
    def clean(self):
        super_clean = getattr(super(), "clean", None)
        if callable(super_clean):
            super_clean()
        for field in self._meta.get_fields():
            if getattr(field, 'get_internal_type', lambda: None)() in ('CharField', 'TextField'):
                if field.name == 'sabores':
                    continue
                val = getattr(self, field.name, None)
                if val is not None:
                    max_len = getattr(field, 'max_length', None)
                    sanitized = sanitize_text(val, max_length=max_len)
                    setattr(self, field.name, sanitized)

    def save(self, *args, **kwargs):
        try:
            self.full_clean(exclude=None)
        except ValidationError as e:
            logger.warning("Model full_clean failed on %s: %s — aplicando fallback", type(self).__name__, e)
            for field in self._meta.get_fields():
                if getattr(field, 'get_internal_type', lambda: None)() in ('CharField', 'TextField'):
                    if field.name == 'sabores':
                        continue
                    val = getattr(self, field.name, None)
                    if val is not None:
                        setattr(self, field.name, sanitize_text(val, max_length=getattr(field, 'max_length', None)))
        super().save(*args, **kwargs)
