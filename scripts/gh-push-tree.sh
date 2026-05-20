#!/bin/bash
# gh-push-tree.sh — Push multiple files to GitHub in 1 commit via Git Trees API
# Preserves directory structure. Builds on remote HEAD (not local).
#
# Usage:
#   ./scripts/gh-push-tree.sh -m "commit message" file1 file2 dir/file3 ...
#   ./scripts/gh-push-tree.sh --move old/path:new/path [-m "msg"]
#   ./scripts/gh-push-tree.sh --move old:new --move old2:new2 file3 -m "msg"
#   ./scripts/gh-push-tree.sh --delete path/to/file [-m "msg"]

set -e

REPO="garyho1998/trade_with_what_he_see"
BRANCH="main"
TOKEN="${GH_TOKEN:?Set GH_TOKEN env var first}"
API="https://api.github.com/repos/$REPO"

# --- Parse args ---
MSG=""
FILES=()
MOVES=()    # "old_path:new_path" pairs
DELETES=()  # paths to delete
while [[ $# -gt 0 ]]; do
  case "$1" in
    -m)       MSG="$2"; shift 2 ;;
    --move)   MOVES+=("$2"); shift 2 ;;
    --delete) DELETES+=("$2"); shift 2 ;;
    *)        FILES+=("$1"); shift ;;
  esac
done

if [ ${#FILES[@]} -eq 0 ] && [ ${#MOVES[@]} -eq 0 ] && [ ${#DELETES[@]} -eq 0 ]; then
  echo "Usage:"
  echo "  ./scripts/gh-push-tree.sh -m \"message\" file1 [file2 ...]"
  echo "  ./scripts/gh-push-tree.sh --move old/path:new/path [-m \"msg\"]"
  echo "  ./scripts/gh-push-tree.sh --delete path/to/file [-m \"msg\"]"
  echo "  Combine: --move, --delete, and files in one commit"
  exit 1
fi

MSG="${MSG:-Update ${FILES[*]}${MOVES[*]+; move ${MOVES[*]}}${DELETES[*]+; delete ${DELETES[*]}}}"

api_get() {
  curl -sf -H "Authorization: token $TOKEN" "$API$1"
}

api_post() {
  curl -sf -X POST -H "Authorization: token $TOKEN" \
    -H "Content-Type: application/json" "$API$1" -d @-
}

jq_py() {
  python3 -c "import sys,json; print(json.load(sys.stdin)$1)"
}

NEEDS_FULL_TREE=false
if [ ${#MOVES[@]} -gt 0 ] || [ ${#DELETES[@]} -gt 0 ]; then
  NEEDS_FULL_TREE=true
fi

# --- Step 1: Get remote HEAD ---
echo "1/5 Getting remote HEAD..."
HEAD_SHA=$(api_get "/git/refs/heads/$BRANCH" | jq_py "['object']['sha']")
BASE_TREE=$(api_get "/git/commits/$HEAD_SHA" | jq_py "['tree']['sha']")
echo "     HEAD: ${HEAD_SHA:0:7}  Tree: ${BASE_TREE:0:7}"

# --- Step 2: Create blobs for new/updated files ---
BLOB_SHAS=()
if [ ${#FILES[@]} -gt 0 ]; then
  echo "2/5 Creating blobs (${#FILES[@]} files)..."
  for FILE in "${FILES[@]}"; do
    if [ ! -f "$FILE" ]; then
      echo "  SKIP (not found): $FILE"
      continue
    fi

    BLOB_SHA=$(python3 -c "
import base64, json, sys
with open('$FILE', 'rb') as f:
    content = base64.b64encode(f.read()).decode()
sys.stdout.write(json.dumps({'content': content, 'encoding': 'base64'}))
" | api_post "/git/blobs" | jq_py "['sha']")

    echo "  $FILE → ${BLOB_SHA:0:7}"
    BLOB_SHAS+=("$BLOB_SHA:$FILE")
  done
else
  echo "2/5 No new files to upload"
fi

# --- Step 3: Create tree ---
echo "3/5 Creating tree..."

if [ "$NEEDS_FULL_TREE" = true ]; then
  # Move/delete requires full tree rebuild (base_tree can't delete entries)
  # Fetch existing tree → remove old paths → add new paths → POST without base_tree
  EXISTING_TREE=$(api_get "/git/trees/$BASE_TREE?recursive=1")

  NEW_TREE=$(python3 -c "
import json, sys

existing = json.loads(sys.stdin.read())
moves = {}       # old_path → new_path
move_args = [m for m in sys.argv[1].split('|') if m]
for m in move_args:
    old, new = m.split(':', 1)
    moves[old] = new

deletes = set(d for d in sys.argv[2].split('|') if d)

# blob overrides from new file uploads: 'sha:path' format
blob_overrides = {}
for b in sys.argv[3].split('|'):
    if not b: continue
    sha, path = b.split(':', 1)
    blob_overrides[path] = sha

# Build new tree entries from existing (skip trees, only blobs)
entries = []
for item in existing['tree']:
    if item['type'] == 'tree':
        continue  # directories are implicit from blob paths

    path = item['path']

    # Skip deleted paths
    if path in deletes:
        continue

    # Rename moved paths (keep same blob SHA)
    if path in moves:
        entries.append({
            'path': moves[path],
            'mode': item['mode'],
            'type': 'blob',
            'sha': item['sha']
        })
        continue

    # Keep as-is
    entries.append({
        'path': path,
        'mode': item['mode'],
        'type': 'blob',
        'sha': item['sha']
    })

# Add new/updated files
for path, sha in blob_overrides.items():
    # Remove existing entry if updating
    entries = [e for e in entries if e['path'] != path]
    entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': sha})

# POST without base_tree = full tree
sys.stdout.write(json.dumps({'tree': entries}))
" <<< "$EXISTING_TREE" \
    "$(IFS='|'; echo "${MOVES[*]}")" \
    "$(IFS='|'; echo "${DELETES[*]}")" \
    "$(IFS='|'; echo "${BLOB_SHAS[*]}")" \
  | api_post "/git/trees" | jq_py "['sha']")

  # Show what changed
  for M in "${MOVES[@]}"; do
    echo "  MOVE: ${M%%:*} → ${M#*:}"
  done
  for D in "${DELETES[@]}"; do
    echo "  DELETE: $D"
  done

else
  # Simple add/update — use base_tree (efficient, no full tree fetch)
  TREE_JSON=$(python3 -c "
import json, sys
entries = []
for item in sys.argv[1:]:
    sha, path = item.split(':', 1)
    entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': sha})
sys.stdout.write(json.dumps({'base_tree': '$BASE_TREE', 'tree': entries}))
" "${BLOB_SHAS[@]}")

  NEW_TREE=$(echo "$TREE_JSON" | api_post "/git/trees" | jq_py "['sha']")
fi

echo "     New tree: ${NEW_TREE:0:7}"

# --- Step 4: Create commit ---
echo "4/5 Creating commit..."
COMMIT_SHA=$(python3 -c "
import json, sys
msg = sys.stdin.read()
sys.stdout.write(json.dumps({'message': msg, 'tree': '$NEW_TREE', 'parents': ['$HEAD_SHA']}))
" <<< "$MSG" | api_post "/git/commits" | jq_py "['sha']")
echo "     Commit: ${COMMIT_SHA:0:7}"

# --- Step 5: Update branch ---
echo "5/5 Updating $BRANCH..."
echo "{\"sha\":\"$COMMIT_SHA\"}" \
  | curl -sf -X PATCH -H "Authorization: token $TOKEN" \
    -H "Content-Type: application/json" "$API/git/refs/heads/$BRANCH" -d @- > /dev/null

echo ""
TOTAL=$((${#FILES[@]} + ${#MOVES[@]} + ${#DELETES[@]}))
echo "Done! ${TOTAL} operations in 1 commit."
echo "https://github.com/$REPO/commit/$COMMIT_SHA"
