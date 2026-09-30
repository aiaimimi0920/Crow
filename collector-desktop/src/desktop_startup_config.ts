const API_CONFLICT = "crow_configuration_alias_conflict:CROW_COLLECTOR_API_BASE,FAPAI_COLLECTOR_API_BASE";
export const CONFIGURATION_ERROR = "CROW_COLLECTOR_API_BASE 与 FAPAI_COLLECTOR_API_BASE 配置冲突，请修正配置或明确应用 API 地址";

export async function startupApiBase(invoke: () => Promise<unknown>, fallback: () => string): Promise<{ apiBase: string; blocked: boolean }> {
  try {
    const value = await invoke();
    if (typeof value !== "string" || !value) throw new Error("Missing API address");
    return { apiBase: value, blocked: false };
  } catch (error) {
    if (error === API_CONFLICT || (error instanceof Error && error.message === API_CONFLICT)) {
      return { apiBase: "", blocked: true };
    }
    return { apiBase: fallback(), blocked: false };
  }
}
