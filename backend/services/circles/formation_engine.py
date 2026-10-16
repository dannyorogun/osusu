from decimal import Decimal

from circles.models import (
    CircleStatus,
    MembershipStatus,
)


class FormationResult:
    def __init__(self, passed, checks):
        self.passed = passed
        self.checks = checks

    def __bool__(self):
        return self.passed


class CircleFormationEngine:

    @staticmethod
    def validate(circle):

        checks = {}

        # --------------------------------------------------
        # 1. Constitution exists
        # --------------------------------------------------

        try:
            constitution = circle.constitution
            checks["constitution_exists"] = True
        except Exception:
            checks["constitution_exists"] = False
            return FormationResult(False, checks)

        # --------------------------------------------------
        # 2. Active members
        # --------------------------------------------------

        members = circle.memberships.filter(
            status=MembershipStatus.ACTIVE
        )

        member_count = members.count()

        checks["minimum_members"] = member_count >= 2

        # --------------------------------------------------
        # 3. Member limit
        # --------------------------------------------------

        checks["member_limit"] = (
            member_count <= constitution.member_limit
        )

        # --------------------------------------------------
        # 4. Constitution acceptance
        # --------------------------------------------------

        unaccepted_members = members.filter(
            constitution_accepted=False
        ).exists()

        checks["constitution_accepted"] = not unaccepted_members

        # --------------------------------------------------
        # 5. Contribution amount
        # --------------------------------------------------

        checks["contribution_valid"] = (
            constitution.contribution_amount > Decimal("0")
        )

        # --------------------------------------------------
        # 6. Payout amount
        # --------------------------------------------------

        checks["payout_valid"] = (
            constitution.payout_amount > Decimal("0")
        )

        # --------------------------------------------------
        # 7. Cycle length
        # --------------------------------------------------

        checks["cycle_length_valid"] = (
            constitution.cycle_length >= member_count
        )

        # --------------------------------------------------
        # 8. Quorum
        # --------------------------------------------------

        checks["quorum_valid"] = (
            1 <= constitution.quorum_percentage <= 100
        )

        # --------------------------------------------------
        # 9. Reserve
        # --------------------------------------------------

        if constitution.reserve_enabled:
            checks["reserve_valid"] = (
                constitution.reserve_amount >= Decimal("0")
            )
        else:
            checks["reserve_valid"] = True

        # --------------------------------------------------
        # Overall result
        # --------------------------------------------------

        passed = all(checks.values())

        return FormationResult(
            passed=passed,
            checks=checks,
        )