// The draft, persisted to localStorage so a reload mid-draft doesn't lose it.
export const LIMITS = { ally: 5, enemy: 5, ban: 10 };
export const LANES = [
  { value: "any", label: "Any" },
  { value: "jungle", label: "Jungle" },
  { value: "gold", label: "Gold" },
  { value: "exp", label: "EXP" },
  { value: "mid", label: "Mid" },
  { value: "roam", label: "Roam" },
];

const KEY = "draft-copilot:draft:v1";
const blank = () => ({ ally: [], enemy: [], ban: [], lane: "any", target: "ally" });

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY));
    if (!saved) return blank();
    const state = blank();
    for (const team of ["ally", "enemy", "ban"]) {
      if (Array.isArray(saved[team])) state[team] = saved[team].filter((n) => typeof n === "string").slice(0, LIMITS[team]);
    }
    if (LANES.some((l) => l.value === saved.lane)) state.lane = saved.lane;
    if (["ally", "enemy", "ban"].includes(saved.target)) state.target = saved.target;
    return state;
  } catch {
    return blank();
  }
}

export const draft = load();

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(draft)); } catch { /* private mode: fine */ }
}

export const usedBy = (hero) => ["ally", "enemy", "ban"].find((team) => draft[team].includes(hero)) || null;

export function add(team, hero) {
  if (usedBy(hero) || draft[team].length >= LIMITS[team]) return false;
  draft[team].push(hero);
  save();
  return true;
}

export function remove(team, hero) {
  draft[team] = draft[team].filter((h) => h !== hero);
  save();
}

export function setLane(lane) { draft.lane = lane; save(); }
export function setTarget(target) { draft.target = target; save(); }

export const snapshot = () => JSON.parse(JSON.stringify(draft));
export function restore(previous) { Object.assign(draft, previous); save(); }

export function clearAll() {
  const lane = draft.lane;
  Object.assign(draft, blank(), { lane });
  save();
}

export const isEmpty = () => !draft.ally.length && !draft.enemy.length && !draft.ban.length;

export function payload() {
  return { ally_picks: draft.ally, enemy_picks: draft.enemy, banned_heroes: draft.ban, role_needed: draft.lane };
}
