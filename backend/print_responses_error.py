from __future__ import annotations

import json

from foundry_responses_client import _DEFAULT_DEPLOYMENT, _build_client, _env


def main() -> None:
    client = _build_client()
    deployment = _env("AZURE_FOUNDRY_DEPLOYMENT", _DEFAULT_DEPLOYMENT)

    print("client:", type(client))
    print("deployment:", deployment)

    try:
        resp = client.responses.create(
            model=deployment,
            input="Return the JSON object with root_cause='OK'.",
            max_output_tokens=60,
        )
        print("OK output_text:")
        print(getattr(resp, "output_text", None))
        try:
            raw = resp.model_dump() if hasattr(resp, "model_dump") else resp
            print("RAW:")
            print(json.dumps(raw, indent=2, ensure_ascii=False, default=str))
        except Exception as dump_err:
            print("raw_dump_error:", dump_err)
    except Exception as e:
        print("Exception type:", type(e))
        print("status_code:", getattr(e, "status_code", None))
        print("message:", getattr(e, "message", None))
        print("body:", getattr(e, "body", None))
        print("str:", str(e))


if __name__ == "__main__":
    main()
