.PHONY: build up down logs

build:
	docker compose build

up:
	docker compose up

down:
	docker compose down

logs:
	docker logs -f django-laundrymart
