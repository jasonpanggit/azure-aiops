"use client";

import { useEffect, useRef, useState } from "react";
import { useMsal } from "@azure/msal-react";
import { isMsalConfigured, signOut } from "@/lib/auth";

/** Two-letter monogram from a display name or username, for the avatar. */
function initialsFor(label: string): string {
  const words = label
    .replace(/[<>()"']/g, " ")
    .split(/[\s@._-]+/)
    .filter(Boolean);
  if (words.length === 0) return "OP";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0]}${words[1][0]}`.toUpperCase();
}

/**
 * Signed-in operator avatar with a sign-out action.
 *
 * Replaces the previously hard-coded "OP" monogram, which showed the same
 * placeholder for every user and offered no way to sign out at all — leaving
 * a stale session recoverable only by manually clearing browser storage.
 */
export function AccountMenu() {
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click or Escape, so the menu never strands itself open
  // over the page content.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!isMsalConfigured) {
    return (
      <div className="shell-avatar" aria-label="Development mode (no sign-in configured)" title="Development mode">
        DEV
      </div>
    );
  }

  return <SignedInAccountMenu
    open={open}
    setOpen={setOpen}
    signingOut={signingOut}
    setSigningOut={setSigningOut}
    containerRef={containerRef}
  />;
}

function SignedInAccountMenu({
  open,
  setOpen,
  signingOut,
  setSigningOut,
  containerRef,
}: {
  open: boolean;
  setOpen: (value: boolean) => void;
  signingOut: boolean;
  setSigningOut: (value: boolean) => void;
  containerRef: React.MutableRefObject<HTMLDivElement | null>;
}) {
  const { accounts } = useMsal();
  const account = accounts[0];
  const displayName = account?.name || account?.username || "Signed-in operator";
  const username = account?.username ?? "";

  return (
    <div className="shell-account" ref={containerRef}>
      <button
        type="button"
        className="shell-avatar shell-avatar-button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${displayName}`}
        title={displayName}
        onClick={() => setOpen(!open)}
      >
        {initialsFor(displayName)}
      </button>
      {open && (
        <div className="shell-account-menu" role="menu">
          <div className="shell-account-identity">
            <strong>{displayName}</strong>
            {username && username !== displayName && <span>{username}</span>}
          </div>
          <button
            type="button"
            role="menuitem"
            className="shell-account-action"
            disabled={signingOut}
            onClick={() => {
              setSigningOut(true);
              void signOut();
            }}
          >
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
      )}
    </div>
  );
}
