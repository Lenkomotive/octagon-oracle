frontend:
	cd website && npm install && npm run dev

backend:
	cd backend && source venv/bin/activate && python monitor.py

results:
	cd backend && source venv/bin/activate && python fetch_all_results.py
