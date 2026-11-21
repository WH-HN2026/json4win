# json4win: Odwołania2json

Rozwiązanie wyzwania UZP (HackNation 2026): zamienia dokumenty sprawy odwoławczej KIO (odwołanie,
pełnomocnictwo, potwierdzenie przelewu) z PDF na JSON w formacie z `../oczekiwane-json`.
Dokumenty, które nie należą do żadnej z tych klas, dają pusty JSON `{}`.

Status: szkielet. CLI działa end-to-end, ale każdy dokument daje na razie `{}`. Plan prac:
[`../docs/roadmap.md`](../docs/roadmap.md).

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
├── json4win/         # kod: cli.py (wejście/wyjście), pipeline.py (przetwarzanie dokumentu)
├── tests/
├── requirements.txt
├── start.bat / start.sh
└── .env.example      # konfiguracja LLM, kopiuj do .env.local
```
