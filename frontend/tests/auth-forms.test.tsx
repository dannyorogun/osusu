import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "@/components/auth/LoginForm";
import { RegisterForm, validateRegistration } from "@/components/auth/RegisterForm";
import { osusu } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/errors";

import { USER } from "./helpers";
import { router } from "./router";

const login = vi.fn();

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ login }),
}));

vi.mock("@/lib/api/endpoints", () => ({
  osusu: { users: { register: vi.fn() } },
}));

const register = vi.mocked(osusu.users.register);

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

beforeEach(() => {
  login.mockReset();
  register.mockReset();
});

describe("LoginForm", () => {
  it("validates required fields without calling the API", async () => {
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Enter your username.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
  });

  it("signs in and follows a safe next path", async () => {
    login.mockResolvedValue(USER);
    render(<LoginForm next="/circles/abc" />);
    type("Username", " ada ");
    type("Password", "correct horse");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/circles/abc"));
    expect(login).toHaveBeenCalledWith({ username: "ada", password: "correct horse" });
  });

  it("refuses open redirects", async () => {
    login.mockResolvedValue(USER);
    render(<LoginForm next="//evil.example/steal" />);
    type("Username", "ada");
    type("Password", "pw");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows invalid credentials and clears the password", async () => {
    login.mockRejectedValue(new ApiError(401));
    render(<LoginForm />);
    type("Username", "ada");
    type("Password", "wrong");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("don't match");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("shows a friendly message for network/API failures", async () => {
    login.mockRejectedValue(new ApiError(0));
    render(<LoginForm />);
    type("Username", "ada");
    type("Password", "pw");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't reach Osusu");
  });
});

describe("RegisterForm", () => {
  function fill(overrides: Partial<Record<string, string>> = {}) {
    const values = {
      "First name": "Ada",
      "Last name": "Obi",
      Email: "ada@example.com",
      Username: "ada",
      Password: "long enough",
      ...overrides,
    };
    for (const [label, value] of Object.entries(values)) type(label, value ?? "");
  }

  it("validates email, username and the backend's password length", () => {
    expect(validateRegistration({
      email: "nope", username: "", first_name: "", last_name: "", password: "short",
    })).toEqual({
      email: "Enter a valid email address.",
      username: "Choose a username.",
      password: "Use at least 8 characters.",
    });
  });

  it("blocks a weak password before calling the API", async () => {
    render(<RegisterForm />);
    fill({ Password: "1234567" });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Use at least 8 characters.")).toBeInTheDocument();
    expect(register).not.toHaveBeenCalled();
  });

  it("registers, signs in and goes to the dashboard", async () => {
    register.mockResolvedValue({ email: "ada@example.com", username: "ada", first_name: "Ada", last_name: "Obi" });
    login.mockResolvedValue(USER);
    render(<RegisterForm />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/dashboard"));
    expect(register).toHaveBeenCalledWith({
      email: "ada@example.com", username: "ada", first_name: "Ada", last_name: "Obi",
      password: "long enough",
    });
    expect(login).toHaveBeenCalledWith({ username: "ada", password: "long enough" });
  });

  it("shows duplicate email and username errors from the backend", async () => {
    register.mockRejectedValue(new ApiError(400, {
      email: ["user with this email already exists."],
      username: ["A user with that username already exists."],
    }));
    render(<RegisterForm />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("user with this email already exists.")).toBeInTheDocument();
    expect(screen.getByText("A user with that username already exists.")).toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
  });

  it("shows network errors", async () => {
    register.mockRejectedValue(new ApiError(0));
    render(<RegisterForm />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't reach Osusu");
  });

  it("falls back to the login page if auto sign-in fails", async () => {
    register.mockResolvedValue({ email: "a@b.co", username: "ada", first_name: "", last_name: "" });
    login.mockRejectedValue(new ApiError(503));
    render(<RegisterForm />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login?registered=1"));
  });
});
