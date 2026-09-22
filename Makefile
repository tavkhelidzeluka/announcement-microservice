# Announcements microservice
#
#   make install   create the local virtualenv
#   make test      unit tests
#   make validate  lint the OpenAPI contract and the CloudFormation templates
#   make build     produce the merged OpenAPI document (offline, fake ARNs)
#   make deploy    deploy both stacks   (ARTIFACT_BUCKET=... [ENV=dev])
#   make creds     print the values the Postman environment needs
#   make destroy   tear the environment down

VENV    ?= .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
ENV     ?= dev
REGION  ?= eu-west-1

.PHONY: install test validate build deploy creds destroy clean

install:
	python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r requirements-dev.txt
	@echo "ready: $(VENV)"

test:
	$(VENV)/bin/pytest -q

validate:
	$(PY) scripts/validate.py

# Offline build with placeholder values, to check the merge without deploying.
build:
	$(PY) scripts/build_openapi.py \
	  --set AWS_REGION=$(REGION) \
	  --set AWS_ACCOUNT_ID=000000000000 \
	  --set LIST_FUNCTION_NAME=announcements-$(ENV)-list \
	  --set CREATE_FUNCTION_NAME=announcements-$(ENV)-create \
	  --set USER_POOL_ARN=arn:aws:cognito-idp:$(REGION):000000000000:userpool/$(REGION)_EXAMPLE \
	  --set TOKEN_URL=https://example.auth.$(REGION).amazoncognito.com/oauth2/token \
	  --set ALLOWED_ORIGIN=https://www.philips.com

deploy:
	@test -n "$(ARTIFACT_BUCKET)" || { echo "ARTIFACT_BUCKET=<bucket> is required"; exit 1; }
	PYTHON=$(PY) ./scripts/deploy.sh --artifact-bucket $(ARTIFACT_BUCKET) --env $(ENV) --region $(REGION)

creds:
	./scripts/show_credentials.sh --env $(ENV) --region $(REGION)

destroy:
	./scripts/destroy.sh --env $(ENV) --region $(REGION)

clean:
	rm -rf build .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
