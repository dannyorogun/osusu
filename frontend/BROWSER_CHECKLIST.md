# Manual browser verification: circle and payout journey

No browser automation is set up in this repository. Sprint 30's checks
were automated over HTTP and in Vitest, not in a browser. Use this list to
verify the same journey by hand.

## Setup

```bash
cd backend && venv/bin/python manage.py runserver 127.0.0.1:8000
cd frontend && npm run dev            # http://localhost:3000
```

Use two browser profiles (or one normal and one private window) so the
creator and the member each have their own session cookie.

## Journey

1. **Register and log in** two accounts, A (creator) and B (member).
   A weak password such as `password123` must be refused on the form.
2. **Create a circle as A**: member limit 2, contribution 50.00 weekly,
   payout 200.00 biweekly, cycle 4, quorum 100.
3. **Invite B as A** (circle → Set up → Invite). Copy the code that is shown.
   As B, use My circles → *Accept an invitation* and paste the code.
4. **Constitution and formation.** As A and as B, use Set up → *Accept the
   constitution*. As A, run *Run formation checks*; every check is ✓ and the
   status badge shows Ready.
5. **Lock as A.** Choose *Financially lock the circle*, then confirm. The
   status shows Financially locked.
6. **Fund the treasury.** There is no contribution UI yet. In a shell:

   ```bash
   cd backend && venv/bin/python manage.py shell -c "
   from decimal import Decimal; from circles.models import Circle
   from finance.models import TransactionType
   from services.finance.ledger_service import LedgerService
   c = Circle.objects.get(name='<your circle name>')
   for m in c.memberships.all():
       LedgerService.record_transaction(circle=c, member=m.user,
           transaction_type=TransactionType.CONTRIBUTION, amount=Decimal('125.00'),
           period_number=1, payment_reference=f'manual-{c.id}-{m.user_id}')"
   ```

   Treasury tab shows £250.00.
7. **Open the payout view.** As A: Payouts → *Open the next payout window*.
   B sees the window with no open button.
8. **Unauthorized access.** Open the circle URL as a third account C.
   It must show *Circle not available*.
9. **Vote.** As B, vote for B. The panel shows *1 of 2 required votes cast*
   and B's vote. The vote buttons disappear for B.
10. **Quorum.** As A, *Approve the window* must fail with *Quorum not
    reached: 1 of 2 required votes.* A then votes for B and approves. The
    badge shows Approved, not yet paid.
11. **Execute.** As A, choose *Pay out*, then confirm. Only after the response
    arrives does the panel show Paid with a paid date. The Treasury tab shows
    £50.00.
12. **Retry.** Run the execute request again, for example with
    `curl -X POST .../payout-windows/1/execute/` and A's token, or by
    resubmitting it from the browser devtools Network tab. The response is
    `already_paid`. Then run `venv/bin/python manage.py
    report_ledger_anomalies`: it reports *No anomalies found.*, and the
    Treasury tab still shows £50.00.
13. **Log out** as A. In devtools, the `osusu_refresh` cookie is gone.
    Replaying the old cookie value against `/api/session/refresh` returns
    401.

## Staging variant (payouts disabled)

Run against staging (backend/OPERATIONS.md, "Staging") from an allowed
address, with test accounts only. Differences from the journey above:
there is no shell funding step unless an operator funds a **test** circle
on the staging database with the step-6 command (run with the staging
environment loaded), and execution must be refused.

Record every row as Passed / Failed / Blocked / Not tested, with the
date, browser and tester. Do not mark a row Passed from HTTP or unit
tests: those are listed separately in the sprint report.

| # | Step | Expected | Result |
|---|---|---|---|
| S1 | Register A with a strong password | Signed in, dashboard shown | |
| S2 | Register with `password123` | Refused on the form, password not echoed | |
| S3 | Log out, log in as A | Dashboard; devtools: `osusu_refresh` cookie is HttpOnly, Secure, SameSite=Strict | |
| S4 | Six wrong passwords for one username | 6th shows "Too many requests. Please wait a moment and try again." | |
| S5 | Create circle (journey step 2), invite B, B accepts | B sees the circle | |
| S6 | Both accept constitution; A runs formation checks; A locks | Ready, then Financially locked | |
| S7 | Members, Obligations, Treasury, Activity tabs (A and B) | Each loads; Treasury shows balance; Activity lists events | |
| S8 | Outsider C opens the circle URL | "Circle not available" | |
| S9 | A opens a payout window (after test funding) | Window open; B sees no open button | |
| S10 | B votes; A tries to approve | "Quorum not reached: 1 of 2 required votes." | |
| S11 | A votes, approves | Approved, not yet paid | |
| S12 | A chooses Pay out, confirms | "Payouts are not enabled on this server yet. Nothing was paid."; still Approved; Treasury balance unchanged | |
| S13 | Operator: `report_ledger_anomalies`; payout rows for the circle | No anomalies; no PAYOUT ledger row | |
| S14 | Log out A; replay old cookie to `/api/session/refresh` | Cookie gone; replay -> 401 | |
| S15 | Phone width (375 px) and desktop for each page above | No horizontal scroll; buttons reachable; errors readable | |
| S16 | Stop Django briefly and reload a page | Friendly "couldn't reach" / unavailable message, no raw error | |
