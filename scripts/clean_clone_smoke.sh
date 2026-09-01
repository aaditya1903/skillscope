#!/usr/bin/env bash
# Verify that a fresh clone of the current HEAD builds and passes on its own.
#
# The clone gets no .env, no virtual environment, no node_modules and no local
# database rows, so anything the repository forgot to commit or document fails
# here rather than for a reader.
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="$(mktemp -d "${TMPDIR:-/tmp}/skillscope-clean-clone.XXXXXX")"
CLONE="$WORKSPACE/skillscope"
DATABASE_CONTAINER="skillscope-clean-clone-db"
DATABASE_PORT="${CLEAN_CLONE_DB_PORT:-55432}"
DATABASE_BASE="postgresql+psycopg://skillscope:skillscope@127.0.0.1:$DATABASE_PORT"
# The demonstration corpus and the integration suite get separate databases, so
# a loaded corpus never becomes an implicit test fixture.
DEMO_DATABASE_URL="$DATABASE_BASE/skillscope"
TEST_DATABASE_URL="$DATABASE_BASE/skillscope_test"

cleanup() {
  local status=$?
  docker rm --force "$DATABASE_CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$WORKSPACE"
  exit $status
}
trap cleanup EXIT

step() { echo; echo "==> $1"; }

step "Cloning HEAD into $CLONE"
git clone --quiet --no-hardlinks "$REPOSITORY_ROOT" "$CLONE"
cd "$CLONE"
echo "    commit $(git rev-parse --short HEAD)"

step "Confirming no secret or local artefact was cloned"
for forbidden in .env .venv node_modules data/cache data/raw; do
  if [[ -e "$forbidden" ]]; then
    echo "clean clone contains $forbidden" >&2
    exit 1
  fi
done
test -f .env.example || { echo ".env.example is missing" >&2; exit 1; }

step "Installing locked dependencies"
uv sync --locked
npm ci --prefix frontend --silent

step "Starting a throwaway PostgreSQL with pgvector"
docker rm --force "$DATABASE_CONTAINER" >/dev/null 2>&1 || true
docker run --detach --name "$DATABASE_CONTAINER" \
  --env POSTGRES_DB=skillscope \
  --env POSTGRES_USER=skillscope \
  --env POSTGRES_PASSWORD=skillscope \
  --publish "127.0.0.1:$DATABASE_PORT:5432" \
  --health-cmd "pg_isready -U skillscope -d skillscope" \
  --health-interval 2s --health-timeout 3s --health-retries 30 \
  pgvector/pgvector:0.8.6-pg18-trixie >/dev/null

for _ in $(seq 1 45); do
  if [[ "$(docker inspect --format '{{.State.Health.Status}}' "$DATABASE_CONTAINER")" == "healthy" ]]; then
    break
  fi
  sleep 1
done
[[ "$(docker inspect --format '{{.State.Health.Status}}' "$DATABASE_CONTAINER")" == "healthy" ]] \
  || { echo "the throwaway database never became healthy" >&2; exit 1; }
docker exec "$DATABASE_CONTAINER" createdb -U skillscope skillscope_test

step "Applying migrations to an empty database"
DATABASE_URL="$DEMO_DATABASE_URL" uv run alembic upgrade head
DATABASE_URL="$DEMO_DATABASE_URL" uv run alembic check

step "Loading the demonstration corpus without a GitHub token"
env -u GITHUB_TOKEN DATABASE_URL="$DEMO_DATABASE_URL" uv run skillscope demo load

step "Searching the demonstration corpus in every mode"
for mode in bm25 dense hybrid; do
  DATABASE_URL="$DEMO_DATABASE_URL" uv run skillscope search "review a code diff" \
    --mode "$mode" --top-k 3 \
    --config config/demo/bm25-v1.json \
    --dense-config config/demo/dense-hybrid-v1.json >/dev/null
  echo "    $mode search answered"
done

step "Running the quality gate"
SKILLSCOPE_TEST_DATABASE_URL="$TEST_DATABASE_URL" uv run ruff format --check .
SKILLSCOPE_TEST_DATABASE_URL="$TEST_DATABASE_URL" uv run ruff check .
SKILLSCOPE_TEST_DATABASE_URL="$TEST_DATABASE_URL" uv run mypy src
SKILLSCOPE_TEST_DATABASE_URL="$TEST_DATABASE_URL" uv run pytest -q

step "Building the interface"
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend

echo
echo "clean clone verification passed"
