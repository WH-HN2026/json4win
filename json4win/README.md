# json4win: Odwołania2json

Rozwiązanie wyzwania UZP (HackNation 2026): zamienia dokumenty sprawy odwoławczej KIO (odwołanie,
pełnomocnictwo, potwierdzenie przelewu) z PDF na JSON w formacie z `../oczekiwane-json`.
Dokumenty, które nie należą do żadnej z tych klas, dają pusty JSON `{}`.

Status: działające MVP (lokalny OCR + LLM, wszystkie trzy klasy, GUI, ślad ekstrakcji). Co działa, wyniki i co dalej:
[`../docs/status.md`](../docs/status.md). Plan prac: [`../docs/roadmap.md`](../docs/roadmap.md).

## Jak to działa

Dla każdego PDF-a (niezależnie, błąd jednego pliku daje `{}` i przetwarzanie idzie dalej):

1. **OCR** pierwszej strony lokalnym modelem (CPU, wynik w cache). Warstwa tekstowa PDF nie jest używana.
2. **Decyzja**: model językowy dostaje tekst strony i opisy wszystkich klas z `config/*.yaml`
   (`prompt_decyzja.md`) i odpowiada id klasy albo `inne` → `{}`.
3. **Czytanie dalej** według `czytanie` klasy: do znacznika (`znacznik` + `stron_po_znaczniku`), albo do
   odpowiedzi „tak” na pytanie `kompletny_gdy` (`prompt_kompletnosc.md`), najwyżej `max_stron` stron.
4. **Ekstrakcja**: model wypełnia `szablon` klasy według opisów pól (`prompt_ekstrakcja.md`).
5. **Normalizacja i walidacja** każdego pola (`normalizacja`, `typ`, `format`, `wartosci`). Błędy wracają do
   modelu (`prompt_poprawka.md`, najwyżej 2 razy); pole wciąż błędne → `null`.

Nowa klasa dokumentu = nowy plik `config/<id>.yaml` (format: [`config/README.md`](config/README.md)), bez zmian
w kodzie. Instrukcję krok po kroku oraz gotowy przykład nowej klasy (`config_examples/ogloszenie_bzp.yaml`,
aktywowany zmienną `JSON4WIN_CONFIG_DIRS`) zawiera [`../docs/nowa-klasa.md`](../docs/nowa-klasa.md). Model
językowy: API zgodne z OpenAI w UE (Mistral La Plateforme), ustawienia w `.env.local` (wzór: `.env.example`).

## Uruchomienie

```bash
pip install -r requirements.txt        # Python 3.13+
# umieść sprawy w input/<sprawa>/*.pdf
./start.sh                             # Windows: start.bat
# wynik: output/<sprawa>/<nazwa pliku>.json
```

Opcje: `python -m json4win --input KATALOG --output KATALOG [--trace KATALOG | --no-trace] [-v]`.

## Przejrzystość

Dla każdego PDF-a powstaje ślad ekstrakcji, **poza** `output/`: `traces/<sprawa>/<nazwa>.trace.json`
(do odczytu maszynowego) i `traces/<sprawa>/<nazwa>.trace.md` (tabela dla człowieka). Katalog zmienia
`--trace KATALOG` albo `JSON4WIN_TRACE_DIR`; `--no-trace` wyłącza ślady.

Ślad zawiera: sha256 pliku, przeczytane strony OCR (liczba znaków, czas), decyzję modelu (klasa),
przebieg czytania (znacznik, pytania o kompletność), model i liczbę wywołań LLM, poprawki i błędy walidacji
w każdej rundzie, czasy kroków, a dla błędnego dokumentu typ błędu i krok, w którym wystąpił. Dla każdego
pola: wartość końcowa, surowa wartość od modelu, normalizacja, metoda (`llm`, `llm+normalizacja`,
`walidacja→null`) oraz **pochodzenie**: numer strony i fragment tekstu OCR (±60 znaków), w którym
surowa wartość została znaleziona deterministycznie (dopasowanie przybliżone `difflib`, dla numerów
porównywane same cyfry), albo „nie znaleziono w tekście”. Pochodzenie nie zależy od modelu językowego,
więc każdą wartość można sprawdzić w dokumencie. Ślad nie zawiera klucza API.

## Interfejs graficzny (GUI)

Aplikacja zawiera lekki, lokalny interfejs webowy (działa w pełni offline, wyłącznie na bibliotece
standardowej Pythona 3.13, nasłuchuje tylko na `127.0.0.1`):

```bash
./start_gui.sh                         # Windows: start_gui.bat
# albo bezpośrednio:
python -m json4win --gui [--port PORT] [--input KATALOG] [--output KATALOG] [--no-browser]
```

Domyślnie serwer wybiera wolny port na `127.0.0.1` i automatycznie otwiera przeglądarkę. Interfejs ma
jeden układ dla obu widoków: górny pasek ze wskaźnikiem przetwarzania (stan, licznik plików, czas; widoczny
w każdym widoku), menu po lewej (**Dokumenty**, **Nowa klasa**) i obszar roboczy po prawej. Działa też na
wąskim ekranie (lista, a po wybraniu dokumentu jego podgląd).

**Dokumenty** (`/`):
- lewy panel: sprawy z katalogu wejściowego i ich pliki ze stanem (kwadratowy znacznik: nowy, w kolejce,
  w toku z czasem, gotowe z kluczem głównym wyniku, pusty `{}`, błąd); **Przetwórz wszystko**, a przy każdej
  sprawie **Dodaj** (wgranie PDF; można też upuścić pliki na sprawę) i **Przetwórz**; panel **Nowa sprawa**
  (nazwa podpowiadana, przeciągnij i upuść lub wybór z dysku); strzałki góra/dół przechodzą między plikami;
- obszar roboczy: podgląd PDF obok wyniku JSON (pola `null` wyszarzone, „nie rozpoznano (pusty JSON)” dla
  `{}`), zakładka **Ślad** ze śladem ekstrakcji, komunikat błędu przetwarzania nad wynikiem, **Przetwórz**,
  **Kopiuj**, **Pobierz JSON**; wybrany dokument jest w adresie (`/?doc=sprawa/plik.pdf`).

**Nowa klasa** (`/wizard`): trzyetapowy kreator nowej klasy dokumentu bez pisania kodu (etapy w lewym
panelu: przykładowe PDF-y + OCR → edytor kształtu JSON → edytor YAML z walidacją na żywo, testem potoku
i zapisem); długie kroki (OCR, LLM) pokazują pasek i upływający czas. Szczegóły: [`../docs/nowa-klasa.md`](../docs/nowa-klasa.md).

## OCR (lokalnie, CPU)

Każda czytana strona przechodzi przez lokalny model OCR `baidu/Unlimited-OCR-2` (MIT, otwarte wagi),
na CPU, bez GPU (warstwa tekstowa PDF nie jest używana). Szczegóły i pomiary: [`../docs/ocr.md`](../docs/ocr.md).

- **Instalacja:** `pip install -r requirements.txt` pobiera torch w wersji CPU (indeks
  `download.pytorch.org/whl/cpu`, bez CUDA) i resztę zależności; razem ok. 1 GB na dysku w venv.
- **Pierwsze uruchomienie** pobiera wagi modelu z Hugging Face (ok. 6,7 GB, przypięta rewizja) do
  `~/.cache/huggingface/hub` (Windows: `%USERPROFILE%\.cache\huggingface\hub`; zmiana: zmienna `HF_HOME`).
  Kolejne uruchomienia działają offline (`HF_HUB_OFFLINE=1`).
- **Zasoby:** ok. 10 GB RAM w szczycie; 45–90 s na stronę A4 (zależnie od ilości tekstu) przy AVX2 i 8 wątkach. Czytamy tylko tyle stron, ile potrzebuje dana klasa dokumentu.
- **Cache:** wynik OCR każdej strony jest zapisywany (klucz: sha256 PDF + strona + ustawienia) w
  `~/.cache/json4win/ocr` (Windows: `%LOCALAPPDATA%\json4win\ocr`; zmiana: `JSON4WIN_CACHE_DIR`), więc
  ponowne przetworzenie tych samych plików jest natychmiastowe.
- **Zmienne** (`.env.example`): `OCR_BACKEND` (`local` domyślnie | `tesseract` | `lighton_api` | `hybrid`), `OCR_THREADS`
  (domyślnie liczba rdzeni fizycznych), `OCR_MODE`, `OCR_MAX_TOKENS`, `OCR_DTYPE`, `OCR_FAST_DECODE`,
  `OCR_CACHE_ONLY`.
- **Alternatywny backend Tesseract (`OCR_BACKEND=tesseract`):** zamiast ciężkiego modelu VLM można
  użyć lokalnego Tesseract OCR (Apache 2.0, kilkadziesiąt razy szybszy i ok. 0,2 GB RAM, kosztem
  niższej dokładności na trudnych skanach/tabelach). Wymaga zainstalowanego programu `tesseract` oraz
  pliku `pol.traineddata` w `~/.cache/json4win/tessdata` (Windows: `%LOCALAPPDATA%\json4win\tessdata`
  lub wskazanie katalogu przez `OCR_TESSDATA_DIR`). Wyniki trafiają do osobnego katalogu cache.
  Szczegóły instalacji i porównanie jakości: [`../docs/ocr.md`](../docs/ocr.md) oraz
  [`../docs/quality.md`](../docs/quality.md).
- **LightOnOCR-2-1B przez API w UE (`OCR_BACKEND=lighton_api`):** ten sam model z otwartymi wagami
  (Apache 2.0, LightOn, Francja), ale uruchamiany u dostawcy w UE przez API zgodne z OpenAI, więc na
  słabym CPU nie trzeba liczyć ~60 s na stronę (czas przez API jeszcze niezmierzony). Obraz strony (PNG, dłuższy bok 1540 px) jest
  wysyłany do **IONOS AI Model Hub** (IONOS SE, Berlin; domyślnie) albo przez **EUrouter** (Amsterdam,
  kierowany do IONOS). Wymaga klucza w `.env.local`:
  ```
  OCR_BACKEND=lighton_api
  OCR_API_KEY=<token IONOS>
  ```
  EUrouter: dodatkowo `OCR_API_BASE_URL=https://api.eurouter.ai/api/v1`, `OCR_API_MODEL=lightonocr-2-1b`
  i `OCR_API_EXTRA_BODY={"provider": {"only": ["ionos"], "allow_fallbacks": false, "zdr": true, "max_retention_days": 0}}`.
  Gdy API zawiedzie dla strony (brak klucza, błąd, limit czasu po ponownych próbach), tę stronę czyta
  lokalny Tesseract (`OCR_API_FALLBACK=tesseract`, domyślnie) i w logu pojawia się ostrzeżenie (najwyżej
  45 s na stronę; po 3 nieudanych stronach z rzędu API nie jest już wołane do końca uruchomienia); wymaga
  to zainstalowanego Tesseracta jak wyżej. Wariant hybrydowy: `OCR_BACKEND=hybrid` +
  `OCR_HYBRID_FIRST=lighton_api` (strona 1 przez API, dalsze Tesseractem). Szczegóły: [`../docs/ocr.md`](../docs/ocr.md).
- `OCR_BACKEND=lighton` (LightOnOCR-2-1B) służy tylko do porównań w repozytorium deweloperskim (wymaga transformers 5, osobny venv): [`../docs/ocr.md`](../docs/ocr.md).

## Struktura

```
json4win/
├── input/            # wejście: input/<sprawa>/*.pdf
├── output/           # wyjście: output/<sprawa>/*.json (te same nazwy co w input)
├── traces/           # ślady ekstrakcji: traces/<sprawa>/*.trace.json i *.trace.md (poza output/)
├── config/           # definicje klas dokumentów (nowa klasa = nowy plik, bez zmian w kodzie)
├── json4win/         # kod: cli.py (CLI), gui.py + gui_static/ (GUI), pipeline.py (przebieg),
│                     #   config.py (klasy), prompts.py, llm.py, decide.py, extract.py, validate.py,
│                     #   trace.py (ślad ekstrakcji)
├── tests/
├── requirements.txt
├── start.bat / start.sh
├── start_gui.bat / start_gui.sh
└── .env.example      # konfiguracja LLM, kopiuj do .env.local
```
