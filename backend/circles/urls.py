from django.urls import path

from .views import (
    CreateCircleView,
    CircleDetailView,
    EvaluateFormationView,
    FinancialLockView,
    AcceptConstitutionView,
    CreateInvitationView,
    AcceptInvitationView,
    CircleMembersView,
    MyObligationsView,
    CirclePayoutsView,
    CircleTreasuryView,
    CircleActivityView,
    CircleTrustView,
    PayoutWindowsView,
    PayoutWindowDetailView,
    PayoutVoteView,
    PayoutApproveView,
    PayoutExecuteView,
)


urlpatterns = [
    path(
        "",
        CreateCircleView.as_view(),
        name="create-circle",
    ),

    path(
        "<uuid:circle_id>/",
        CircleDetailView.as_view(),
        name="circle-detail",
    ),

    path(
        "<uuid:circle_id>/evaluate/",
        EvaluateFormationView.as_view(),
        name="circle-evaluate",
    ),

    path(
        "<uuid:circle_id>/lock/",
        FinancialLockView.as_view(),
        name="circle-lock",
    ),
    path(
        "<uuid:circle_id>/accept-constitution/",
        AcceptConstitutionView.as_view(),
        name="accept-constitution",
),  
    path(
        "<uuid:circle_id>/invite/",
        CreateInvitationView.as_view(),
        name="create-invitation",
),

    path(
        "invitations/<str:token>/accept/",
        AcceptInvitationView.as_view(),
        name="accept-invitation",
),

    path(
        "<uuid:circle_id>/members/",
        CircleMembersView.as_view(),
        name="circle-members",
    ),

    path(
        "<uuid:circle_id>/obligations/",
        MyObligationsView.as_view(),
        name="circle-obligations",
    ),

    path(
        "<uuid:circle_id>/payouts/",
        CirclePayoutsView.as_view(),
        name="circle-payouts",
    ),

    path(
        "<uuid:circle_id>/treasury/",
        CircleTreasuryView.as_view(),
        name="circle-treasury",
    ),

    path(
        "<uuid:circle_id>/activity/",
        CircleActivityView.as_view(),
        name="circle-activity",
    ),

    path(
        "<uuid:circle_id>/trust/",
        CircleTrustView.as_view(),
        name="circle-trust",
    ),

    path(
        "<uuid:circle_id>/payout-windows/",
        PayoutWindowsView.as_view(),
        name="payout-windows",
    ),

    path(
        "<uuid:circle_id>/payout-windows/<int:window>/",
        PayoutWindowDetailView.as_view(),
        name="payout-window",
    ),

    path(
        "<uuid:circle_id>/payout-windows/<int:window>/vote/",
        PayoutVoteView.as_view(),
        name="payout-window-vote",
    ),

    path(
        "<uuid:circle_id>/payout-windows/<int:window>/approve/",
        PayoutApproveView.as_view(),
        name="payout-window-approve",
    ),

    path(
        "<uuid:circle_id>/payout-windows/<int:window>/execute/",
        PayoutExecuteView.as_view(),
        name="payout-window-execute",
    ),
]
