import type { IsoDateTime, Uuid } from "./api";

/** GET /api/users/me/ (users.serializers.UserSerializer). */
export type User = {
  id: Uuid;
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  is_verified: boolean;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
};

/** POST /api/users/register/ request (users.serializers.RegisterSerializer). */
export type RegisterRequest = {
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  /** Backend rule: at least 8 characters. */
  password: string;
};

/** POST /api/users/register/ 201 response (password is write-only). */
export type RegisterResponse = Omit<RegisterRequest, "password">;

/**
 * POST /api/auth/login/ request (SimpleJWT TokenObtainPairView).
 * The backend authenticates by USERNAME (Django's default USERNAME_FIELD);
 * email login is not supported.
 */
export type LoginRequest = {
  username: string;
  password: string;
};
