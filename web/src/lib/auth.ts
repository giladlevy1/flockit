import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "./api";
import type { Me } from "./types";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<Me>("/api/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
}

export function useSetupStatus() {
  return useQuery({
    queryKey: ["setup"],
    queryFn: () => api<{ needs_setup: boolean }>("/api/setup"),
    staleTime: Infinity,
  });
}
