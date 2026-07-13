import { api } from "./api.js";

export async function loadCursorPage(pageState, options) {
  const { path, itemKey, apply, reset = false, limit = 30 } = options;
  if (pageState.loading || (!reset && !pageState.hasMore)) return [];
  pageState.loading = true;
  try {
    const before = reset || !pageState.nextCursor ? "" : `&before=${encodeURIComponent(pageState.nextCursor)}`;
    const page = await api(`${path}?limit=${limit}${before}`);
    const items = Array.isArray(page) ? page : page[itemKey] || [];
    pageState.nextCursor = Array.isArray(page) ? null : page.nextCursor || null;
    pageState.hasMore = Array.isArray(page) ? false : Boolean(page.hasMore);
    apply(items, !reset);
    return items;
  } finally {
    pageState.loading = false;
  }
}
