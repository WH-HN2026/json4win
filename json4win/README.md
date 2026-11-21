# json4win: Odwołania2json

Rozwiązanie wyzwania UZP (HackNation 2026): zamienia dokumenty sprawy odwoławczej KIO (odwołanie,
pełnomocnictwo, potwierdzenie przelewu) z PDF na JSON w formacie z `../oczekiwane-json`.
Dokumenty, które nie należą do żadnej z tych klas, dają pusty JSON `{}`.

Plan prac: [`../docs/roadmap.md`](../docs/roadmap.md).

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

Domyślnie serwer wybiera wolny port na `127.0.0.1` i automatycznie otwiera przeglądarkę.
W interfejsie można:
- przeglądać drzewo spraw z katalogu wejściowego i wgrywać pliki PDF (przeciągnij i upuść lub wybór z dysku) do nowej albo istniejącej sprawy,
- uruchamiać przetwarzanie dla wybranej sprawy, pojedynczego pliku lub wszystkich spraw („Przetwórz”) z podglądem statusu każdego pliku na żywo,
- oglądać podgląd PDF obok sformatowanego wyniku JSON (z wyszarzonymi polami `null` oraz oznaczeniem „nie rozpoznano (pusty JSON)” dla pustych wyników `{}`) i pobierać wynikowy plik JSON.

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
