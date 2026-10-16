# Questions for legal and compliance review before handling real money

**This is a list of questions for qualified UK legal, regulatory and
compliance advisers. It is not legal advice and reaches no conclusions.**
Osusu must not take real customer money until these are answered in
writing by such advisers, and the answers are reflected in the product and
in provider contracts (`payment-provider-evaluation.md`).

References given as starting points (fetched 2026-10-15):
FCA PS25/12, changes to the safeguarding regime for payments and e-money
firms; the new CASS 15 rules apply from 7 May 2026
([policy statement](https://www.fca.org.uk/publications/policy-statements/ps25-12-changes-safeguarding-regime-payments-and-e-money-firms),
[CASS 15](https://handbook.fca.org.uk/handbook/cass15)).
The Payment Services Regulations 2017 list money remittance as a payment
service ([FCA approach document](https://www.fca.org.uk/publication/finalised-guidance/fca-approach-payment-services-electronic-money-2017.pdf)).

## 1. Legal structure of the savings circle

1. What is a circle in law: a contract between members, an unincorporated
   association, a trust, or a service Osusu provides to each member? Who
   are the contracting parties?
2. Does the arrangement, or Osusu's role in it, fall within any regulated
   activity: payment services (e.g. money remittance), e-money issuance,
   deposit taking, consumer credit (members who receive the pool early are
   effectively advanced money by later members), collective investment
   schemes, or anything else? Do any exclusions or exemptions apply?
3. Does it matter that the recipient is chosen by member vote (current
   design) rather than by lot or fixed rotation? Could any selection method
   raise lottery or gambling questions?
4. What happens legally when a member who has already received the pool
   stops contributing? Who bears the loss: the other members, Osusu, or a
   reserve? Is it a debt, and who may collect it?
5. Are the constitution and voting rules enforceable as written? What
   disclosures and terms must members accept before joining?

## 2. Who holds and controls funds

6. Between a contribution and the payout, whose money is it, and who
   legally holds it: Osusu, a regulated provider, the members jointly?
7. Must Osusu be FCA-authorised or registered (e.g. as a payment or
   e-money institution, or as an agent of one), or can a regulated
   provider hold the funds so that Osusu never receives or controls them?
   What exactly must Osusu not do in that model?
8. If funds are held by Osusu or on its behalf, do the safeguarding
   requirements apply (PSRs/EMRs and the new CASS 15 rules from 7 May
   2026), including segregation, reconciliation, audit and resolution
   packs?
9. Who may instruct a payout? Today the app requires member votes,
   quorum and the circle creator's approval. Is that a sufficient
   authorisation of each payment, and how must consent and strong customer
   authentication be evidenced?
10. What happens to funds if Osusu stops operating or the provider fails?

## 3. Customer verification and financial crime

11. Which customer due diligence must be done, by whom (Osusu or provider),
    and at what point: before contributing, before receiving, above
    thresholds?
12. Do the Money Laundering Regulations 2017 apply to Osusu directly, and
    is registration with a supervisor required?
13. Sanctions screening, fraud monitoring, suspicious activity reporting:
    who is responsible, and what must the product support (holds, freezes,
    information requests)?
14. Confirmation of Payee and authorised push payment (APP) fraud
    reimbursement: how do they apply to payouts to members, and who bears
    reimbursement costs?
15. Can Osusu's risk scores (trust, member risk, circle health) be used in
    onboarding decisions? Under the architecture rules they never approve or
    block money movement. Any fairness or explainability duties?

## 4. Consumer protection, complaints, disputes and refunds

16. Does the FCA Consumer Duty or other conduct regulation apply? What
    fair-value and communications obligations follow?
17. Complaints handling: is Osusu within the Financial Ombudsman Service's
    jurisdiction? What procedure and timescales are required?
18. Refund rights: a member leaving early, a circle dissolving, mistaken or
    unauthorised payments, chargebacks or Direct Debit indemnity claims on
    contributions after a payout has been made. What must Osusu do, and
    who bears the loss?
19. What information must members see before each payment and in
    statements?

## 5. Records, data and tax

20. Retention periods for ledger, audit, identity and payment records
    (financial crime rules and others), and how they fit with UK GDPR
    erasure requests. The ledger is append-only by design.
21. Is personal data shared with payment providers appropriately covered
    (controller/processor roles, international transfers)?
22. Tax treatment for members and for Osusu's fees. Any reporting
    obligations?

## 6. Treasury ownership and independent review

23. Who is the named treasury owner accountable for reconciliations,
    corrections (`record_ledger_correction`) and incident decisions? Who
    deputises?
24. What independent financial review or audit is required before launch
    and periodically (e.g. safeguarding audits where applicable)?
25. What insurance (professional indemnity, crime/fidelity) is required or
    advisable?
26. What are the launch limits (circle size, contribution amount, number of
    circles, geography: UK residents and GBP only) until controls are
    proven?

## Outcome needed

A written opinion covering 1–26 that names the permitted operating model.
Then provider selection and contracts, then the payout design in
`payout-uncertain-outcomes.md`, then sandbox tests and an independent
review before any real transaction.
