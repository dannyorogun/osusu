"""
HTTP adapter for CircleAccessService: maps domain access errors to DRF
exceptions so every circle-scoped view responds identically.
"""

from contextlib import contextmanager

from rest_framework.exceptions import NotFound, PermissionDenied

from services.circles.circle_access_service import (
    CircleAccessForbidden,
    CircleAccessService,
    CircleMemberNotFound,
    CircleNotFound,
)


@contextmanager
def _as_http_errors():
    try:
        yield
    except (CircleNotFound, CircleMemberNotFound) as exc:
        raise NotFound(str(exc)) from exc
    except CircleAccessForbidden as exc:
        raise PermissionDenied(str(exc)) from exc


def authorize_member(request, circle_id):
    """ACTIVE member of the circle; returns their membership."""
    with _as_http_errors():
        return CircleAccessService.require_active_member(
            circle_id=circle_id,
            user=request.user,
        )


def authorize_creator(request, circle_id):
    """Creator (and ACTIVE member) of the circle; returns membership."""
    with _as_http_errors():
        return CircleAccessService.require_creator(
            circle_id=circle_id,
            user=request.user,
        )


def get_active_target_member(circle_id, member_id):
    """ACTIVE member of the circle being acted upon; returns membership."""
    with _as_http_errors():
        return CircleAccessService.require_active_target_member(
            circle_id=circle_id,
            member_id=member_id,
        )
