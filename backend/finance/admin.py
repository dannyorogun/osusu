from django.contrib import admin

from .models import LedgerTransaction, PayoutAttempt


@admin.register(LedgerTransaction)
class LedgerTransactionAdmin(admin.ModelAdmin):
    """
    View only. The ledger is append-only: rows are written by LedgerService
    and corrected by LedgerCorrectionService (OPERATIONS.md), never edited
    or deleted here.
    """

    list_display = (
        "transaction_type",
        "circle",
        "member",
        "amount",
        "status",
        "period_number",
    )

    list_filter = (
        "transaction_type",
        "status",
    )

    search_fields = (
        "reference",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PayoutAttempt)
class PayoutAttemptAdmin(admin.ModelAdmin):
    """
    View only. Attempt states change only through
    services.payouts.payout_attempt_service, from provider evidence.
    """

    list_display = (
        "payout",
        "attempt_number",
        "state",
        "provider",
        "provider_reference",
        "created_at",
    )

    list_filter = (
        "state",
        "provider",
    )

    search_fields = (
        "idempotency_key",
        "provider_reference",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
