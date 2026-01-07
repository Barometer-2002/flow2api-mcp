import argparse
import json
import os
import sys
from datetime import datetime

import httpx


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect OpenAI-compatible /v1/chat/completions responses.")
    parser.add_argument("--base-url", required=True, help="Upstream base URL, e.g. http://127.0.0.1:8000")
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument("--prompt", default="Generate an image of a cute cat.", help="User prompt")
    parser.add_argument("--stream", action="store_true", help="Use stream=true (SSE)")
    parser.add_argument("--timeout", type=float, default=300.0, help="Request timeout seconds")
    parser.add_argument("--out", default="", help="Write raw lines to this file path")
    args = parser.parse_args()

    api_key = os.environ.get("FLOW2API_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    if not api_key:
        print("Missing API key: set FLOW2API_API_KEY or OPENAI_API_KEY.", file=sys.stderr)
        return 2

    url = args.base_url.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": args.prompt}],
        "stream": bool(args.stream),
    }

    out_path = args.out.strip()
    out_f = None
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        out_f = open(out_path, "w", encoding="utf-8", errors="ignore")

    def write(line: str) -> None:
        print(line)
        if out_f is not None:
            out_f.write(line + "\n")

    write(f"[{_now()}] POST {url}")
    write(f"[{_now()}] model={args.model} stream={bool(args.stream)}")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    timeout = httpx.Timeout(args.timeout, connect=min(args.timeout, 10.0))

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        if args.stream:
            with client.stream("POST", url, headers=headers, json=payload) as resp:
                write(f"[{_now()}] status={resp.status_code}")
                if resp.status_code != 200:
                    write(resp.text[:4000])
                    return 1
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="ignore")
                    write(line)
        else:
            resp = client.post(url, headers=headers, json=payload)
            write(f"[{_now()}] status={resp.status_code}")
            if resp.status_code != 200:
                write(resp.text[:4000])
                return 1
            try:
                data = resp.json()
            except Exception:
                write(resp.text[:4000])
                return 1
            write(json.dumps(data, ensure_ascii=False, indent=2)[:20000])

    if out_f is not None:
        out_f.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

