const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

/** Accept remote changes only where the user has not changed the previous saved value. */
export function reconcileDraft<T>(draft: T, previous: T, next: T): T {
  if (Array.isArray(draft) || draft === null || typeof draft !== 'object') return same(draft, previous) ? next : draft
  const result = { ...draft } as T
  for (const key of Object.keys(next as object) as (keyof T)[]) {
    if (same(draft[key], previous[key])) result[key] = next[key]
  }
  return result
}
