frontend:
	cd website && npm install && npm run dev

backend:
	cd backend && ./venv/bin/python monitor.py

results:
	cd backend && ./venv/bin/python fetch_all_results.py

# Docker
up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

# Database
db-migrate:
	cd backend && ./venv/bin/alembic upgrade head

db-import:
	cd backend && ./venv/bin/python import_json.py

db-reset:
	docker compose down -v && docker compose up -d db && sleep 3 && make db-migrate && make db-import
