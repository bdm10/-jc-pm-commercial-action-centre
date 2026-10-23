import { createContext, useContext } from "react";
import type { Me, Meta } from "./api/types";
import type { SheetTarget } from "./components/ActionSheet";

export type Session = { me: Me; meta: Meta; openSheet: (t: SheetTarget) => void };
export const SessionCtx = createContext<Session | null>(null);

export function useSession(): Session {
  const s = useContext(SessionCtx);
  if (!s) throw new Error("useSession outside session");
  return s;
}
