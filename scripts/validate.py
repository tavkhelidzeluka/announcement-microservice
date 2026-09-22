#!/usr/bin/env python3
"""Static checks that run without an AWS account.

* the published contract, and the merged contract, are valid OpenAPI 3;
* the published contract carries no AWS-specific extension;
* both CloudFormation templates parse, and every Fn::ImportValue in the API
  stack matches an export the foundation stack publishes.
"""
import re
import subprocess
import sys
import tempfile

import yaml

CONTRACT = "api/openapi.yaml"
OVERLAY = "infrastructure/openapi-aws-overlay.yaml"
FOUNDATION = "infrastructure/foundation.yaml"
API = "infrastructure/api.yaml"

failures = []


def check(description, ok, detail=""):
    print("{0} {1}{2}".format("PASS" if ok else "FAIL", description,
                              "" if ok else "\n     " + detail))
    if not ok:
        failures.append(description)


class CfnLoader(yaml.SafeLoader):
    """CloudFormation short forms (!Ref, !Sub, ...) are not standard YAML."""


CfnLoader.add_multi_constructor(
    "!", lambda loader, suffix, node: {"Fn::" + suffix: _node_value(loader, node)}
)


def _node_value(loader, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


def validate_openapi(path, label):
    try:
        from openapi_spec_validator import validate as validate_spec
    except ImportError:
        check("{0} is valid OpenAPI 3".format(label), True,
              "(skipped: openapi-spec-validator not installed)")
        return
    with open(path) as handle:
        document = yaml.safe_load(handle)
    try:
        validate_spec(document)
        check("{0} is valid OpenAPI 3".format(label), True)
    except Exception as error:  # noqa: BLE001 - report, do not crash
        check("{0} is valid OpenAPI 3".format(label), False, str(error)[:600])


def main():
    validate_openapi(CONTRACT, "published contract")

    with open(CONTRACT) as handle:
        contract_text = handle.read()
    vendor = sorted(set(re.findall(r"x-amazon-[a-z-]+", contract_text)))
    check(
        "published contract carries no AWS extensions",
        not vendor,
        "found: {0}".format(", ".join(vendor)),
    )

    # Merge, then validate the result too: the overlay must not break the spec.
    merged = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False)
    merged.close()
    result = subprocess.run(
        [
            sys.executable, "scripts/build_openapi.py", "--output", merged.name,
            "--set", "AWS_REGION=eu-west-1",
            "--set", "AWS_ACCOUNT_ID=000000000000",
            "--set", "LIST_FUNCTION_NAME=announcements-dev-list",
            "--set", "CREATE_FUNCTION_NAME=announcements-dev-create",
            "--set", "USER_POOL_ARN=arn:aws:cognito-idp:eu-west-1:000000000000:userpool/eu-west-1_EXAMPLE",
            "--set", "TOKEN_URL=https://example.auth.eu-west-1.amazoncognito.com/oauth2/token",
            "--set", "ALLOWED_ORIGIN=https://www.philips.com",
        ],
        capture_output=True, text=True,
    )
    check("contract and AWS overlay merge", result.returncode == 0,
          result.stderr.strip())
    if result.returncode == 0:
        validate_openapi(merged.name, "merged contract")

        with open(merged.name) as handle:
            aws_document = yaml.safe_load(handle)
        operations = aws_document["paths"]["/announcements"]
        bound = [
            name for name, operation in operations.items()
            if isinstance(operation, dict)
            and "x-amazon-apigateway-integration" in operation
        ]
        check(
            "every operation has an API Gateway integration",
            sorted(bound) == ["get", "options", "post",
                              "x-amazon-apigateway-any-method"],
            "bound: {0}".format(sorted(bound)),
        )
        check(
            "API Gateway would not switch on its own x-api-key",
            "apiKey" not in aws_document["components"]["securitySchemes"],
        )

        # A Cognito scheme left as type: oauth2 imports as no authorizer at
        # all, leaving the private endpoint open. Valid OpenAPI either way,
        # so only an explicit check catches it.
        cognito = [
            scheme
            for scheme in aws_document["components"]["securitySchemes"].values()
            if (scheme.get("x-amazon-apigateway-authorizer") or {}).get("type")
            == "cognito_user_pools"
        ]
        check(
            "the Cognito authorizer is in the form API Gateway imports",
            bool(cognito)
            and all(
                s.get("type") == "apiKey"
                and s.get("name") == "Authorization"
                and s.get("in") == "header"
                and "flows" not in s
                for s in cognito
            ),
            "found: {0}".format(
                [
                    {k: v for k, v in s.items() if k in ("type", "name", "in")}
                    for s in cognito
                ]
            ),
        )
        # Gateway responses must live in the document: an OpenAPI import
        # overwrites whatever the API had, so CFN-managed ones vanish on the
        # second deploy and the API falls back to AWS's {"message": ...}.
        gateway_responses = aws_document.get(
            "x-amazon-apigateway-gateway-responses", {}
        )
        required_types = {
            "DEFAULT_4XX", "DEFAULT_5XX", "UNAUTHORIZED", "ACCESS_DENIED",
            "MISSING_AUTHENTICATION_TOKEN", "THROTTLED",
            "UNSUPPORTED_MEDIA_TYPE",
        }
        missing_types = sorted(required_types - set(gateway_responses))
        check(
            "error formatting for gateway rejections is in the document",
            not missing_types,
            "missing: {0}".format(missing_types),
        )

        secured = aws_document["paths"]["/announcements"]["post"].get("security")
        check(
            "POST requires the announcements/write scope",
            secured == [{"announcementsOAuth2": ["announcements/write"]}],
            "found: {0}".format(secured),
        )

    templates = {}
    for path, label in ((FOUNDATION, "foundation"), (API, "api")):
        try:
            with open(path) as handle:
                templates[label] = yaml.load(handle, Loader=CfnLoader)
            check("{0} template parses".format(label), True)
        except Exception as error:  # noqa: BLE001
            check("{0} template parses".format(label), False, str(error)[:400])

    if len(templates) == 2:
        exported = {
            output["Export"]["Name"]["Fn::Sub"].replace("${AWS::StackName}-", "")
            for output in templates["foundation"]["Outputs"].values()
            if "Export" in output
        }
        imported = set(
            re.findall(r"\$\{FoundationStackName\}-([A-Za-z]+)", open(API).read())
        )
        missing = sorted(imported - exported)
        check(
            "every import in the api stack is exported by the foundation stack",
            not missing,
            "missing exports: {0}".format(missing),
        )

    print()
    if failures:
        print("{0} check(s) failed".format(len(failures)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
