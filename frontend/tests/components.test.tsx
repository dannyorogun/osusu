import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { LoadingBlock, Spinner } from "@/components/ui/Spinner";
import { Alert, EmptyState, ErrorState, StatCard } from "@/components/ui/Surface";
import { Table } from "@/components/ui/Table";

describe("Button", () => {
  it("fires clicks when enabled", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Save</Button>);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("is disabled and busy while loading", () => {
    const onClick = vi.fn();
    render(
      <Button loading loadingText="Saving" onClick={onClick}>
        Save
      </Button>,
    );
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveTextContent("Saving");
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("defaults to type=button so it never submits forms by accident", () => {
    render(<Button>Plain</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
  });
});

describe("Input", () => {
  it("links the label and shows an accessible error", () => {
    render(<Input label="Email" error="Enter a valid email address." />);
    const input = screen.getByLabelText("Email");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Enter a valid email address.");
  });

  it("shows the hint when there is no error", () => {
    render(<Input label="Username" hint="You'll sign in with this." />);
    expect(screen.getByLabelText("Username")).toHaveAccessibleDescription("You'll sign in with this.");
  });
});

describe("feedback states", () => {
  it("spinner and loading block announce loading", () => {
    render(
      <>
        <Spinner label="Loading circles" />
        <LoadingBlock label="Loading profile" />
      </>,
    );
    expect(screen.getAllByRole("status")).toHaveLength(2);
    expect(screen.getByText("Loading circles")).toBeInTheDocument();
  });

  it("error state renders the message and retries", () => {
    const retry = vi.fn();
    render(<ErrorState message="We couldn't reach Osusu." onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("We couldn't reach Osusu.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
  });

  it("danger alerts are announced as alerts", () => {
    render(<Alert tone="danger">Nope</Alert>);
    expect(screen.getByRole("alert")).toHaveTextContent("Nope");
  });

  it("empty state explains what to do next", () => {
    render(<EmptyState title="Nothing here" description="Create one." action={<button>Go</button>} />);
    expect(screen.getByText("Create one.")).toBeInTheDocument();
  });

  it("stat card never invents a value", () => {
    render(<StatCard label="Next payout" value={null} />);
    expect(screen.getByText("Not available yet")).toBeInTheDocument();
    expect(screen.queryByText(/£/)).not.toBeInTheDocument();
  });
});

describe("Modal", () => {
  it("renders a labelled dialog and closes on Escape", () => {
    const onClose = vi.fn();
    render(
      <Modal open title="Accept an invitation" onClose={onClose}>
        body
      </Modal>,
    );
    expect(screen.getByRole("dialog", { name: "Accept an invitation" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("renders nothing when closed", () => {
    render(<Modal open={false} title="Hidden" onClose={() => {}}>x</Modal>);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("Table", () => {
  it("renders headers and rows", () => {
    render(
      <Table
        caption="Members"
        rowKey={(row: { id: string; name: string }) => row.id}
        columns={[{ key: "name", header: "Name", render: (row) => row.name }]}
        rows={[{ id: "1", name: "Ada" }]}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Ada" })).toBeInTheDocument();
  });
});
