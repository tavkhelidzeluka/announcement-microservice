#!/usr/bin/env python3
"""Merge the vendor-neutral API contract with its AWS API Gateway bindings.

    api/openapi.yaml                        the published contract, no AWS in it
  + infrastructure/openapi-aws-overlay.yaml the x-amazon-apigateway-* bindings
  = build/openapi.aws.yaml                  what API Gateway imports

Keeping the two apart is what lets the contract satisfy the guideline that API
definitions MUST be implementation/technology-agnostic while still being the
single source of truth for the deployment: there is no second, hand-maintained
description of the API that could drift.

Placeholders of the form ``${NAME}`` in the overlay are filled from --set
arguments, which the deploy script feeds from the foundation stack's outputs.
"""
import argparse
import hashlib
import json
import os
import re
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit(
        "PyYAML is required: pip install -r requirements-dev.txt "
        "(or run `make install`)"
    )

PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")


def deep_merge(base, overlay, path="$"):
    """Overlay wins on scalars; dicts merge; lists are replaced outright."""
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return overlay
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged:
            merged[key] = deep_merge(merged[key], value, "{0}.{1}".format(path, key))
        else:
            merged[key] = value
    return merged


def substitute(text, values):
    missing = sorted(
        {name for name in PLACEHOLDER.findall(text) if name not in values}
    )
    if missing:
        sys.exit(
            "Missing substitution value(s): {0}\n"
            "Pass them as --set NAME=value.".format(", ".join(missing))
        )
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


def strip_api_key_scheme(document, scheme_name="apiKey"):
    """Remove the ``Api-Key`` security scheme from the copy API Gateway imports.

    The scheme is correct and stays in the published contract, but on import
    API Gateway reads *any* `apiKey` security scheme as a request for its own
    usage-plan keys - which are hard-wired to the `x-api-key` header name that
    the guidelines override with `Api-Key`. Importing it would therefore switch
    on `apiKeyRequired` and reject every guideline-conforming request with a
    403 before it reached the handler, which validates the header itself.
    """
    schemes = (document.get("components") or {}).get("securitySchemes") or {}
    schemes.pop(scheme_name, None)

    def prune(requirements):
        pruned = []
        for requirement in requirements or []:
            remaining = {k: v for k, v in requirement.items() if k != scheme_name}
            # An empty requirement means "no security"; keep it only if the
            # original was already empty, otherwise drop it so the remaining
            # schemes on the operation still apply.
            if remaining or not requirement:
                pruned.append(remaining)
        return pruned

    if "security" in document:
        document["security"] = prune(document["security"])
    for operations in (document.get("paths") or {}).values():
        for operation in (operations or {}).values():
            if isinstance(operation, dict) and "security" in operation:
                operation["security"] = prune(operation["security"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default="api/openapi.yaml")
    parser.add_argument("--overlay", default="infrastructure/openapi-aws-overlay.yaml")
    parser.add_argument("--output", default="build/openapi.aws.yaml")
    parser.add_argument(
        "--set",
        dest="values",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Substitute ${NAME} in the overlay. Repeatable.",
    )
    parser.add_argument(
        "--print-hash",
        action="store_true",
        help="Print only the sha256 of the merged document and exit.",
    )
    args = parser.parse_args()

    values = {}
    for item in args.values:
        if "=" not in item:
            sys.exit("--set expects NAME=VALUE, got {0!r}".format(item))
        name, value = item.split("=", 1)
        values[name] = value

    with open(args.contract) as handle:
        contract = yaml.safe_load(handle)
    with open(args.overlay) as handle:
        overlay = yaml.safe_load(substitute(handle.read(), values))

    merged = deep_merge(contract, overlay)
    strip_api_key_scheme(merged)

    # API Gateway resolves `$ref` on import, but it rejects a document whose
    # `servers` block still carries unresolved variables it does not
    # understand. The deployed API is reached through its own invoke URL or a
    # custom domain, so the canonical Philips servers block is documentation
    # only and is dropped from the import copy.
    merged.pop("servers", None)

    body = yaml.safe_dump(merged, sort_keys=False, default_flow_style=False, width=120)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]

    if args.print_hash:
        print(digest)
        return

    directory = os.path.dirname(args.output)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(args.output, "w") as handle:
        handle.write(body)

    print(
        json.dumps(
            {"output": args.output, "sha256": digest, "bytes": len(body)}, indent=2
        )
    )


if __name__ == "__main__":
    main()
