"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { IconDeviceFloppy, IconLoader2, IconUpload } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { MfaSecuritySection } from "@/components/auth/mfa-security-section";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";
import { getUserMeta } from "@/lib/auth";
import { useCurrentUser, useProjectSummaries } from "@/lib/ui/use-shell-data";
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";

const FALLBACK_USER: CurrentUser = {
  name: "",
  email: "",
  role: "",
  tenantName: "",
  initials: "··",
};
const FALLBACK_TENANT: TenantSummary = {
  name: "Tablescope",
  slug: "",
  initials: "TS",
};

const ACCEPTED_AVATAR_TYPES = "image/png,image/jpeg,image/webp";
const MAX_AVATAR_BYTES = 5 * 1024 * 1024;

export default function ProfilePage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: identity } = useCurrentUser();
  const { data: allProjects } = useProjectSummaries();

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [displayName, setDisplayName] = useState("");
  const [dirty, setDirty] = useState(false);
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  useEffect(() => {
    if (!dirty && identity?.user) setDisplayName(identity.user.name);
  }, [identity?.user, dirty]);

  const saveMutation = useMutation({
    mutationFn: (name: string) =>
      apiClient.patch("/api/users/me", { display_name: name }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      setDirty(false);
      setSavedNote("Profile updated.");
    },
  });

  const avatarMutation = useMutation({
    mutationFn: (file: File) => apiClient.upload("/api/users/me/avatar", file),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    },
    onError: (err: Error) => setAvatarError(err.message),
  });

  function onAvatarSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarError("Image too large (max 5 MB).");
      return;
    }
    setAvatarError(null);
    avatarMutation.mutate(file);
  }

  return (
    <AppShell
      mode="home"
      activeNav="home"
      tenant={tenant}
      user={user}
      counts={{ projects: allProjects?.length }}
      topBarLeft={<span className="text-[15px] text-ink-secondary">Profile</span>}
    >
      <div className="mx-auto w-full max-w-xl space-y-6 py-8">
        <h1 className="text-h1 text-ink-primary">Your profile</h1>

        <section className="rounded-lg border border-line-tertiary bg-bg-primary p-5">
          <div className="flex items-center gap-4">
            <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full bg-brand-50 text-h2 font-semibold text-brand-700">
              {user.avatarUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={user.avatarUrl}
                  alt=""
                  className="h-full w-full object-cover"
                />
              ) : (
                <span>{user.initials}</span>
              )}
            </div>
            <div className="min-w-0">
              <input
                type="file"
                accept={ACCEPTED_AVATAR_TYPES}
                ref={fileInputRef}
                onChange={onAvatarSelected}
                className="hidden"
              />
              <Button
                variant="secondary"
                size="md"
                onClick={() => fileInputRef.current?.click()}
                disabled={avatarMutation.isPending}
              >
                {avatarMutation.isPending ? (
                  <IconLoader2 size={14} className="animate-spin" />
                ) : (
                  <IconUpload size={14} />
                )}
                {user.avatarUrl ? "Change picture" : "Upload picture"}
              </Button>
              <p className="mt-1.5 text-caption text-ink-tertiary">
                PNG, JPG or WebP, up to 5 MB.
              </p>
              {avatarError && (
                <p className="mt-1 text-small text-danger">{avatarError}</p>
              )}
            </div>
          </div>
        </section>

        <section className="space-y-4 rounded-lg border border-line-tertiary bg-bg-primary p-5">
          <div>
            <label className="mb-1 block text-small font-medium text-ink-secondary">
              Display name
            </label>
            <input
              value={displayName}
              onChange={(e) => {
                setDisplayName(e.target.value);
                setDirty(true);
                setSavedNote(null);
              }}
              className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="mb-1 text-small font-medium text-ink-secondary">
                Email
              </div>
              <div className="truncate text-[13px] text-ink-tertiary">
                {user.email}
              </div>
            </div>
            <div>
              <div className="mb-1 text-small font-medium text-ink-secondary">
                Role
              </div>
              <div className="text-[13px] text-ink-tertiary">
                {user.role} · {user.tenantName}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Button
              variant="primary"
              size="md"
              onClick={() => saveMutation.mutate(displayName.trim())}
              disabled={
                saveMutation.isPending || !dirty || !displayName.trim()
              }
            >
              {saveMutation.isPending ? (
                <IconLoader2 size={14} className="animate-spin" />
              ) : (
                <IconDeviceFloppy size={14} />
              )}
              Save changes
            </Button>
            {savedNote && (
              <span className="text-small text-success">{savedNote}</span>
            )}
            {saveMutation.isError && (
              <span className="text-small text-danger">
                {(saveMutation.error as Error).message}
              </span>
            )}
          </div>
        </section>

        <MfaSecuritySection />
      </div>
    </AppShell>
  );
}
