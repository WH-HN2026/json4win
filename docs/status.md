# Status MVP i co dalej (2026-11-21)

Gałąź `dev` (lokalna, do wypchnięcia przez użytkownika). Szczegóły decyzji: [`architecture.md`](architecture.md),
zadania: [`roadmap.md`](roadmap.md).

## Co działa

Pełny przepływ z [`architecture.md`](architecture.md) §3, na prawdziwych skanach, bez warstwy tekstowej PDF:

1. **OCR lokalnie na CPU:** `baidu/Unlimited-OCR-2` (przypięta rewizja). Wynik jest w cache per strona, a wagi (~6,7 GB)
   pobierają się przy pierwszym uruchomieniu. Szczegóły i pomiary: [`ocr.md`](ocr.md).
2. **Decyzja:** GLM-5.3-Flash przez API Mistrala rozpoznaje odwołanie, pełnomocnictwo, przelew albo `inne` → `{}`.
3. **Doczytywanie stron według configu klasy:** znacznik (odwołanie: zarzuty), pytanie o kompletność
   (pełnomocnictwo) albo limit stron (przelew: 1).
4. **Ekstrakcja:** prompt bazowy uzupełniony configiem klasy. LLM poprawia literówki OCR według formatów pól, a imiona
   i nazwiska zapisuje w mianowniku. Potem działają normalizatory (daty, kwoty, cyfry, TED) i walidacja (typy, regexy,
   listy wartości), a na koniec do 2 poprawek przez LLM. Pole, które nadal jest błędne, dostaje `null`.
5. **Ślad ekstrakcji** (`json4win/traces/`, poza `output/`): dla każdego pola strona i fragment tekstu, z którego
   pochodzi wartość, oraz kroki, czasy i poprawki.
6. **Konfigurowalność:** nowa klasa to nowy plik YAML ([`nowa-klasa.md`](nowa-klasa.md),
   przykład: `json4win/config_examples/ogloszenie_bzp.yaml`).
7. **GUI** (`start_gui.sh` / `start_gui.bat`): wgrywanie PDF-ów, przetwarzanie z postępem, podgląd PDF i JSON obok
   siebie, ślad.

Uruchomienie: `cd json4win && pip install -r requirements.txt && ./start.sh` (Windows: `start.bat`). Klucz API
trzeba wpisać w `json4win/.env.local` (wzór: `.env.example`).

## Wyniki (bez dużych testów, na życzenie)

| Pomiar | Wynik |
|---|---|
| Test MVP na 4 prawdziwych skanach (`start.sh`: przelew, pełnomocnictwo, odwołanie, negatyw) | 4/4 dobrze sklasyfikowane, negatyw `{}`, **29/29** niepustych pól zgodnych z wzorcem (kryterium ewaluatora) |
| Czas tego testu (Ryzen 9, 12 wątków) | 5,5 min, prawie wyłącznie OCR: 47–90 s na stronę, LLM 2–12 s na dokument |
| „Idealny OCR” (tekst z PDF zamiast OCR, tylko pomiar dev) na `przyklad_01..39` | F1 **0.997**, 0 FP, 16/16 negatywów `{}` |
| Mniejsze modele, „idealny OCR” ([`models.md`](models.md)) | ministral-14b 0.991, mistral-small 0.996, ministral-8b 0.980, ministral-3b 0.973 |
| OCR, warunki jak u jury (8 wątków, limit 12 GB, AVX2) | RAM 9,6 GB (ok), 41–57 s lekkie strony, 67–86 s gęste (za wolno wobec celu 60 s) |

## Znane ograniczenia

- **Prędkość OCR** to główne ryzyko. Na laptopie i7 szacujemy 45–75 s na lekką stronę i 90–120 s na gęstą. Odwołanie
  ze skanu w teście MVP czytało 3 strony (znacznik zarzutów nie trafił na stronach 1–2), co dało około 4,5 min na
  jeden dokument.
- Nie ma jeszcze F1 na prawdziwym OCR dla całego zbioru, bo cache OCR nie jest wypełniony (`dane/skany` ~40 min,
  całe `dane/` ~5–6 h).
- Ślad nie znajduje źródła dla dat (tekst „10.04.2026 r.” nie jest porównywany z „2026-04-10”).
- Endpoint LLM to na razie globalny `api.mistral.ai` (taniej). Na oddanie trzeba przełączyć na `api.eu.mistral.ai`
  ([`compliance.md`](compliance.md)).
- Model GLM-5.3-Flash (320 mld parametrów) daje mało punktów za rozmiar.

## Co dalej (w kolejności)

1. **Prędkość OCR:** zmierzyć i wybrać ustawienie z `ocr.md`: tryb `base` (47/68 s), `OCR_FAST_DECODE`, niższe dpi.
   Sprawdzić znacznik odwołania na tekście z OCR, żeby czytać 1–2 strony zamiast 3. To zadanie T3, a jedna strona
   mniej daje około 90 s mniej na odwołanie.
2. **Cache OCR i prawdziwe F1:** `make ocr-cache` dla `dane/skany` (w tle, jeden proces), potem
   `OCR_CACHE_ONLY=1 make eval-skany`. Następnie strojenie klas na prawdziwym OCR (T1–T4).
3. **Mniejszy model:** usunąć z `pelnomocnictwo.yaml` przykład KRS, który małe modele przepisują. Przetestować
   ministral-3b do decyzji z ministral-14b albo mistral-small do ekstrakcji (M1), potem wybrać domyślny zestaw.
4. **Szybkość i koszt LLM:** `LLM_REASONING_EFFORT=low` (na 1 sprawie F1 1.000, LLM 2–3 s zamiast 4–16 s na
   dokument). Do potwierdzenia na większej próbce.
5. **Dostawa (D1):**
   - przełączyć na endpoint UE;
   - osobny klucz dla jury z limitem;
   - w panelu Mistrala wyłączyć trenowanie na danych i rozważyć ZDR;
   - test czystej instalacji na Windows (`start.bat`), w tym pobranie wag przy pierwszym uruchomieniu;
   - pomiar czasu na laptopie.
6. **Dokumentacja zgłoszenia (D2)** i raport jakości (V1). Drobne: ślad dla dat (X2).
