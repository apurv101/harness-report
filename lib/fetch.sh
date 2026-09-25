# fetch.sh — stage 1: the harness repo at its current HEAD.  Sourced by run.sh.
# Reads OWNER REPO SRC WORK REBUILD and HR_GIT_TOKEN; sets COMMIT, and writes work/<name>/source.json.

# A private repo is fetched with $HR_GIT_TOKEN (a short-lived GitHub App installation token that serve.py mints). It goes
# to git only as an auth header through git's environment: never in a URL, a log line or .git/config, and it is unset
# before the analyzer or any container starts.
git_fetching() {
  if [ -n "${HR_GIT_TOKEN:-}" ]; then
    GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="http.https://github.com/.extraheader" \
      GIT_CONFIG_VALUE_0="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$HR_GIT_TOKEN" | base64 | tr -d '\n')" git "$@"
  else git "$@"; fi
}

# fetch_repo: always the repo's current HEAD; an existing clone is only a download cache, reset to exactly that
# commit (no stray files, since the whole tree is the build context).
fetch_repo() {
  UPSTREAM="https://github.com/$OWNER/$REPO"
  if [ -d "$SRC/.git" ] && [ "$REBUILD" = 0 ]; then
    WAS="$(git -C "$SRC" rev-parse --short HEAD)"
    git_fetching -C "$SRC" fetch -q --depth 1 "$UPSTREAM" HEAD && git -C "$SRC" reset -q --hard FETCH_HEAD && git -C "$SRC" clean -qfdx \
      || die "could not fetch HEAD of $UPSTREAM"
    NOW="$(git -C "$SRC" rev-parse --short HEAD)"; [ "$WAS" = "$NOW" ] && echo "at HEAD $NOW (unchanged)" || echo "updated $WAS → $NOW"
  else rm -rf "$SRC"; git_fetching clone -q --depth 1 "$UPSTREAM" "$SRC" || die "could not clone $UPSTREAM"; echo "cloned $(git -C "$SRC" rev-parse --short HEAD)"; fi
  unset HR_GIT_TOKEN
  COMMIT="$(git -C "$SRC" rev-parse HEAD)"
  emit type fetched commit "$COMMIT"
  printf '{"repo":"https://github.com/%s/%s","commit":"%s"}\n' "$OWNER" "$REPO" "$COMMIT" > "$WORK/source.json"
}
