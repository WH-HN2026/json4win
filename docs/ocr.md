# OCR engine: Unlimited-OCR-2 on CPU (task P1), Tesseract backend (task P4), LightOnOCR-2-1B benchmark backend (task P5), hybrid mode (task P7), LightOnOCR-2-1B through an EU/EEA API (task P8)

Code: [`json4win/json4win/ocr.py`](../json4win/json4win/ocr.py) (contract, backend dispatcher, rendering,
shared cache, local text cleaning), [`ocr_engine.py`](../json4win/json4win/ocr_engine.py) (Unlimited-OCR-2
model load + inference), [`ocr_fast.py`](../json4win/json4win/ocr_fast.py) (opt-in faster decode),
[`ocr_tesseract.py`](../json4win/json4win/ocr_tesseract.py) (Tesseract CLI backend via `subprocess`),
[`ocr_lighton.py`](../json4win/json4win/ocr_lighton.py) (LightOnOCR-2-1B, benchmark-only),
[`ocr_api.py`](../json4win/json4win/ocr_api.py) (LightOnOCR-2-1B through an EU/EEA OpenAI-compatible API). Dev tools:
[`scripts/ocr_cache.py`](../scripts/ocr_cache.py) (`make ocr-cache`), [`scripts/ocr_probe.py`](../scripts/ocr_probe.py) (gate bench + quality probe).

## Backendy OCR

Wybór backendu odbywa się zmienną środowiskową `OCR_BACKEND` (w `.env.local` lub w środowisku):

- **`OCR_BACKEND=local` (domyślny):** `baidu/Unlimited-OCR-2` (MIT) uruchamiany lokalnie na CPU
  przez `json4win.ocr_engine`. Najwyższa jakość rozpoznawania na skanach (szczególnie tabele i układ),
  ale ok. 9–11 GB RAM i ~45–90 s/stronę.
- **`OCR_BACKEND=tesseract`:** Tesseract OCR (licencja **Apache 2.0**, w pełni open source) wywoływany
  bezpośrednio z biblioteki standardowej Pythona (`subprocess.run` z listą argumentów, bez shella,
  bez dodatkowych pakietów Pythona) przez `json4win.ocr_tesseract`. Strony są renderowane przez
  `pypdfium2` (domyślnie 300 dpi) i przekazywane na `stdin` jako PNG. Bardzo szybki (~1 s/stronę,
  niski RAM), ale wrażliwszy na układ dwukolumnowy/tabele i drobne skazy skanów (porównanie w
  [`docs/quality.md`](quality.md)).
- **`OCR_BACKEND=lighton` (tylko benchmark):** `lightonai/LightOnOCR-2-1B` (Apache 2.0, ~1B parametrów) na CPU
  przez `json4win.ocr_lighton`. Wymaga transformers 5, więc działa tylko w osobnym venv `.venv-lighton`
  (sekcja niżej); nie jest częścią dostawy.
- **`OCR_BACKEND=lighton_api` (task P8):** ten sam `LightOnOCR-2-1B`, ale przez API zgodne z OpenAI u dostawcy w UE
  (IONOS AI Model Hub lub EUrouter) przez `json4win.ocr_api`; tylko biblioteka standardowa (`urllib`), bez nowych
  zależności. Strona, dla której API zawiedzie, idzie do `OCR_API_FALLBACK` (domyślnie `tesseract`). Sekcja niżej.
- **`OCR_BACKEND=hybrid` (task P7, domyślnie też tylko benchmark):** pierwsze `OCR_HYBRID_FIRST_PAGES` stron czyta
  `OCR_HYBRID_FIRST` (domyślnie `lighton`), każdą następną `OCR_HYBRID_REST` (domyślnie `tesseract`). Sekcja niżej.
- Nieznana wartość `OCR_BACKEND` podnosi `ValueError`.

### Zmienne dla `OCR_BACKEND=tesseract`

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `OCR_BACKEND` | `local` | `local` \| `tesseract` \| `lighton` \| `lighton_api` \| `hybrid` |
| `OCR_TESSERACT_CMD` | `tesseract` | Nazwa lub pełna ścieżka pliku wykonywalnego Tesseract |
| `OCR_TESSERACT_LANG` | `pol` | Język(i) przekazane przez `-l` (np. `pol` lub `pol+eng`) |
| `OCR_TESSERACT_DPI` | `300` | Rozdzielczość renderowania `pypdfium2` oraz flaga `--dpi` |
| `OCR_TESSERACT_PSM` | *(puste = domyślne, PSM 3)* | Tryb segmentacji strony `--psm` (0–13) |
| `OCR_TESSDATA_DIR` | `<cache_dir>/tessdata` | Katalog z plikami `<lang>.traineddata` przekazywany przez `--tessdata-dir` |

### Instalacja Tesseracta i danych `pol.traineddata`

- **Linux:** zainstaluj pakiet systemowy `tesseract-ocr` (lub `tesseract`). Jeżeli brakuje pakietu
  językowego `tesseract-ocr-pol` (lub brak uprawnień roota), pobierz oficjalny model
  [`pol.traineddata` z `tesseract-ocr/tessdata_best`](https://github.com/tesseract-ocr/tessdata_best/raw/main/pol.traineddata)
  (Apache 2.0, ~12 MB) do `~/.cache/json4win/tessdata/pol.traineddata` (pliki `.traineddata` nie są
  commitowane do repozytorium). Można też użyć lżejszego `tessdata_fast` (~4,6 MB) w osobnym katalogu
  i wskazać go przez `OCR_TESSDATA_DIR`.
- **Windows:** pobierz instalator **UB Mannheim** (`https://github.com/UB-Mannheim/tesseract/wiki`,
  Tesseract na licencji Apache 2.0). Podczas instalacji zaznacz dodatkowy pakiet językowy **Polish**
  (`pol`), albo pobierz `pol.traineddata` z `tesseract-ocr/tessdata_best` do
  `%LOCALAPPDATA%\json4win\tessdata\pol.traineddata`. Jeżeli `tesseract.exe` nie jest w `PATH`, ustaw
  `OCR_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`; jeśli chcesz użyć katalogu z
  instalatora zamiast cache, ustaw `OCR_TESSDATA_DIR=C:\Program Files\Tesseract-OCR\tessdata`.

### Separacja cache między backendami

Każdy backend zapisuje surowe wyniki w `json4win.env.cache_dir()/ocr/<settings_id>/<sha256>/<page>.json`
wraz z plikiem `settings.json`:

- Dla `local` format klucza (`settings_id`) pozostał **identyczny** z dotychczasowym (`0fe4b22967e4791d`
  dla ustawień domyślnych), więc istniejący cache Unlimited-OCR-2 jest w pełni zachowany.
- Dla `tesseract` klucz obejmuje `backend: "tesseract"`, linię wersji z `tesseract --version`, `lang`,
  `dpi`, `psm`, `format` oraz skrót sha256 użytych plików `<lang>.traineddata` (`tessdata_sha256`).
  Dzięki temu wyniki `local` i `tesseract` — a także różne wersje Tesseracta, `tessdata_best` vs
  `tessdata_fast`, różne `dpi`/`psm`/`lang` — nigdy się nie mieszają.
- Dla `lighton` klucz to same stałe i ustawienia (`backend`, `model`, `revision`, `dpi`, `longest_side`, `resize`,
  `decoding`, `max_tokens`, `dtype`, `format`), bez wersji torch/transformers, więc główny `.venv` (transformers
  4.52.1) czyta cache LightOnOCR z `OCR_CACHE_ONLY=1`. Domyślny `settings_id`: `13f6697c5daa30bf`.
- Dla `lighton_api` klucz to `backend`, sam host z `OCR_API_BASE_URL` (np. `openai.inference.de-txl.ionos.com`),
  `model`, `dpi`, `longest_side`, `resize`, `image_format`, `prompt` (brak), `max_tokens`, `temperature`, `top_p`,
  `extra_body` (sparsowany `OCR_API_EXTRA_BODY`) i `format`. Bez klucza API, timeoutu, liczby prób i fallbacku (nie
  zmieniają wyniku). IONOS i EUrouter mają więc osobne cache, choć to ten sam model u tego samego dostawcy.
- Ślad ekstrakcji (`trace.py`) zapisuje pole `backend` przy każdej przeczytanej stronie w `ocr_pages`: backend, który
  **faktycznie** przeczytał stronę; gdy API zawiodło i stronę przeczytał fallback, dochodzi `fallback_from: "lighton_api"`
  (w `.trace.md`: `tesseract zamiast lighton_api`).

### `OCR_BACKEND=lighton`: LightOnOCR-2-1B (tylko benchmark, task P5)

**Dlaczego tylko benchmark:** model jest w transformers dopiero od wersji 5 (`LightOnOcrForConditionalGeneration`,
`LightOnOcrProcessor`, `model_type` mistral3), a `json4win/requirements.txt` przypina `transformers==4.52.1` dla
zdalnego kodu Unlimited-OCR-2 (`trust_remote_code`; tę wersję przypina karta modelu, na transformers 5 nie był
testowany). Dlatego oba modele nie dzielą jednego venv. Na transformers < 5 `ocr_lighton` podnosi `RuntimeError("LightOnOCR needs transformers>=5 …: use
.venv-lighton, see docs/ocr.md")`, zanim cokolwiek zaimportuje.

**Venv (3 polecenia, z katalogu głównego repo):**

```bash
uv venv --python 3.13 .venv-lighton
uv pip install --index-strategy unsafe-best-match --python .venv-lighton/bin/python -r requirements-lighton.txt
OCR_BACKEND=lighton .venv-lighton/bin/python scripts/eval_skany.py -v   # wypełnia cache (jeden proces OCR)
```

`requirements-lighton.txt` (dev): te same torch/torchvision CPU co aplikacja, `transformers==5.24.0`,
`tokenizers==0.23.3`, `huggingface-hub==2.4.0`, plus PyYAML/pypdfium2/pillow/numpy. Pierwsze uruchomienie pobiera
~2 GB wag (bf16 safetensors) z rewizji `be7c41313c30e940fe5571de59e5fabc779e00c8`. Potem porównania LLM idą z
głównego `.venv` z `OCR_BACKEND=lighton OCR_CACHE_ONLY=1`.

**Jak działa:** strona renderowana przez pypdfium2 w 200 dpi i zmniejszana (LANCZOS, proporcje zachowane) do
dłuższego boku 1540 px (zalecenia z karty modelu); jedno wywołanie `generate()` na stronę, **greedy**
(`do_sample=False`; `generation_config.json` modelu losuje z temperaturą 0.2), maks. `OCR_LIGHTON_MAX_TOKENS`
(domyślnie 4096) tokenów. Prompt to sam obraz (szablon czatu modelu nie ma tekstu polecenia), ~2150 tokenów
wejścia na stronę A4. Wyjście to markdown (nagłówki `#`, `**pogrubienia**`, tabele markdown lub HTML,
`![obraz](…)`); w cache zapisywany jest surowy markdown, a `ocr_lighton.clean_text()` robi z niego tekst
(tabele: komórki rozdzielone ` | `, obrazki i linie `---` usunięte, etykiety linków zostają, wypełniacz
`*(blank)*` usunięty, `\-` → `-`).

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `OCR_LIGHTON_DTYPE` | `bf16` | `bf16` \| `fp32`. Na stronie testowej (`potwierdzenia/0001`, 675 tokenów) tekst identyczny; bf16 59–61 s vs fp32 91–95 s, RSS 2,9 vs 6,3 GB. Ten CPU (Ryzen 9 7900X) ma AVX512-BF16; bez niego bf16 może być wolniejszy niż fp32 (jak przy Unlimited-OCR-2) |
| `OCR_LIGHTON_MAX_TOKENS` | `4096` | Limit tokenów wyjścia na stronę (wartość z karty modelu) |
| `OCR_THREADS` | rdzenie fizyczne | Wspólne z `local`; 8 vs 12 wątków: bez różnicy w czasie |

**Co trzeba by zrobić, żeby go dostarczyć:** (a) przejść całą aplikację na transformers 5 i porzucić
Unlimited-OCR-2 albo przenieść jego zdalny kod na transformers 5 (nietestowane, czy działa bez zmian), albo (b) uruchamiać LightOnOCR jako osobny
proces z własnym venv (dwa zestawy zależności w dostawie, `start.bat` musiałby tworzyć drugi venv). Do tego pomiar
na laptopie AVX2 bez AVX512-BF16 (wybór `fp32` vs `bf16`) i ochrona przed pętlami dekodowania greedy (np.
`no_repeat_ngram_size` jak w `local`). Wyniki: [`quality.md`](quality.md), sekcja "Real scans: LightOnOCR-2-1B".

### `OCR_BACKEND=hybrid`: LightOnOCR na początek, Tesseract na resztę (task P7)

Nagłówek każdej klasy (strony, NIP/KRS, e-maile, sygnatury) jest na stronie 1, a tam LightOnOCR czyta najlepiej;
dalsze strony odwołania (uzasadnienie, terminy) czyta Tesseract w ~1 s/stronę. Tryb jest wyłącznie w dispatcherze
`json4win.ocr`: `page_backend(index)` mówi, który backend czyta daną stronę, a `ocr_page` / `is_cached` /
`cache_path` / `ocr_page_entry` biorą ustawienia tego backendu (`active_settings(index)`). Pipeline, `decide` i
skrypty się nie zmieniają: klasyfikacja dostaje stronę 1 (tekst LightOnOCR), a znaczniki czytania i ekstrakcja
strony sklejone w kolejności, tak jak dla jednego backendu.

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `OCR_HYBRID_FIRST` | `lighton` | Backend pierwszych stron: `local` \| `tesseract` \| `lighton` \| `lighton_api` |
| `OCR_HYBRID_REST` | `tesseract` | Backend każdej dalszej strony: `local` \| `tesseract` \| `lighton` \| `lighton_api` |
| `OCR_HYBRID_FIRST_PAGES` | `1` | Ile stron czyta `OCR_HYBRID_FIRST` (liczba całkowita ≥ 1) |

- **Cache:** każda strona idzie do przestrzeni swojego backendu z jego ustawieniami (`OCR_LIGHTON_*`,
  `OCR_TESSERACT_*`, `OCR_*` dla `local`), więc hybryda trafia w wpisy zapisane wcześniej przez `OCR_BACKEND=lighton`
  i `OCR_BACKEND=tesseract` (te same `settings_id`, te same klucze stron); nie ma osobnej przestrzeni `hybrid`.
- **Ślad:** `trace.py` zapisuje w `ocr_pages[*].backend` backend, który przeczytał daną stronę (`lighton`, `tesseract`).
- **Błędy:** nieznany backend w `OCR_HYBRID_FIRST`/`_REST` (także `hybrid`) albo `OCR_HYBRID_FIRST_PAGES` < 1 lub
  niebędące liczbą → `ValueError` z nazwą zmiennej przy pierwszej czytanej stronie (jak nieznany `OCR_BACKEND`).
  Gdy `OCR_BACKEND` ≠ `hybrid`, zmienne `OCR_HYBRID_*` są ignorowane, a dispatcher woła tylko wybrany backend.
- **Uruchomienie:** z domyślnym `lighton` na początek tylko w `.venv-lighton` (transformers 5; ten venv ma już wszystko,
  czego potrzebuje reszta pipeline'u: PyYAML, pypdfium2, pillow, a LLM idzie przez `urllib`). Tesseract to binarka
  systemowa jak przy `OCR_BACKEND=tesseract`. Z `OCR_CACHE_ONLY=1` hybrydę czyta też główny `.venv`.

  ```bash
  OCR_BACKEND=hybrid OCR_CACHE_ONLY=1 .venv-lighton/bin/python scripts/eval_skany.py -v
  ```
- **Co by trzeba, żeby ją dostarczyć, i czas:** [`quality.md`](quality.md), sekcja "Real scans: hybrid OCR".

### `OCR_BACKEND=lighton_api`: LightOnOCR-2-1B przez API w UE/EOG (task P8)

**Po co:** serwer dostawy ma 2 rdzenie CPU, więc lokalny LightOnOCR (~60 s/stronę na 12 rdzeniach) jest za wolny.
Ten sam model z otwartymi wagami (`lightonai/LightOnOCR-2-1B`, Apache 2.0, LightOn, Francja) jest serwowany w UE
przez chat completions zgodne z OpenAI z obrazem na wejściu (decyzja użytkownika 2026-11-22, AGENTS.md "OCR always").

**Włączenie** (w `json4win/.env.local`):

```bash
# IONOS AI Model Hub (IONOS SE, Berlin): domyślne URL i model
OCR_BACKEND=lighton_api
OCR_API_KEY=<token IONOS AI Model Hub>

# albo EUrouter (EUrouter B.V., Amsterdam; bramka kierująca do IONOS Cloud)
OCR_BACKEND=lighton_api
OCR_API_KEY=<klucz EUrouter>
OCR_API_BASE_URL=https://api.eurouter.ai/api/v1
OCR_API_MODEL=lightonocr-2-1b
OCR_API_EXTRA_BODY={"provider": {"only": ["ionos"], "allow_fallbacks": false, "zdr": true, "max_retention_days": 0}}

# hybryda: strona 1 przez API, dalsze Tesseractem (Tesseract musi być zainstalowany)
OCR_BACKEND=hybrid
OCR_HYBRID_FIRST=lighton_api
```

**Dostawcy i limity:**

| | IONOS AI Model Hub | EUrouter |
|---|---|---|
| Firma, siedziba | IONOS SE, Niemcy (centrum `de-txl`, Berlin) | EUrouter B.V., Holandia; model serwuje IONOS Cloud |
| Base URL | `https://openai.inference.de-txl.ionos.com/v1` (domyślny) | `https://api.eurouter.ai/api/v1` |
| Model | `lightonai/LightOnOCR-2-1B` (domyślny) | `lightonocr-2-1b` (jest też `lightonocr-3-0.8b` na Scaleway, wejście "file": nieobsługiwane tutaj) |
| Wejście | obraz PNG/JPEG/WebP jako data URI `data:image/png;base64,…` lub URL | jak IONOS (obraz → tekst) |
| Limity | ciało żądania ≤ 16 MiB, jeden obraz inline ≤ 12 MiB; żądania > 4 MiB maks. 2 naraz (HTTP 503 + `Retry-After`) | — |
| Cena | wg cennika IONOS | 0,15 EUR / M tokenów wejścia, 0,30 EUR / M tokenów wyjścia |
| Dokumentacja | [docs.ionos.com: OCR](https://docs.ionos.com/cloud/ai/ai-model-hub/how-tos/ocr) | [eurouter.ai](https://eurouter.ai) |

EUrouter przyjmuje w ciele żądania obiekt `provider`; `OCR_API_EXTRA_BODY` (obiekt JSON scalany z każdym żądaniem,
na końcu, więc może też nadpisać np. `max_tokens`) przypina dostawcę (`only: ["ionos"]`, bez przełączania na innych:
`allow_fallbacks: false`) i prosi o brak retencji danych (`zdr: true`, `max_retention_days: 0`). Nieprawidłowy JSON
albo coś innego niż obiekt → `ValueError` od razu, przy pierwszej stronie (bez fallbacku).

**Jak działa:** strona renderowana w 200 dpi i zmniejszana do dłuższego boku 1540 px tym samym kodem co `lighton`
(`ocr_lighton.resize`, LANCZOS: na tym rozmiarze model był trenowany), zapisywana jako PNG (6 stron z `dane/skany`: 0,35–1,55 MB PNG,
data URI ≤ 2,1 MB, więc poniżej progu 4 MiB IONOS), wysyłana jako data URI w jednej wiadomości `user`, której treścią jest **tylko obraz**
(jak w przykładzie IONOS i w szablonie czatu modelu). Wyjście (markdown) idzie do cache surowe, a tekst robi z niego
`ocr_lighton.clean_text()`, jak dla `lighton`. Wpis cache ma `seconds` (czas żądania, z ponownymi próbami),
`tokens` / `prompt_tokens` (z `usage` odpowiedzi), `attempts`, `image_bytes`, `model_image_size`, `finish`.

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `OCR_API_KEY` | *(puste)* | Klucz API (Bearer). Nigdy nie jest logowany ani zapisywany (nie ma go w kluczu cache, w błędach jest maskowany, `trace.scrub` go usuwa). Puste → każda strona idzie do fallbacku z ostrzeżeniem |
| `OCR_API_BASE_URL` | IONOS (wyżej) | Base URL API zgodnego z OpenAI; dopisywane `/chat/completions` |
| `OCR_API_MODEL` | `lightonai/LightOnOCR-2-1B` | Id modelu u dostawcy |
| `OCR_API_EXTRA_BODY` | *(puste)* | Obiekt JSON scalany z ciałem żądania (EUrouter: `provider`) |
| `OCR_API_MAX_TOKENS` | `4096` | Limit tokenów wyjścia na stronę (karta modelu, przykład IONOS) |
| `OCR_API_TEMPERATURE` | `0` | Temperatura; `0` = greedy, jak backend `lighton` (przykład IONOS: `0.2`) |
| `OCR_API_TOP_P` | `1` | top_p (przykład IONOS: `0.9`; przy temperaturze 0 bez znaczenia) |
| `OCR_API_TIMEOUT` | `20` | Sekundy na jedno żądanie (timeout `urllib` na operację gniazda; serwer sączący bajty wolniej mógłby go przekroczyć) |
| `OCR_API_RETRIES` | `1` | Ponowne próby po 429, 5xx, timeoucie, błędzie połączenia lub niepoprawnym JSON-ie; czeka `Retry-After` (sekundy albo data HTTP), a bez niego 2, 4… s, zawsze **maks. 5 s** (`MAX_RETRY_DELAY`). Inne 4xx (zły klucz, zły model) → bez ponawiania |
| `OCR_API_FALLBACK` | `tesseract` | Backend, który czyta stronę, gdy API zawiedzie po wszystkich próbach: `tesseract` \| `local` \| `lighton` \| `none` (`none` = błąd strony jak w innych backendach, dokument kończy się `{}`) |

**Wybór temperatury (niezmierzony):** domyślnie `0` (greedy), bo tak dekoduje nasz lokalny backend `lighton`, którego
jakość na `dane/skany` jest zmierzona w [`quality.md`](quality.md), a wynik jest powtarzalny między uruchomieniami
(cache, eval). Przykład IONOS i `generation_config.json` modelu używają `0.2` / `0.9`; nie porównaliśmy tego na żywo
(brak klucza w czasie taska P8). Każda zmiana temperatury/top_p to nowa przestrzeń cache.

**Fallback:** gdy `run()` podniesie `OcrApiError` (brak klucza, HTTP 4xx, wyczerpane próby, odpowiedź bez `choices`,
pusta albo złożona z samych białych znaków odpowiedź 200),
strona jest czytana przez `OCR_API_FALLBACK` z **jego** ustawieniami, renderowaniem (Tesseract: 300 dpi) i cache, a log
dostaje ostrzeżenie `OCR [lighton_api] <plik> page N failed (…); reading it with tesseract`. Tekst z fallbacku nigdy nie
trafia do cache API, więc następne uruchomienie znów spróbuje API. Fallback działa też w hybrydzie (dla stron
czytanych przez `lighton_api`). Błędy konfiguracji (`OCR_API_*` z niepoprawną wartością, `OCR_API_FALLBACK=lighton_api`)
nie przechodzą w fallback, tylko od razu podnoszą `ValueError`. Z `OCR_CACHE_ONLY=1` brak wpisu API to `OcrCacheMiss`
(bez fallbacku), więc eval z cache nigdy nie miesza po cichu tekstu Tesseracta z tekstem API.

**Ochrona danych:** obraz strony (a więc dane osobowe z odwołań, pełnomocnictw i potwierdzeń przelewu) wychodzi do
dostawcy w UE/EOG: IONOS SE (Niemcy) bezpośrednio albo przez EUrouter B.V. (Holandia) do IONOS Cloud. Oba podmioty są
w UE, więc dane nie opuszczają EOG; przy EUrouterze `OCR_API_EXTRA_BODY` z `zdr: true` / `max_retention_days: 0`
prosi o brak retencji, a `only: ["ionos"]` + `allow_fallbacks: false` blokuje przekierowanie do innego dostawcy.
Dla zastosowania produkcyjnego potrzebna jest umowa powierzenia (DPA, art. 28 RODO) z dostawcą. Zasada repo: danych
treningowych `dane/przyklad_*` nie wysyłamy do API; do pomiarów służą wyłącznie skany z `dane/skany`.

**Budżet czasu (serwer jury: 2 rdzenie, 45 min na 150 PDF-ów):**

- **Najgorszy przypadek na stronę** przed przejściem na fallback: `(OCR_API_RETRIES + 1) × OCR_API_TIMEOUT +
  OCR_API_RETRIES × 5 s` = 2 × 20 s + 5 s = **45 s** przy domyślnych (`ocr_api.worst_case_seconds()`; test z
  wiszącym endpointem i sztucznym zegarem). Szybki błąd (503/429 bez zawieszenia, odmowa połączenia): ≤ 5 s;
  brak klucza, 401/400: od razu.
- **Bezpiecznik (circuit breaker):** po `BREAKER_FAILURES` = 3 kolejnych stronach z błędem API (dowolnym, który
  uruchamia fallback, także pusta odpowiedź i brak klucza) proces nie woła już API do końca uruchomienia: jedno
  ostrzeżenie `OCR API: 3 pages in a row failed, not calling it again in this run…`, a każda dalsza strona idzie od
  razu do `OCR_API_FALLBACK` (bez renderowania dla API, log INFO). Udana strona zeruje licznik. Z
  `OCR_API_FALLBACK=none` otwarty bezpiecznik daje od razu błąd strony.
- **API niedostępne od początku:** strata ≤ 3 × 45 s = **135 s** na całe uruchomienie, gdy endpoint wisi; ≈ 3 × 5 s
  = 15 s, gdy odpowiada błędem 5xx/429; ~0 s przy braku klucza lub złym kluczu. Reszta stron jak przy
  `OCR_BACKEND=tesseract`.
- Pusta odpowiedź liczy się jako błąd, więc kilka pustych stron (np. pusty rewers skanu) z rzędu też otworzy
  bezpiecznik; czytamy tylko pierwsze strony dokumentów, więc to mało prawdopodobne.

**Tryb jednego procesu:** żądania idą po jednym (pipeline czyta strony sekwencyjnie), więc limit 2 równoczesnych
dużych żądań IONOS nie jest problemem; 503 z `Retry-After` jest obsługiwane i tak.

## How it works

- **Model:** `baidu/Unlimited-OCR-2`, pinned revision `cb16b920ec2249c4b280f3aa67942e00b5099122` (2026-11-16),
  MIT, ~6.7 GB of bf16 safetensors downloaded by `transformers`/`huggingface_hub` on first use into the HF cache
  (`~/.cache/huggingface/hub`, `HF_HOME` overrides). Loaded lazily, once per process.
- **Rendering:** pypdfium2 (pip wheel, Windows/Linux), 200 dpi RGB. The model resizes to a 1024 px global view +
  640 px tiles (gundam mode: 2×3 tiles for A4, 903 image tokens), so more dpi buys nothing.
- **Inference:** the model's own `infer()` with the only documented prompt (`Multi page parsing.`), one page per
  call, greedy, no-repeat-ngram 35 / window 128 (model card values), max 3000 output tokens per page
  (dense A4 ≈ 1300–1600).
- **CPU patches (no fork of the remote code):** (1) transformers' import check refuses the remote code because one
  file imports `triton`; `triton` is filtered out of that check (the code uses it only on CUDA tensors);
  (2) `Tensor.cuda` becomes a no-op when CUDA is absent (the vision merge calls `.cuda()` on a mask);
  (3) the model's debug `print()`s are swallowed.
- **dtype:** vision encoder (SAM + CLIP) in **fp32**, decoder in **bf16** (`OCR_DTYPE=mixed`, default). bf16
  convolutions are ~5× slower on CPUs without AVX512-BF16 (prefill 52 s → 9 s); fp32 for everything needs ~14 GB.
- **Output → text:** the model emits layout markup (`<BLOCK>text[x1, y1, x2, y2]<FORK>…`, markdown links, `**`).
  The **raw** output is cached and cleaned on read by `clean_text()` (one block per line, link labels kept,
  e.g. `[DA.ZP.242.50.2026](mailto:…)` → `DA.ZP.242.50.2026`), so a cleaner change never needs a re-OCR.
- **Cache:** `json4win.env.cache_dir()/ocr/<settings id>/<sha256 of PDF>/<page>.json`, written atomically.
  The settings id hashes model, revision, prompt, dpi, mode, max tokens, n-gram, dtype, fast-decode level and a
  format version (`settings.json` in each settings dir lists them). Changing any `OCR_*` setting below starts a
  new, empty cache. `OCR_CACHE_ONLY=1` → `OcrCacheMiss` on a miss.
- **Env:** `OCR_THREADS` (default: torch's default = physical cores), `OCR_MODE` (`gundam`|`base`),
  `OCR_MAX_TOKENS`, `OCR_DTYPE` (`mixed`|`bf16`|`mixed-int8head`), `OCR_FAST_DECODE` (`0`|`1`|`2`), `OCR_CACHE_ONLY`.
- **Install:** `json4win/requirements.txt` pins torch `2.13.0+cpu` from `--extra-index-url
  https://download.pytorch.org/whl/cpu` (no CUDA on Linux). The index has both wheels for Python 3.13:
  `torch-2.13.0+cpu-cp313-cp313-win_amd64.whl` and `torch-2.13.0+cpu-cp313-cp313-manylinux_2_28_x86_64.whl`
  (and `torchvision-0.28.0+cpu-cp313-cp313-win_amd64.whl` / `…manylinux_2_28_x86_64.whl`), checked 2026-11-21.
  pip resolves it as is (31 packages, ~1 GB venv). uv needs `--index-strategy unsafe-best-match` (added to
  `scripts/wt-env.sh`), because the torch index also serves old numpy/pillow.

## Gate measurements (2026-11-21, dev box: Ryzen 9 7900X, no GPU)

Jury-like limits for every row: `OCR_THREADS=8`, `ATEN_CPU_CAPABILITY=avx2 ONEDNN_MAX_CPU_ISA=AVX2
MKL_ENABLE_INSTRUCTIONS=AVX2`, `systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0`. The cap takes
effect: `torch.backends.cpu.get_cpu_capability()` reports `AVX2`, oneDNN verbose shows `jit:avx2` for fp32 convs,
and bf16 matmuls no longer use oneDNN's `avx512_core_bf16` (900×1280×896 bf16 GEMM 1.05 ms → 8.7 ms, the same as
with oneDNN disabled, i.e. the path a CPU without AVX512-BF16 takes). Command:
`scripts/ocr_probe.py bench [--dtype …] [--mode …] [--fast-decode …] PDF:PAGE …`. Seconds per page include
vision + prefill + decode; peak RSS is VmHWM per page (includes the mmapped weights).

**Default (`mixed`, gundam, fast-decode 0):** cold model load 2.7 s (weights cached; mmapped, RSS 3.5 GB after load).

| Page | s/page | prefill s | out tokens | tok/s | peak RSS GB |
|---|---:|---:|---:|---:|---:|
| `dane/skany/odwolania/0001` p1 | 67.4 | 9.1 | 1269 | 21.8 | 8.58 |
| `dane/skany/odwolania/0001` p2 (dense text) | 86.2 | 8.7 | 1609 | 20.7 | 9.53 |
| `dane/skany/pelnomocnictwa/0001` p1 | 49.5 | 8.4 | 916 | 22.3 | 9.56 |
| `dane/skany/potwierdzenia/0001` p1 | 40.5 | 8.5 | 734 | 23.0 | 9.56 |
| `dane/przyklad_03/odwolanie.pdf` p1 | 57.2 | 8.6 | 1076 | 22.1 | 9.57 |
| `dane/negatywne/Decyzja-Ministra-Sportu-i-Turystyki1.pdf` p1 | 42.8 | 8.5 | 793 | 23.1 | 9.58 |
| **mean / max** | **57.3 / 86.2** | | | | **max 9.58** |

**Variants** (on the two odwolanie pages, same limits):

| Setting | p1 s | p2 s | peak RSS GB | Output vs default |
|---|---:|---:|---:|---|
| default (`mixed`, gundam) | 67.4 | 86.2 | 9.53 | — |
| `OCR_DTYPE=bf16` (all bf16) | 110.8 | – | 7.0 | prefill 52 s instead of 9 s |
| fp32 everywhere | – | – | ~14 (est.) | not run: does not fit 12 GB |
| `OCR_MODE=base` (1 view, 279 prompt tokens) | 46.6 | 67.6 | 9.28 | a few more diacritics errors (`prowadżonego`, `DOWOLANIE`) |
| `OCR_FAST_DECODE=1` (single-token MoE) | 65.6 | 83.2 | 9.54 | identical (p2 byte-identical) |
| `OCR_FAST_DECODE=2` (+ dense decode attention) | 54.3 | 68.2 | 9.54 | p2: 15 word diffs out of ~1000 |
| `OCR_FAST_DECODE=2` + `OCR_DTYPE=mixed-int8head`¹ | 61.4 | 64.7 | 10.36 | clean text near-identical to fast-2 (3 word diffs), but p1 emitted 1538 instead of 1253 raw tokens (cause unknown), so p1 got slower |

¹ measured with per-tensor int8; the code now uses per-channel int8 for the head (only smoke-tested: 60 tokens, correct text).

Without the cap (12 threads, AVX-512) the default runs 45–50 s/page on the 1-page documents (cache fill demo).

**Gate verdict:** RAM **pass** (≤ 9.6 GB peak, 12 GB cap). Speed **fails** on dense pages: mean 57 s, but the
two pages with ≥ 1269 output tokens take 67–86 s (limit 60 s). Quality: **not measured on the full set** (below).

### Why decode is slow, and the laptop estimate

Time = ~9 s vision + prefill, then ~22 tok/s decode. Decode is **memory-bandwidth-bound**: each token reads
~575 M active parameters (12 layers × (attention + 2 shared + 6 of 64 routed experts) + a 129k-vocab lm_head),
i.e. ~1.15 GB of bf16 weights, ≈ 30–45 ms at 30–40 GB/s. It barely scales past 4 threads (1 thread 14 tok/s,
4 threads 23, 8 threads 24, 12 threads 24). A laptop i7 with dual-channel DDR4/DDR5 (~30–50 GB/s achievable)
and a slower vision prefill (~1.5× on 8 cores) should land at **~15–22 tok/s, i.e. 45–75 s for a light page and
90–120 s for a dense A4 page** (estimate, not measured).

## Quality

`scripts/ocr_probe.py quality` (cache-only) on the scans OCR'd so far (`dane/skany/pelnomocnictwa/0001`,
`dane/skany/potwierdzenia/0001`): NIP/REGON/KRS/account/transaction ids + names **10/10 found** (9/10 verbatim:
the NIP is printed `999-295-65-50`, found with separators removed); amount and date found. Reading the 6 gate
pages by eye: all NIP/KRS/REGON, account numbers, case numbers and names are correct; diacritics are almost
always right. Errors seen: `Ł`→`L` in capitals (`WPLYNEŁO`, `ODWOLANIE`, `JANA PAWLA`), `NADWIŚLANSKI` (Ń→N),
and a few word-level slips (`nieograniczowego`, `kómunalnych`, `zamieszkłych`, `predmiotowego`). End to end
(CLI, cached OCR, LLM) the scanned potwierdzenie gave the ground-truth JSON except `z_rachunku` without its `PL`
prefix (the OCR text has it; a normaliser/extraction follow-up). The LLM step
(D12) is expected to fix such typos. The full probe on all 30 scans was not run (see next steps).

## Next steps

1. **Cache fill (P2):** `make ocr-cache` (default 4 pages, breadth-first, resumable; one process). dane/ has
   226 PDFs, 400 pages at ≤ 4 per PDF (358 at ≤ 3); at ~45–55 s/page with 12 threads that is **≈ 5–6 h**. The 30
   scans alone (≤ 3 pages: 50 pages) take ≈ 40 min: `make ocr-cache PAGES=3 PATHS="$(ls dane/skany/*/*/*.pdf)"`.
   Then `OCR_CACHE_ONLY=1 scripts/ocr_probe.py quality -v` for the full per-field table (the quality gate).
2. **Speed options** (the decision belongs to the coordinator/user; any change of default = new cache):
   - (a) `OCR_MODE=base`: −20 s on dense pages, slightly more diacritics errors. Check with the probe.
   - (b) `OCR_DTYPE=mixed-int8head`: −3 ms/token in decode (29 vs 27 tok/s with fast-decode 2), clean text nearly
     unchanged, but on one page it emitted 23 % more raw tokens and was slower overall; inconclusive.
   - (c) `OCR_FAST_DECODE=2`: −20 % decode, small text differences; needs the quality probe before becoming the
     default. Next lever after that: **int8 weights for the whole decoder** (halves the bytes read per token,
     est. 1.6–2× decode). A prototype ran out of the 12 GB cap during quantization (packed int8 weights
     ~0.38 GB/layer + fp32 conversion of embeddings/vision) and broke on `self.q_proj.weight.device` in the
     remote code; it was shelved.
   - (d) Read fewer pages per class in the pipeline (O7), e.g. odwolanie page 1 only when the markers are there.
3. **Jury run (D1):** on a real AVX2-only laptop, measure the 6 gate pages (`scripts/ocr_probe.py bench`) to replace
   the estimate above. Not yet verified: a real clean-venv `pip install -r json4win/requirements.txt` (only a pip
   dry-run was done) and a first-run download with the pinned huggingface-hub 0.36.0 (the weights on the dev box
   were fetched with huggingface-hub 2.4.0).
4. **dpi:** 200 dpi was chosen because the model downsizes to 640 px tiles / a 1024 px view; it was not compared
   with the model card's 300 dpi. dpi is in the cache key.
