import { isTauriRuntime as isTauri } from "./desktop_native.ts";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { mountShellIcons } from "./desktop_shell_icons.ts";
import { element } from "./desktop_dom.ts";

export function initializeShell(refresh: () => Promise<void>): void {
  mountShellIcons();
  const shell = element("appShell");
  const railToggle = element<HTMLButtonElement>("toggleSidebar");
  const backButton = element<HTMLButtonElement>("closeSettings");
  const pages = {
    collection: { panel: "collectionPage", button: "openCollection", title: "workspaceTitle" },
    operations: { panel: "operationsPage", button: "openOperations", title: "operationsTitle" },
    settings: { panel: "settingsPage", button: "openSettings", title: "settingsTitle" },
  } as const;
  type Page = keyof typeof pages;
  const scrollArea = element("collectionPage").closest("main");
  const scrolls: Record<Page, number> = { collection: 0, operations: 0, settings: 0 };
  let currentPage: Page = "collection";
  const narrow = window.matchMedia("(max-width: 820px)");
  let collapsed = false;

  const updateRail = () => {
    const compact = narrow.matches || collapsed;
    shell.classList.toggle("rail-collapsed", compact);
    railToggle.disabled = narrow.matches;
    railToggle.setAttribute("aria-expanded", String(!compact));
    railToggle.setAttribute("aria-label", compact ? "展开侧栏" : "收起侧栏");
    railToggle.title = narrow.matches ? "窄窗口使用紧凑侧栏" : railToggle.getAttribute("aria-label") || "";
  };
  railToggle.addEventListener("click", () => { collapsed = !collapsed; updateRail(); });
  narrow.addEventListener("change", updateRail);
  updateRail();

  const showPage = (page: Page) => {
    scrolls[currentPage] = scrollArea?.scrollTop || 0;
    currentPage = page;
    for (const [name, entry] of Object.entries(pages)) {
      element(entry.panel).classList.toggle("hidden", name !== page);
      element(entry.button).classList.toggle("active", name === page);
      element(entry.button).setAttribute("aria-pressed", String(name === page));
    }
    backButton.classList.toggle("hidden", page === "collection");
    if (page !== "collection") element(pages[page].title).focus();
    if (scrollArea) scrollArea.scrollTop = scrolls[page];
  };
  for (const page of Object.keys(pages) as Page[]) {
    element(pages[page].button).addEventListener("click", () => { if (currentPage !== page) showPage(page); });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented || currentPage === "collection"
      || document.querySelector("dialog[open], dialog.open") || (event.target instanceof Element && event.target.closest("dialog"))) return;
    const previous = currentPage;
    event.preventDefault(); showPage("collection"); element(pages[previous].button).focus();
  });
  backButton.addEventListener("click", () => { const previous = currentPage; showPage("collection"); element(pages[previous].button).focus(); });
  document.querySelectorAll<HTMLButtonElement>("[data-settings-target]").forEach((button) => {
    button.addEventListener("click", () => {
      showPage("settings");
      element<HTMLDetailsElement>("runtimeSettings").open = true;
      const target = document.getElementById(button.dataset.settingsTarget || "");
      target?.focus(); target?.scrollIntoView({ block: "center" });
    });
  });

  element("windowRefresh").addEventListener("click", () => void refresh());
  if (!isTauri()) return;
  document.querySelectorAll<HTMLElement>("[data-window-command]").forEach((button) => button.classList.remove("hidden"));
  const appWindow = getCurrentWindow();
  const runWindowCommand = async (command: string) => {
    try {
      if (command === "minimize") await appWindow.minimize();
      else if (command === "maximize") await appWindow.toggleMaximize();
      else if (command === "close") await appWindow.close();
      else if (command === "drag") await appWindow.startDragging();
    } catch (error) {
      const notice = element("shellNotice");
      notice.textContent = `窗口操作失败：${error instanceof Error ? error.message : String(error)}`;
      notice.classList.remove("hidden");
    }
  };
  document.querySelectorAll<HTMLElement>("[data-window-command]").forEach((button) => {
    button.addEventListener("click", () => void runWindowCommand(button.dataset.windowCommand || ""));
  });
  document.querySelectorAll<HTMLElement>("[data-window-drag]").forEach((region) => {
    region.addEventListener("mousedown", (event) => {
      if (event.button !== 0 || (event.target instanceof Element && event.target.closest("button"))) return;
      void runWindowCommand(event.detail === 2 ? "maximize" : "drag");
    });
  });
}
