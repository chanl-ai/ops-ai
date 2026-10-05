'use client';

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

/** Staff and roles the current team can run a test as. */
export const useRunAsPrincipals = () => useQuery({ queryKey: ['run-as', 'principals'], queryFn: api.runAs.principals, staleTime: 5 * 60_000 });
