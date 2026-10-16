from circles.models import CircleInvitation


class TrustGraphEngine:

    @staticmethod
    def edges(circle):

        invitations = CircleInvitation.objects.filter(
            circle=circle,
        )

        return [
            {
                "from": invite.inviter.id,
                "to": invite.email,
                "status": invite.status,
            }
            for invite in invitations
        ]