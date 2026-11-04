# Deploying a public demo safely

Judges can always use **Recorded live run** mode with no key and no cost. A hosted live demo is optional.

## Streamlit Community Cloud (about 5 minutes)

1. Make `github.com/musharraf3/DataTrace` public.
2. Go to <https://share.streamlit.io>, sign in with GitHub, and click **Create app**.
3. Repository `musharraf3/DataTrace`, branch `main`, main file `app.py`.
4. Open **Advanced settings → Secrets** and paste the following. Never put the key in the repository.

   ```toml
   MODEL_API_KEY = "your-meta-key"
   DATATRACE_PUBLIC_DEMO = "1"
   DATATRACE_DAILY_LIVE_LIMIT = "60"
   ```

5. Deploy, then open the app URL in a private window to confirm it loads.

## What protects your credits

| Control | Effect |
| --- | --- |
| `DATATRACE_PUBLIC_DEMO=1` | 3 live investigations and 6 intake drafts per visitor session |
| `DATATRACE_DAILY_LIVE_LIMIT` | Shared daily cap across all visitors (default 60 runs, about $7/day at list prices) |
| Uploads in public mode | Uploaded data can only run offline; live mode uses the bundled synthetic incidents |
| Host lock | The key is sent only to `https://api.meta.ai/v1`; redirects are refused |
| Never displayed | The UI only says "Meta key configured"; the key is not logged or exported |
| Token ceiling | Each investigation stops after 250k tokens; 12 tool calls maximum |

Also set a **Spend notification** in the Meta API dashboard (Billing). It is a notification, not a hard cap, so keep the daily limit above as the real brake.

If you are not comfortable hosting a live key, deploy **without** `MODEL_API_KEY`. The app opens in Recorded live run mode, which replays real Meta agent runs captured from this app.

## Docker

```sh
docker build -t datatrace .
docker run --rm -p 127.0.0.1:8501:8501 --env-file .env datatrace
```

The image sets `DATATRACE_PUBLIC_DEMO=1` by default.
