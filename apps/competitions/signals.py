from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from .models import SeasonComponent, Season
from .rule_validation import validate_dependency_graph


@receiver(m2m_changed, sender=SeasonComponent.depends_on.through)
def prevent_cycles(sender, instance, action, reverse, pk_set, **kwargs):
    if action != "pre_add" or not pk_set:
        return
    # M2M operations run in an atomic block. Serialize same-season graph mutations.
    Season.objects.select_for_update().get(pk=instance.season_id)
    if reverse:
        additions = {pk: {instance.pk} for pk in pk_set}
    else:
        additions = {instance.pk: set(pk_set)}
    validate_dependency_graph(instance.season_id, additions=additions)
