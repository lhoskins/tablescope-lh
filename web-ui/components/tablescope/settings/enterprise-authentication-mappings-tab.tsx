"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useToasts } from "@/components/ui/toast";
import {
  confirmIdentityMapping,
  getIdentityMappings,
  rejectIdentityMapping,
  type IdentityMapping,
} from "@/lib/api/enterprise-auth";
import { Button, GhostButton, Input, Section } from "./enterprise-authentication-shared";

export function IdentityMappingsTab() {
  const queryClient = useQueryClient();
  const { push } = useToasts();
  const { data: mappings } = useQuery<IdentityMapping[]>({
    queryKey: ["enterprise-auth", "identity-mappings"],
    queryFn: getIdentityMappings,
  });
  const [userIds, setUserIds] = useState<Record<number, string>>({});

  const confirmMutation = useMutation({
    mutationFn: ({ id, userId }: { id: number; userId: number }) => confirmIdentityMapping(id, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["enterprise-auth", "identity-mappings"] });
      push("Identity mapping confirmed", "success");
    },
    onError: (err: unknown) => push(err instanceof Error ? err.message : "Confirm failed", "error"),
  });

  const rejectMutation = useMutation({
    mutationFn: rejectIdentityMapping,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["enterprise-auth", "identity-mappings"] });
      push("Identity mapping rejected", "success");
    },
    onError: (err: unknown) => push(err instanceof Error ? err.message : "Reject failed", "error"),
  });

  return (
    <Section title="Identity Mappings" description="Review and confirm external SSO/LDAP identities linked to TableScope users.">
      {mappings?.length ? (
        <ul className="divide-y divide-line-secondary">
          {mappings.map((m) => (
            <li key={m.id} className="py-3 text-sm">
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-medium text-ink-primary">{m.external_subject}</span>
                  <span className="ml-2 rounded bg-bg-secondary px-2 py-0.5 text-ink-primary">{m.provider_type}</span>
                  <span className="ml-2 text-ink-tertiary">State: {m.verification_state}</span>
                </div>
                <div className="flex gap-2">
                  <Input
                    type="number"
                    placeholder="User ID"
                    className="w-24"
                    value={userIds[m.id] ?? ""}
                    onChange={(e) => setUserIds((ids) => ({ ...ids, [m.id]: e.target.value }))}
                  />
                  <Button
                    onClick={() => confirmMutation.mutate({ id: m.id, userId: parseInt(userIds[m.id] || String(m.user_id), 10) })}
                    className="py-1 text-xs"
                  >
                    Confirm
                  </Button>
                  <GhostButton onClick={() => rejectMutation.mutate(m.id)} className="py-1 text-xs">
                    Reject
                  </GhostButton>
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ink-tertiary">No pending identity mappings.</p>
      )}
    </Section>
  );
}
