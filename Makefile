.DEFAULT_GOAL := help


################
# Help
################

.PHONY: help
help:
	@grep -E '^[a-zA-Z0-9 -]+:.*## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'


##############
# Dependencies
##############

.PHONY: install install-deps install-precommit update update-deps update-precommit lock outdated

install-deps:  ## Install python dependencies
	poetry install

install-precommit:  ## Install pre-commit hooks
	poetry run pre-commit install

install: install-deps install-precommit ## Install python dependencies and pre-commit hooks

update-deps:  ## Update python dependencies
	poetry update

update-precommit:  ## Update pre-commit hooks
	poetry run pre-commit autoupdate

update: update-deps update-precommit ## Update python dependencies and pre-commit hooks

lock:  ## Lock dependencies
	poetry lock --no-update

outdated: ## List outdated dependencies
	poetry show --outdated


###################
# Local Development
###################

.PHONY: lint lint-format lint-check precommit

lint-format:  ## Lint and format code
	poetry run ruff check spotifagent tests
	poetry run ruff format spotifagent tests
	poetry run mypy
	poetry run deptry .

lint: lint-format

lint-check: ## Lint and check code
	poetry run ruff check --no-fix spotifagent tests
	poetry run ruff format --check spotifagent tests
	poetry run mypy
	poetry run deptry .

precommit: ## Run pre-commit hooks
	poetry run pre-commit run --all-files


############
# Versioning
############

BUMP_TARGETS = bump-patch bump-minor bump-major bump-prepatch bump-preminor bump-premajor bump-prerelease

# This "phantom" target exists only to appear in 'make help'
bump: ## Bump version (options: bump-patch, bump-minor, bump-major, etc.)

.PHONY: $(BUMP_TARGETS) bump
$(BUMP_TARGETS): bump-%:
	poetry version $*
	poetry install


########
# Docker
########

.PHONY: ps logs up up-db down restart reload reset

ps:  ## List containers
	docker compose ps --all

logs:  ## Show container logs
	docker compose logs -f

up: ## Start containers
	docker compose up --detach --build --wait

up-db:  ## Start database container only
	docker compose up --detach --wait db

down: ## Stop containers
	docker compose down --remove-orphans

restart: ## Restart containers
	docker compose restart

reload: down up ## Stop and start containers

reset:  ## Remove volumes and images
	docker compose down --remove-orphans --volumes --rmi local


#####
# App
#####

.PHONY: run app-shell

run: ## Run the application
	poetry run fastapi dev spotifagent/infrastructure/entrypoints/api/main.py

app-shell: up ## Connect to the application shell
	docker compose exec app /bin/bash


##########
# Database
##########

.PHONY: db-upgrade db-downgrade db-revision db-shell

db-upgrade: up-db  ## Upgrade database
	poetry run alembic upgrade head

db-downgrade: up-db  ## Downgrade database
	poetry run alembic downgrade base

db-revision: up-db ## Create a new migration
	poetry run alembic revision --autogenerate

db-shell: up-db ## Connect to the database shell
	docker compose exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'


################
# Testing
################

.PHONY: test test-unit test-integration

test: up-db ## Run all the testsuite
	poetry run pytest ./tests || ($(MAKE) down && exit 1)
	@$(MAKE) down

test-unit: ## Run unit tests
	poetry run pytest ./tests/unit -v

test-integration: up-db ## Run integration tests
	poetry run pytest ./tests/integration -v || ($(MAKE) down && exit 1)
	@$(MAKE) down
