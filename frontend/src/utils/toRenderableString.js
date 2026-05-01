/**
 * Coerce arbitrary backend list items to a renderable string.
 *
 * Several Archmorph endpoints return arrays that the frontend renders
 * inline in JSX. The backend GPT layer occasionally emits objects
 * (e.g. `{type, message}` warnings, `{name}` services) where strings
 * are expected — rendering those objects directly crashes React with
 * error #31 ("Objects are not valid as a React child").
 *
 * This helper mirrors the backend's
 * `utils.chat_coercion.coerce_to_str_list` so a single misbehaving
 * response cannot brick the UI. Returns an empty string if no usable
 * text can be extracted (callers should skip empties).
 */
export function toRenderableString(item) {
  if (item == null) return '';
  if (typeof item === 'string') return item;
  if (typeof item === 'number' || typeof item === 'boolean') return String(item);
  if (Array.isArray(item)) {
    return item.map(toRenderableString).filter(Boolean).join(', ');
  }
  if (typeof item === 'object') {
    for (const key of ['message', 'text', 'name', 'label', 'value', 'description']) {
      const val = item[key];
      if (typeof val === 'string' && val) return val;
    }
    try {
      return JSON.stringify(item);
    } catch {
      return String(item);
    }
  }
  return String(item);
}

export default toRenderableString;
