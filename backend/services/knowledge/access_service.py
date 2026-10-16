"""
The ONLY user-facing entry point into knowledge retrieval.

Authorization reuses CircleAccessService (the same rules as every circle
endpoint): the requester must be an ACTIVE member of the circle, and the
search is then scoped to that single circle. A user can therefore never
retrieve another circle's knowledge, whatever their query says.

Within a circle, every document is visible to its active members: this
mirrors the existing API (shared treasury, contribution status, payouts,
and default-risk probabilities for active members). Documents carry
subject_user so a stricter per-member policy can be added later.
"""

from services.circles.circle_access_service import CircleAccessService
from services.knowledge.retriever import KnowledgeRetriever


class KnowledgeAccessService:

    @staticmethod
    def retrieve_for_user(
        *,
        user,
        circle_id,
        query,
        document_types=None,
        top_k=5,
        retriever=None,
    ):
        """
        Raises CircleNotFound / CircleAccessForbidden (from
        CircleAccessService) before any retrieval happens.
        """
        membership = CircleAccessService.require_active_member(
            circle_id=circle_id,
            user=user,
        )

        retriever = retriever or KnowledgeRetriever()

        return retriever.retrieve(
            query,
            circle_ids={membership.circle_id},
            document_types=document_types,
            top_k=top_k,
        )
