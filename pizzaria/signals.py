from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from .utils import sanitize_text
import logging

logger = logging.getLogger(__name__)

@receiver(pre_save, dispatch_uid="pizzaria.sanitize_text_fields")
def sanitize_text_fields(sender, instance, **kwargs):
    if sender._meta.app_label != 'pizzaria':
        return
    for field in instance._meta.get_fields():
        if getattr(field, 'get_internal_type', None) in ('CharField', 'TextField'):
            val = getattr(instance, field.name, None)
            if val is None:
                continue
            try:
                safe = sanitize_text(val, max_length=getattr(field, 'max_length', None))
            except ValidationError as e:
                logger.warning("Sanitize failed %s.%s: %s", sender.__name__, field.name, e)
                safe = str(val)[: getattr(field, 'max_length', None) or 255]
            setattr(instance, field.name, safe)