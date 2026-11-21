# Porównanie modeli klasyfikacji dokumentów i silników OCR (`dane/`)

Data testów: 2026-11-21  
Środowisko lokalne: AMD Radeon RX 7900 (24 GB VRAM, ROCm/HIP), Ollama `v0.40.13`, patched `llama.cpp` (`b11913` + `unlimited-ocr2.patch`), Tesseract `5.5.4` (`pol+eng`).  
Środowisko API: Mistral AI API (UE).

---

## 1. Klasyfikacja dokumentów PDF po treści (4 klasy, 196 plików)

### Metodyka
- **Zbiór danych:** wszystkie **196 plików PDF** z katalogu `dane/`:
  - **180 dokumentów pozytywnych** (`dane/przyklad_01..60`): 60 `odwolanie`, 60 `pelnomocnictwo`, 60 `potwierdzenie_przelewu`.
  - **16 dokumentów negatywnych (`none`)**: 12 w `dane/negatywne/` (w tym 3 skany bez warstwy tekstowej) oraz 4 dokumenty negatywne zmieszane z przykładami (`przyklad_04`, `przyklad_10`, `przyklad_24`, `przyklad_37`).
- **Wejście:** wyłącznie warstwa tekstowa pierwszych 3 stron (`pdftotext -l 3`, maks. 4000 znaków), **bez nazw plików**.
- **Klasy:** `odwolanie`, `pelnomocnictwo`, `potwierdzenie_przelewu`, `none` (ogólne definicje w języku polskim, bez dopasowywania do nazw ze zbioru treningowego).

### Wyniki porównawcze (196 PDF)

| Model | Środowisko | Dokładność łączna | Pozytywne (180) | Negatywne (16) | Negatywne z tekstem (13) | Średni / Mediana czasu na plik | Czas łączny |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Bielik-One-4B-r1 (`Q8_0`)** | Lokalny GPU (RX 7900) | **196/196 (100.00%)** | **180/180** | **16/16** | **13/13** | **317 ms / 295 ms** | 63.5 s (1x) |
| **GLM-5.3 Flash (`zai-glm-5-3-flash`)** | Mistral API | **196/196 (100.00%)** | **180/180** | **16/16** | **13/13** | 1,316 ms / 1,129 ms | 33.3 s (8x) |
| **Mistral Small 4 (`mistral-small-2603`)** | Mistral API (`json_schema`) | 195/196 (99.49%) | **180/180** | 15/16 | 12/13 | 507 ms / 460 ms | **12.5 s** (8x) |
| **DeepSeek V4.1 Flash (`deepseek-v4-1-flash-1017`)** | Mistral API | 195/196 (99.49%) | **180/180** | 15/16 | 12/13 | 565 ms / 420 ms | 19.3 s (6x) |
| **GLiDE-9B (`Q6_K_L`, `/v1/systemone`)** | Lokalny GPU (RX 7900) | 195/196 (99.49%) | **180/180** | 15/16 | 12/13 | 414 ms / 304 ms | 82.9 s (1x) |

### Najważniejsze obserwacje (klasyfikacja)
- **Najtrudniejszy dokument negatywny:** `dane/negatywne/KIO_KIO 2617-21.pdf` (postanowienie wydane *przez* KIO, a nie odwołanie wniesione *do* KIO). Był to jedyny błąd dla **Mistral Small 4**, **DeepSeek V4.1 Flash** i **GLiDE-9B** (wszystkie przewidziały `odwolanie`; w przypadku GLiDE-9B z wyraźnie niższą pewnością `conf=0.7633` wobec `>0.91` dla pozytywów).
- **Bielik-One-4B-r1 (`Q8_0`)** i **GLM-5.3 Flash** uzyskały **100% (196/196)** bez ani jednej pomyłki.
- **Uwagi techniczne:**
  - `Bielik-One-4B-r1` lokalnie na GPU zajmuje ~5.8 GB VRAM, działa w ~317 ms/plik z wyłączonym trybem thinking (`"think": false`) i wymuszonym JSON enum.
  - `GLiDE-9B` jest modelem wyłącznie decyzyjnym (`POST /v1/systemone`, wymaga Ollama `>= 0.40.13`), zwraca skalibrowane prawdopodobieństwa i zajmuje ~9.4 GB VRAM.
  - `zai-glm-5-3-flash` zawsze generuje blok `thinking` przed odpowiedzią, dlatego wymaga `max_tokens >= 512–1024`.
  - `mistral-small-2603` warto wywoływać ze ścisłym `response_format: {"type": "json_schema", ...}`, co eliminuje okazjonalne wstawianie polskich znaków w nazwach etykiet (`"pełnomocnictwo"` zamiast `"pelnomocnictwo"`).

---

## 2. Porównanie silników OCR na polskich skanach (`dane/skany/`)

### Metodyka
- **Zbiór danych:** **30 zeskanowanych dokumentów PDF = 72 strony** w języku polskim:
  - `odwolania`: 10 PDF (52 strony, 145 pól GT)
  - `pelnomocnictwa`: 10 PDF (10 stron, 67 pól GT)
  - `potwierdzenia`: 10 PDF (10 stron, 54 pól GT)
- **Ocena jakości:** weryfikacja obecności **266 rzeczywistych wartości pól** z odpowiadających plików ground-truth `*.json` (nazwy firm, NIP, KRS, REGON, adresy e-mail, numery kont IBAN, kwoty, daty, numery BZP/TED, tytuły postępowań i przelewów) — mierzona jako:
  - **Recall alnum (znormalizowany):** odporny na spacje, myślniki i drobne różnice diakrytyczne.
  - **Recall dokładny (z polskimi znakami):** ścisłe zachowanie polskich liter (`ą ć ę ł ń ó ś ź ż`).

### Wyniki ogólne (30 skanów, 72 strony, 266 pól GT)

| Silnik OCR | Środowisko | Recall pól (alnum / znormaliz.) | Recall dokładny (z polskimi znakami) | Brakujące pola | Czas łączny (72 str.) | Czas / str. | Wymaga konwersji PDF→PNG |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Mistral OCR (`mistral-ocr-latest`)** | Mistral API (UE) | **265 / 266 (99.62%)** | **238 / 266 (89.47%)** | **1** | **21.9 s** (4x) | **0.30 s** | Nie (natywny PDF) |
| **LightOnOCR-2-1B (`Q8_0`, 1.4 GB)** | Lokalny CPU mmproj + RX 7900 GPU | **264 / 266 (99.25%)** | 231 / 266 (86.84%) | **2** | 1237.3 s (2x)* | 17.18 s* | Tak (`pdftoppm`) |
| **DeepSeek V4.1 Flash (`deepseek-v4-1-flash-1017`, Vision)** | Mistral API (UE) | 261 / 266 (98.12%) | **235 / 266 (88.35%)** | 5 | 69.8 s (6x) | 0.97 s | Tak (`pdftoppm`) |
| **Unlimited-OCR-2 (`Q8_0`, 3.7 GB)** | Lokalny RX 7900 GPU (ROCm/HIP) | 261 / 266 (98.12%) | 231 / 266 (86.84%) | 5 | 591.7 s (1 slot) | 8.22 s | Tak (`pdftoppm`) |
| **Tesseract 5.5.4 (`pol+eng`, 200 DPI)** | Lokalny CPU | 248 / 266 (93.23%) | 219 / 266 (82.33%) | 18 | **21.0 s** (4x) | **0.29 s** | Tak (`pdftoppm`) |

*\*`LightOnOCR-2-1B` wymagał `--no-mmproj-offload` (enkoder wizyjny na CPU) z powodu błędu CLIP na backendzie `ROCm0` w `llama.cpp`; mimo to był ok. 2.5–5× szybszy niż `Unlimited-OCR-2` na CPU (41–86 s/str. wg `docs/status.md`) i nie wymaga nieoficjalnych patchy.*

### Wyniki OCR według kategorii dokumentu (alnum / dokładne polskie znaki)

| Typ dokumentu | Mistral OCR | LightOnOCR-2-1B (`Q8_0`) | DeepSeek V4.1 Flash | Unlimited-OCR-2 (`Q8_0`) | Tesseract (`pol+eng`) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **`odwolania`** (10 PDF, 52 str., 145 pól) | **100.0%** / **89.7%** | **99.3%** / 86.9% | 97.9% / 86.9% | 98.6% / 86.2% | 89.7% / 78.6% |
| **`pelnomocnictwa`** (10 PDF, 10 str., 67 pól) | **100.0%** / **89.6%** | **100.0%** / 88.1% | 98.5% / 88.1% | **100.0%** / 88.1% | 98.5% / 86.6% |
| **`potwierdzenia`** (10 PDF, 10 str., 54 pola) | **98.1%** / 88.9% | **98.1%** / 85.2% | **98.1%** / **92.6%** | 94.4% / 87.0% | 96.3% / 87.0% |

### Najważniejsze obserwacje (OCR)
1. **Mistral OCR (`mistral-ocr-latest`) — najlepsza jakość i wygoda (API):**
   - **99.62% recall (265/266)** — jedyny błąd to numer rachunku w `dane/skany/potwierdzenia/0009/0009.pdf`.
   - Najszybszy end-to-end (**21.9 s** na cały zbiór bez potrzeby renderowania PNG), czysty wynik w Markdown, hosting w UE.
2. **LightOnOCR-2-1B (`Q8_0`, Apache-2.0) — najlepszy lokalny model OCR:**
   - **99.25% recall (264/266)** — **tylko 2 brakujące pola** (`odwolania/0004` nazwa zamawiającego, `potwierdzenia/0008` długi tytuł przelewu). Przebija zarówno lokalny `Unlimited-OCR-2` (5 błędów), jak i chmurowy `DeepSeek V4.1 Flash` (5 błędów).
   - **Tylko 1B parametrów (1.4 GB łącznie: 610 MB model + 782 MB mmproj)**, obsługiwany natywnie przez `llama.cpp` i `transformers` (bez patchy!). Z enkoderem wizyjnym na CPU ~17 s/str. — wyraźnie lżejszy i szybszy na laptopie bez GPU niż `Unlimited-OCR-2` (~6.7 GB, 41–86 s/str. na CPU).
   - **Uwaga dla AMD ROCm:** na backendzie `ROCm0` w `llama.cpp` konieczna jest flaga `--no-mmproj-offload` (inaczej enkoder wizyjny CLIP wpada w pętlę powtórzeń).
3. **DeepSeek V4.1 Flash (`deepseek-v4-1-flash-1017`, Vision) — bardzo mocne polskie znaki:**
   - **98.12% recall (261/266)** oraz **88.35% dokładnego zachowania polskich znaków** (najlepszy wynik na `potwierdzenia`: **92.6%** dokładności) w **69.8 s** (0.97 s/str. przy 6 wątkach).
   - **5 błędów:** 3 nazwy zamawiających w odwołaniach (`Brzozowcu`, `Dębnicy Górnej`), 1 nazwa mocodawcy (`Orbisol Budownictwo Sp. z o.o.`) i 1 długi tytuł przelewu.
4. **Unlimited-OCR-2 (`Q8_0`, lokalnie na GPU) — wysoka jakość offline, ale cięższy i wymaga patchy:**
   - **98.12% recall (261/266)** — 5 błędów (głównie długie tytuły przelewów w tabelach oraz 1 nazwa zamawiającego), **8.22 s/str.** na RX 7900 (1 slot), wymaga spatchowanego `llama.cpp` (`b11913` + `unlimited-ocr2.patch`).
5. **Tesseract 5.5.4 (`pol+eng`) — szybki lokalny CPU, ale zauważalnie słabszy na kluczowych polach:**
   - **93.23% recall (248/266)** — szybki (**21.0 s** na 4 wątkach CPU, plus czas `pdftoppm`), lecz **18 błędów**: często zniekształca znak `@` w mailach pełnomocników, nazwy `Sp. z o.o.` oraz numery postępowań (`DA.ZP.242.50.2026`).
   - Wymaga osobnego pakietu językowego `pol.traineddata` (domyślnie w systemie dostępny był tylko `eng`).

### Test czysto CPU: `LightOnOCR-2-1B (Q8_0)` vs `Unlimited-OCR-2` (8 wątków, bez GPU)

Pomiar na Ryzen 9 7900X3D (`-ngl 0 --no-mmproj-offload -t 8`, 200 DPI, 1 slot):

| Strona testowa | LightOnOCR-2-1B (`Q8_0`, CPU) | Unlimited-OCR-2 (CPU, wg `docs/status.md`) |
| :--- | :---: | :---: |
| **Lekka (`potwierdzenie`)** | **32.8 s** (pp 110.5 t/s, tg 51.1 t/s) | 41–57 s |
| **Średnia (`pelnomocnictwo`)** | **31.9 s** (pp 110.4 t/s, tg 51.4 t/s) | 41–57 s |
| **Gęsta (`odwolanie` str. 1)** | **52.7 s** (pp 110.2 t/s, tg 47.1 t/s) | 67–86 s |
| **Szczytowe zużycie RAM (`VmHWM`)** | **4.03 GB** | 9.6 GB |
| **Rozmiar wag na dysku** | **1.4 GB** | ~6.7 GB |
| **Recall na `dane/skany/` (266 pól)** | **99.25% (2 błędy)** | 98.12% (5 błędów) |

---

## 3. Rekomendacja pod pipeline

- **OCR dla skanów (brak warstwy tekstowej):** **Mistral OCR (`mistral-ocr-latest`)** — najwyższa skuteczność (99.62%), 0.30 s/stronę, brak zależności od GPU i konwersji PDF→PNG, zgodność z wymogiem UE/EOG.
- **Klasyfikacja dokumentów:**
  - **Lokalnie (GPU):** **Bielik-One-4B-r1 (`Q8_0`)** — 100% (196/196), ~317 ms/dokument, brak kosztów API.
  - **Przez API (UE, laptop bez GPU):** **Mistral Small 4 (`mistral-small-2603`)** ze ścisłym `json_schema` (najszybszy: 12.5 s / 196 plików, 99.49%) lub **GLM-5.3 Flash (`zai-glm-5-3-flash`)** (100%, wolniejszy przez tokeny reasoning).
