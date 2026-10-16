/**
 * Typed wrappers for the Django endpoints the frontend consumes. Each one
 * exists in the backend today; see API_CONTRACT.md. The backend decides
 * every financial value and every permission - nothing here computes or
 * authorizes anything.
 */

import type { AssistantAnswer } from "@/types/assistant";
import type {
  AcceptInvitationResponse,
  ActivityEvent,
  Circle,
  CircleMember,
  ConstitutionAccepted,
  CreateCircleRequest,
  FinancialLockResult,
  FormationEvaluation,
  InvitationCreated,
  MyCircle,
  TreasurySummary,
  TrustSummary,
} from "@/types/circle";
import type {
  CirclePayouts,
  CurrentPayoutWindow,
  MyObligation,
  Obligation,
  PaymentIntent,
  PayoutWindowActionResult,
} from "@/types/payment";
import type { RegisterRequest, RegisterResponse, User } from "@/types/user";

import type { ApiClient } from "./client";
import { api as defaultApi } from "./index";

const id = (value: string) => encodeURIComponent(value);

export function endpoints(client: ApiClient = defaultApi) {
  return {
    users: {
      register: (data: RegisterRequest) =>
        client.post<RegisterResponse>("/api/users/register/", data, {
          anonymous: true,
        }),
      me: () => client.get<User>("/api/users/me/"),
      /** The requester's own obligations across their ACTIVE circles. */
      obligations: () => client.get<MyObligation[]>("/api/users/me/obligations/"),
    },

    circles: {
      /** Circles where the requester is an ACTIVE member. */
      list: () => client.get<MyCircle[]>("/api/circles/"),
      create: (data: CreateCircleRequest) =>
        client.post<Circle>("/api/circles/", data),
      get: (circleId: string) =>
        client.get<Circle>(`/api/circles/${id(circleId)}/`),
      acceptInvitation: (token: string) =>
        client.post<AcceptInvitationResponse>(
          `/api/circles/invitations/${id(token)}/accept/`,
        ),
      members: (circleId: string) =>
        client.get<CircleMember[]>(`/api/circles/${id(circleId)}/members/`),
      /** The requester's own obligations only. */
      obligations: (circleId: string) =>
        client.get<Obligation[]>(`/api/circles/${id(circleId)}/obligations/`),
      payouts: (circleId: string) =>
        client.get<CirclePayouts>(`/api/circles/${id(circleId)}/payouts/`),
      treasury: (circleId: string) =>
        client.get<TreasurySummary>(`/api/circles/${id(circleId)}/treasury/`),
      activity: (circleId: string) =>
        client.get<ActivityEvent[]>(`/api/circles/${id(circleId)}/activity/`),
      trust: (circleId: string) =>
        client.get<TrustSummary>(`/api/circles/${id(circleId)}/trust/`),

      // Circle workflow actions. Each one is decided entirely by Django;
      // the frontend only reports what the backend returned.
      /** Any ACTIVE member, while the circle is recruiting. */
      invite: (circleId: string, email: string) =>
        client.post<InvitationCreated>(`/api/circles/${id(circleId)}/invite/`, { email }),
      acceptConstitution: (circleId: string) =>
        client.post<ConstitutionAccepted>(
          `/api/circles/${id(circleId)}/accept-constitution/`,
        ),
      /** Creator only. A passing evaluation sets status "ready". */
      evaluate: (circleId: string) =>
        client.post<FormationEvaluation>(`/api/circles/${id(circleId)}/evaluate/`),
      /** Creator only. Irreversible; Django re-checks every requirement. */
      lock: (circleId: string) =>
        client.post<FinancialLockResult>(`/api/circles/${id(circleId)}/lock/`),
    },

    // Payout governance. Eligibility, quorum, funds and idempotency are
    // enforced by Django's payout services; nothing is decided here.
    payoutWindows: {
      current: (circleId: string) =>
        client.get<CurrentPayoutWindow>(`/api/circles/${id(circleId)}/payout-windows/`),
      /** Creator only; the server picks the window number. */
      open: (circleId: string) =>
        client.post<PayoutWindowActionResult>(`/api/circles/${id(circleId)}/payout-windows/`),
      vote: (circleId: string, window: number, candidateId: string) =>
        client.post<PayoutWindowActionResult>(
          `/api/circles/${id(circleId)}/payout-windows/${window}/vote/`,
          { candidate_id: candidateId },
        ),
      /** Creator only; refused (400) until the constitution's quorum is met. */
      approve: (circleId: string, window: number) =>
        client.post<PayoutWindowActionResult>(
          `/api/circles/${id(circleId)}/payout-windows/${window}/approve/`,
        ),
      /** Creator only. Repeating it after success never pays twice. */
      execute: (circleId: string, window: number) =>
        client.post<PayoutWindowActionResult>(
          `/api/circles/${id(circleId)}/payout-windows/${window}/execute/`,
        ),
    },

    assistant: {
      /** 503 while the backend readiness gate keeps the assistant off. */
      ask: (circleId: string, question: string) =>
        client.post<AssistantAnswer>(
          `/api/circles/${id(circleId)}/assistant/`,
          { question },
        ),
    },

    payments: {
      /**
       * Starts a provider payment for the caller's own obligation. It does
       * NOT mark anything paid: completion comes only from the provider's
       * webhook, processed by the backend.
       */
      create: (obligationId: string) =>
        client.post<PaymentIntent>(
          `/api/payments/obligations/${id(obligationId)}/create/`,
        ),
    },
  };
}

export const osusu = endpoints();
