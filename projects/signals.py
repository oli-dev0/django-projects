from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .image_services import schedule_image_file_cleanup
from .models import ProjectImage


@receiver(pre_delete, sender=ProjectImage)
def schedule_project_image_cleanup(sender, instance, **kwargs):
    schedule_image_file_cleanup(instance)
