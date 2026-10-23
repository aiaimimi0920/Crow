const paths = {
  sidebar: '<rect x="3" y="4" width="18" height="16" rx="1"/><path d="M9 4v16"/>',
  links: '<path d="m10 13 4-4m-6 6-2 2a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 2 2-2a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0" transform="translate(2 0) scale(.9)"/>',
  details: '<path d="M14 3H5v18h14V8zM14 3v5h5M8 12h8m-8 4h8"/>',
  analysis: '<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
  settings: '<path d="m9 3-1 3-3 1-2 3 2 2-1 3 2 3 3-1 3 2 3-2 3 1 2-3-1-3 2-2-2-3-3-1-1-3z"/><circle cx="12" cy="11" r="3"/>',
  operations: '<path d="M3 4h18v16H3zM6 13h3l2-5 3 9 2-4h2"/>',
  back: '<path d="m10 5-7 7 7 7M3 12h18"/>',
  refresh: '<path d="M20 7a8 8 0 1 0 0 10M20 3v5h-5"/>',
  minimize: '<path d="M5 12h14"/>',
  maximize: '<rect x="5" y="5" width="14" height="14" rx="1"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
} as const;

export function mountShellIcons(): void {
  document.querySelectorAll<HTMLElement>("[data-icon]").forEach((element) => {
    const name = element.dataset.icon;
    if (!name || !Object.hasOwn(paths, name)) return;
    element.innerHTML = `<svg class="shell-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name as keyof typeof paths]}</svg>`;
  });
}
