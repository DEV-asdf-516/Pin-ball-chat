export const state = {
  route: "plots",
  catalog: {
    plots: { byId: new Map(), order: [], page: { nextCursor: null, hasMore: false, loading: false } },
    chars: { byId: new Map(), order: [], page: { nextCursor: null, hasMore: false, loading: false } },
    users: { byId: new Map(), order: [], page: { nextCursor: null, hasMore: false, loading: false } },
  },
  selectedPlot: null,
  selectedUserProfileId: null,
  managedPlotId: null,
  activeConversationId: null,
  activeMessages: { list: [], nextCursor: null, hasMore: false },
  conversations: {
    byId: new Map(),
    order: [],
    page: { nextCursor: null, hasMore: false, loading: false },
  },
  streaming: false,
  ui: { chatFromList: false },
  composerEdit: null,
  pendingUserResend: null,
  composerHeight: null,
  composerMaxHeight: 136,
  settings: {
    provider: "local-stub",
    model: "local-stub",
    numPredict: 1500,
    numCtx: 8192,
    compactPrompt: true,
    adapterId: "",
  },
};

const listeners = new Map();

export function subscribe(key, fn) {
  if (!listeners.has(key)) listeners.set(key, new Set());
  listeners.get(key).add(fn);
}

export function notify(...keys) {
  for (const key of keys) listeners.get(key)?.forEach((fn) => fn());
}
