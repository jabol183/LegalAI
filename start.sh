#!/bin/bash
# LegalAI startup script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create .env from example if not exists
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env — please add your ANTHROPIC_API_KEY"
fi

# Create virtualenv if not exists
if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt

# Download spaCy model if not present
python -c "import spacy; spacy.load('en_core_web_lg')" 2>/dev/null || {
  echo "Downloading spaCy model..."
  python -m spacy download en_core_web_lg
}

# Seed the playbook with standard clauses if ChromaDB is empty
python -c "
import sys
sys.path.insert(0, '.')
from backend.playbook import playbook
if playbook.collection_count() == 0:
    count = playbook.load_from_json('playbooks/standard_clauses.json')
    print(f'Seeded playbook with {count} standard clauses.')
else:
    print(f'Playbook already has {playbook.collection_count()} clauses.')
"

# Start server
echo ""
echo "Starting LegalAI server at http://localhost:8000"
echo "Press Ctrl+C to stop."
echo ""
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
