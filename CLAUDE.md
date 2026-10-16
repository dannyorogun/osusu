# Osusu AI Development Charter

You are contributing to Osusu, an AI-assisted community banking platform built with production-quality architecture.

## Tech Stack

Backend
- Python 3.14
- Django
- Django REST Framework
- PostgreSQL

Frontend
- React
- Tailwind CSS

Future
- Open Banking
- RAG
- LLM explanations
- Machine Learning
- Cloud deployment

## Architecture Principles

Never replace deterministic financial logic with AI.

AI may:
- generate explanations
- assess risk

- recommend restructuring
- detect fraud patterns

AI may NOT:
- approve payouts
- move money
- override treasury rules
- override governance votes

## Financial Principles

Always preserve:
- atomic transactions
- idempotency
- immutable ledger
- audit logs

Never duplicate:
- payments
- payouts
- webhook processing

## Existing Systems

Already implemented:
- Authentication
- Circles
- Constitution
- Invitations
- Circle Formation Engine
- Financial Lock
- Contribution Engine
- Treasury Engine
- Ledger
- Payment abstraction
- Webhook processing
- Payout foundation
- Trust Graph
- Circle Health
- Circle Risk
- Member Risk
- Feature Snapshots
- Risk Outcomes
- Dataset Builder

## Coding Style

- Use service-layer architecture.
- Keep business logic inside `services/`.
- Use Django transactions for financial operations.
- Prefer `get_or_create()` where idempotency is required.
- Write tests for every major service.
- Keep imports organized.
- Do not remove existing functionality unless explicitly instructed.