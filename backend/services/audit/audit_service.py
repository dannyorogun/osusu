from audit.models import AuditLog


class AuditService:

    @staticmethod
    def record(
        *,
        action,
        entity_type,
        entity_id=None,
        user=None,
        metadata=None,
    ):
        return AuditLog.objects.create(
            user=user,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else "",
            metadata=metadata or {},
        )