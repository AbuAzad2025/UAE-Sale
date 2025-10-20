.PHONY: help install run test clean

help:
	@echo "UAE-Sale Development Commands"
	@echo "============================="
	@echo "make install    - Install dependencies"
	@echo "make run        - Run development server"
	@echo "make clean      - Clean cache files"
	@echo "make backup     - Create database backup"

install:
	pip install -r requirements.txt

run:
	python app.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete

backup:
	python -c "from services.backup_service import BackupService; BackupService.create_backup()"

