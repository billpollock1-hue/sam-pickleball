#!/usr/bin/env python3
"""
Patch: admin_index.html's Shootout Ties card hides itself automatically
when /api/unresolved-ties returns nothing pending, and shows a count badge
(using the existing #tieBadge span, which was already in the markup and
styled but never wired to real data) when something is.

Run once from the repo root: python3 sam_hide_ties_card_patch.py
Safe to re-run: asserts each anchor matches exactly once.
"""
from pathlib import Path

path = Path("launcher/admin_index.html")
content = path.read_text()


def replace_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, f"{label}: expected exactly 1 match, found {n}"
    return text.replace(old, new)


# 1. Give the card an id so JS can target it.
old_card = '  <a class="card group-c" href="/shootout-ties">\n'
new_card = '  <a class="card group-c" href="/shootout-ties" id="tiesCard">\n'
content = replace_once(content, old_card, new_card, "card element")

# 2. Fetch pending ties on load; hide the card if none, else show the count.
old_close = '</script>\n</body>'
new_close = '''
async function refreshTiesCard() {
  const card = document.getElementById('tiesCard');
  const badge = document.getElementById('tieBadge');
  if (!card || !badge) return;
  try {
    const resp = await fetch('/api/unresolved-ties');
    const ties = await resp.json();
    if (!ties.length) {
      card.style.display = 'none';
    } else {
      card.style.display = '';
      badge.textContent = ties.length;
      badge.style.display = 'inline-block';
    }
  } catch (e) {
    // Leave the card visible (its own page will show a real error) rather
    // than hide something that might still need attention.
  }
}
refreshTiesCard();
</script>
</body>'''
content = replace_once(content, old_close, new_close, "script close")

path.write_text(content)
print("admin_index.html updated successfully")
