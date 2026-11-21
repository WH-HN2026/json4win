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
w kodzie. Model językowy: API zgodne z OpenAI w UE (Mistral La Plateforme), ustawienia w `.env.local`
(wzór: `.env.example`).

## Uruchomienie

```bash
pip install -r requirements.txt        # Python 3.13+
# umieść sprawy w input/<sprawa>/*.pdf
./start.sh                             # Windows: start.bat
# wynik: output/<sprawa>/<nazwa pliku>.json
```

Opcje: `python -m json4win --input KATALOG --output KATALOG [-v]`.

## Struktura

```
json4win/
├── input/            # wejście: input/<sprawa>/*.pdf
├── output/           # wyjście: output/<sprawa>/*.json (te same nazwy co w input)
├── config/           # definicje klas dokumentów (nowa klasa = nowy plik, bez zmian w kodzie)
├── json4win/         # kod: cli.py (wejście/wyjście), pipeline.py (przebieg), config.py (klasy),
│                     #   prompts.py, llm.py, decide.py (decyzja, czytanie), extract.py, validate.py
├── tests/
├── requirements.txt
├── start.bat / start.sh
└── .env.example      # konfiguracja LLM, kopiuj do .env.local
```
