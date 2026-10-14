"use client";

import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api/client";

export type Me = Schemas["MeOut"];
export type Workspace = Schemas["MyWorkspaceOut"];
export type Source = Schemas["SourceOut"];
export type MessageItem = Schemas["MessageListItemOut"];
export type MessageDetail = Schemas["MessageDetailOut"];
export type Member = Schemas["MemberOut"];
export type Invite = Schemas["InviteOut"];
export type ImapPreset = Schemas["ImapPresetOut"];
export type ImapTest = Schemas["ImapTestOut"];
export type ImapConnect = Schemas["ImapConnectIn"];
export type Direction = Schemas["Direction"];

export const keys = {
  me: ["me"] as const,
  authConfig: ["auth-config"] as const,
  workspace: (wid: string) => ["w", wid] as const,
  overview: (wid: string) => ["w", wid, "overview"] as const,
  messages: (wid: string, filters: object) => ["w", wid, "messages", filters] as const,
  message: (wid: string, id: string) => ["w", wid, "message", id] as const,
  sources: (wid: string) => ["w", wid, "sources"] as const,
  presets: ["imap-presets"] as const,
  members: (wid: string) => ["w", wid, "members"] as const,
  invites: (wid: string) => ["w", wid, "invites"] as const,
  invite: (token: string) => ["invite", token] as const,
};

const path = (workspace_id: string) => ({ params: { path: { workspace_id } } });

// --- auth ---------------------------------------------------------------------------------------

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: () => unwrap(api.GET("/api/auth/me")) });
}

export function useAuthConfig() {
  return useQuery({
    queryKey: keys.authConfig,
    queryFn: () => unwrap(api.GET("/api/auth/config")),
    staleTime: Infinity,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["LoginIn"]) => unwrap(api.POST("/api/auth/login", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.me }),
  });
}

export function useSignup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["SignupIn"]) => unwrap(api.POST("/api/auth/signup", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.me }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/auth/logout")),
    onSuccess: () => qc.clear(),
  });
}

// --- workspaces ---------------------------------------------------------------------------------

export function useCreateWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => unwrap(api.POST("/api/workspaces", { body: { name } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.me }),
  });
}

export function useOverview(wid: string) {
  return useQuery({
    queryKey: keys.overview(wid),
    queryFn: () => unwrap(api.GET("/api/w/{workspace_id}/overview", path(wid))),
    refetchInterval: 60_000,
  });
}

// --- messages -----------------------------------------------------------------------------------

export type MessageFilters = { direction?: Direction; source_id?: string; q?: string };
const PAGE_SIZE = 50;

export function useMessages(wid: string, filters: MessageFilters) {
  return useInfiniteQuery({
    queryKey: keys.messages(wid, filters),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/w/{workspace_id}/messages", {
          params: {
            path: { workspace_id: wid },
            query: { ...filters, limit: PAGE_SIZE, offset: pageParam },
          },
        }),
      ),
    getNextPageParam: (last) =>
      last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined,
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });
}

export function useMessage(wid: string, id: string) {
  return useQuery({
    queryKey: keys.message(wid, id),
    queryFn: () =>
      unwrap(
        api.GET("/api/w/{workspace_id}/messages/{message_id}", {
          params: { path: { workspace_id: wid, message_id: id } },
        }),
      ),
  });
}

// --- sources ------------------------------------------------------------------------------------

export function useSources(wid: string) {
  return useQuery({
    queryKey: keys.sources(wid),
    queryFn: () => unwrap(api.GET("/api/w/{workspace_id}/sources", path(wid))),
    // Poll while a mailbox is being read for the first time so progress shows up.
    refetchInterval: (query) =>
      query.state.data?.some((s) => s.status === "active" && !s.backfill_completed_at)
        ? 4_000
        : 30_000,
  });
}

export function usePresets() {
  return useQuery({
    queryKey: keys.presets,
    queryFn: () => unwrap(api.GET("/api/sources/imap-presets")),
    staleTime: Infinity,
  });
}

export function useTestImap(wid: string) {
  return useMutation({
    mutationFn: (body: Schemas["ImapSettingsIn"]) =>
      unwrap(api.POST("/api/w/{workspace_id}/sources/imap/test", { ...path(wid), body })),
  });
}

export function useConnectImap(wid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ImapConnect) =>
      unwrap(api.POST("/api/w/{workspace_id}/sources/imap", { ...path(wid), body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["w", wid] }),
  });
}

export function useUpdateSource(wid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["SourceUpdateIn"] }) =>
      unwrap(
        api.PATCH("/api/w/{workspace_id}/sources/{source_id}", {
          params: { path: { workspace_id: wid, source_id: id } },
          body,
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["w", wid] }),
  });
}

export function useSyncSource(wid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/api/w/{workspace_id}/sources/{source_id}/sync", {
          params: { path: { workspace_id: wid, source_id: id } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.sources(wid) }),
  });
}

export function useDisconnectSource(wid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/w/{workspace_id}/sources/{source_id}", {
          params: { path: { workspace_id: wid, source_id: id } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["w", wid] }),
  });
}

// --- team ---------------------------------------------------------------------------------------

export function useMembers(wid: string) {
  return useQuery({
    queryKey: keys.members(wid),
    queryFn: () => unwrap(api.GET("/api/w/{workspace_id}/members", path(wid))),
  });
}

export function useInvites(wid: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.invites(wid),
    queryFn: () => unwrap(api.GET("/api/w/{workspace_id}/invites", path(wid))),
    enabled,
  });
}

export function useCreateInvite(wid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["InviteCreateIn"]) =>
      unwrap(api.POST("/api/w/{workspace_id}/invites", { ...path(wid), body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.invites(wid) }),
  });
}

export function useRevokeInvite(wid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/w/{workspace_id}/invites/{invite_id}", {
          params: { path: { workspace_id: wid, invite_id: id } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.invites(wid) }),
  });
}

export function useRemoveMember(wid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      unwrap(
        api.DELETE("/api/w/{workspace_id}/members/{user_id}", {
          params: { path: { workspace_id: wid, user_id: userId } },
        }),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.members(wid) });
      qc.invalidateQueries({ queryKey: keys.me });
    },
  });
}

export function useInvitePreview(token: string) {
  return useQuery({
    queryKey: keys.invite(token),
    queryFn: () => unwrap(api.GET("/api/invites/{token}", { params: { path: { token } } })),
    retry: false,
  });
}

export function useAcceptInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (token: string) =>
      unwrap(api.POST("/api/invites/{token}/accept", { params: { path: { token } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.me }),
  });
}
