# The Sample Tap

UI template for the beer-sample catalog. `static/index.html` is the page, the styles, and the script. `static/hero.jpg` is the hero photo.

The page calls a same-origin catalog API. That server is the beer catalog app in `../demo_beer_sample`. Zeus stays on its public API, port **8080**. The page listens on port **8090**.

**`LLM_API_KEY` is required.** This sample works only after that variable is set in the catalog app `.env`. `config.json` `llm.api_key_env` stays the name `LLM_API_KEY`. The secret belongs in `.env`. Restart the app after you set it. Pour and search stay off until the process has the key.

## Make the page work

1. Zeus is up at `http://localhost:8080` with bucket `beer-sample`, scope `_default`, collection `_default`, and mode `analytics`.

2. From the catalog app, install and configure:

```bash
cd ../demo_beer_sample
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

3. Set `LLM_API_KEY` in `.env`. This step is required. Leave `config.json` `llm.api_key_env` as the name `LLM_API_KEY`.

4. Copy this template over the app's static files, then start it:

```bash
cp ../beer-sample-temp/static/index.html ../beer-sample-temp/static/hero.jpg static/
python main.py
```

`python main.py` binds `127.0.0.1` and port `8090`. Set `PORT` to change the port and `HOST` to change the bind address. Restart the process after any `.env` change.

5. Open [http://127.0.0.1:8090/](http://127.0.0.1:8090/).

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

## Catalog app env

| Variable | Default | Notes |
| --- | --- | --- |
| `ZEUS_URL` | `http://localhost:8080` | Public API |
| `ZEUS_BUCKET` | `beer-sample` | |
| `ZEUS_SCOPE` | `_default` | |
| `ZEUS_COLLECTION` | `_default` | |
| `ZEUS_MODE` | `analytics` | |
| `HOST` | `127.0.0.1` | Bind address for `python main.py` |
| `PORT` | `8090` | Page port |
| `LLM_API_KEY` | | **Required.** The sample works only after this is set in `.env`. `llm.api_key_env` stays the name `LLM_API_KEY` |
| `LLM_BASE_URL` | `https://api.x.ai/v1` | |
| `LLM_MODEL` | `grok-4.5-latest` | Default Grok model |
| `ZEUS_USERNAME` / `ZEUS_PASSWORD` | | Optional basic auth |
| `ZEUS_BEARER_TOKEN` | | Optional bearer |

## Docs

- [Beer-sample search](https://docs.koten.ai/zeus-client/beer-sample-search/)
- [Using Zeus Client](https://docs.koten.ai/zeus-client/using-zeus-client)
