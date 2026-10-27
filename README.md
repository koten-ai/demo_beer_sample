# The Sample Tap

Beer-sample catalog app. `static/index.html` is the page, the styles, and the script. `static/hero.jpg` is the hero photo. `main.py` is the same-origin catalog API.

Zeus stays on its public API, port **8080**. The page listens on port **8090**.

**`LLM_API_KEY` is required.** This sample works only after that variable is set in `.env`. `config.json` `llm.api_key_env` stays the name `LLM_API_KEY`. The secret belongs in `.env`. Restart the app after you set it. Pour and search stay off until the process has the key.

## Make the page work

1. Zeus is up at `http://localhost:8080` with bucket `beer-sample`, scope `_default`, collection `_default`, and mode `analytics`.

2. From this directory, install and configure:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`requirements.txt` installs FastAPI, uvicorn, python-dotenv, and `kotenai-zeus-client` (the `zeus_client_python` package) from PyPI at `kotenai-zeus-client>=2.5.3,<2.6`.

3. Set `LLM_API_KEY` in `.env`. This step is required. Leave `config.json` `llm.api_key_env` as the name `LLM_API_KEY`. `LLM_BASE_URL` defaults to `https://api.x.ai/v1` and `LLM_MODEL` to `grok-4.5-latest`. Other provider base URLs are in the Env section. `ZEUS_AUTH_MODE` defaults to `basic`. Set `ZEUS_USERNAME` and `ZEUS_PASSWORD` for basic auth. For bearer auth, set `ZEUS_AUTH_MODE` to `bearer` and set `ZEUS_BEARER_TOKEN`.

4. Start the app:

```bash
python main.py
```

`python main.py` binds `127.0.0.1` and port `8090`. Set `PORT` to change the port and `HOST` to change the bind address. Restart the process after any `.env` change. The page is already in `static/`.

On startup the app calls `catalog.sync()` and writes `data/chat_requests/beer-sample__default/chat_request_analytics_v2.json` from the live Zeus pin (`chat_request_analytics_base-6.1.json` today). That directory is gitignored. It survives a process restart. A missing catalog makes Pour return HTTP 502. It does not answer with empty `req_ids`.

5. Open [http://127.0.0.1:8090/](http://127.0.0.1:8090/).

## Docker

Copy `.env.example` to `.env` and set `LLM_API_KEY` and `ZEUS_PASSWORD` first. Compose publishes `8090`, sets `HOST=0.0.0.0`, and points `ZEUS_URL` at `http://host.docker.internal:8080` so the container reaches Zeus on the host. Hub `:9091` is the wrong port. `./.env` and `./data` are bind-mounted. The app reads `.env` with python-dotenv, so a `$` in a password is unchanged. The synced catalog survives a container restart. `.env` and `data/` are not copied into the image.

```bash
docker compose up --build
```

Open [http://127.0.0.1:8090/](http://127.0.0.1:8090/). To point the container at another public `:8080` URL, change the `ZEUS_URL` entry in `docker-compose.yml`.

`GET /healthz` returns `{"status":"ok","sample":"beer"}` when the process is up.

## On the page

- **Beers** loads 24 cards.
- **Breweries** loads the brewery list and hides the style chips.
- **All** clears the box and reloads the beer list.
- A style chip, or **Pour**, sends the box text to search. Both need `LLM_API_KEY` in the running process. The line under the box gives the reason when the key is missing.
- The box keeps the question. [http://127.0.0.1:8090/search?q=Duvel](http://127.0.0.1:8090/search?q=Duvel) opens that search. `?entity=brewery` opens on Breweries. `?page=2` asks for the next list page. Next stays hidden when the catalog repeats page 1.
- A result with no beer or brewery name shows the empty state.

Queries that match this catalog: `IPA`, `Porter`, `Duvel`, and `What beers are made from fruits?`.

Style chips: All, IPA, Porter, Stout, Pale Ale, Lager, Pilsner, Wheat, Belgian, Amber, Brown Ale, Hefeweizen, Barleywine.

## Routes the page calls

| Request | When |
| --- | --- |
| `GET /api/config` | Page load. Fills the host, scope, and kicker. `pour_enabled` turns Pour on. |
| `GET /api/beers?limit=24` | Beer list. `offset` is sent from page 2 onward, after paging is on. |
| `GET /api/breweries?limit=24` | Brewery list. Same paging. |
| `GET /api/search?q=…&limit=24` | Pour. Brewery mode adds `entity=Brewery`. An empty box reloads the list. |

Cards use `name`. Beer lines use `style` and `brewery`. Brewery lines use `city`, `state`, and `country`. `abv` draws the badge when it is a number other than zero.

## Env

| Variable | Default | Notes |
| --- | --- | --- |
| `ZEUS_URL` | `http://localhost:8080` | Public API |
| `ZEUS_BUCKET` | `beer-sample` | |
| `ZEUS_SCOPE` | `_default` | |
| `ZEUS_COLLECTION` | `_default` | |
| `ZEUS_MODE` | `analytics` | |
| `HOST` | `127.0.0.1` | Bind address for `python main.py`. Compose sets `0.0.0.0` |
| `PORT` | `8090` | Page port |
| `ZEUS_AUTH_MODE` | `basic` | `basic` or `bearer`. `config.json` names this env var |
| `ZEUS_USERNAME` | `tester_beer` | Basic auth user.  An empty name falls back to `tester` |
| `ZEUS_PASSWORD` | | Basic auth password. `config.json` `password_env` is `ZEUS_PASSWORD`. Only in the environment |
| `ZEUS_BEARER_TOKEN` | | Token used when `ZEUS_AUTH_MODE` is `bearer` |
| `LLM_BASE_URL` | `https://api.x.ai/v1` | Provider base URL. Values are below |
| `LLM_API_KEY` | | **Required.** The sample works only after this is set in `.env`. `llm.api_key_env` stays the name `LLM_API_KEY` |
| `LLM_MODEL` | `grok-4.5-latest` | Model for the provider in `LLM_BASE_URL` |

`config.json` stores `ZEUS_AUTH_MODE`, `ZEUS_USERNAME`, and `ZEUS_MODE` for auth mode, user, and Zeus mode. Startup fills those from the environment before the client reads the file.

`LLM_BASE_URL` values from `.env.example`:

| Provider | Base URL |
| --- | --- |
| Grok | `https://api.x.ai/v1` |
| OpenAI | `https://api.openai.com/v1` |
| Anthropic | `https://api.anthropic.com/v1` |
| Gemini (OpenAI-compatible) | `https://generativelanguage.googleapis.com/v1beta/openai/` |

Search calls `{LLM_BASE_URL}/chat/completions`. Set `LLM_MODEL` to a model that base URL serves.

## Docs

- [Beer-sample search](https://docs.koten.ai/zeus-client/beer-sample-search/)
- [Using Zeus Client](https://docs.koten.ai/zeus-client/using-zeus-client)
