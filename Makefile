.PHONY: all setup hooks install linter
all: install linter

setup:
	# install meta requirements system-wide
	@ echo installing requirements; \
	pipenv install --dev; \

hooks:
	# install pre-commit hooks when not in CI
	@ if [ -z "$$CI" ]; then \
		pipenv run pre-commit install; \
	fi; \

install: setup hooks
	# install packages and pre-commit hooks in local virtual environment
	@ echo installation complete; \

linter:
	# run the linter hooks from pre-commit on all files
	@ echo linting all files; \
	pipenv run pre-commit run --all-files; \