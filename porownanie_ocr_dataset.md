# Porównanie silników OCR na zbiorze publicznych odwołań KIO (`dataset/odwolania/`)

Data testów: 2026-11-22  
Środowisko lokalne: AMD Radeon RX 7900 (24 GB VRAM, ROCm/HIP), `llama.cpp` (`b11913`), Tesseract `5.5.4`.  
Środowisko API: Mistral AI API (UE).

---

## 1. Metodyka

- **Zbiór danych:** **16 prawdziwych, publicznie dostępnych odwołań KIO** z katalogu `dataset/odwolania/` (w tym **3 czyste skany** bez warstwy tekstowej: `01_bialystok`, `02_bip.wszzkielce`, `18_szpital-lebork` oraz 13 dokumentów z BIP/platform zakupowych wyrenderowanych jako obrazy).
- **Zakres:** pierwsze 4 strony każdego dokumentu = **63 strony @ 150 DPI**.
- **Ground truth:** ręcznie i wizyjnie zweryfikowane pliki `dataset/odwolania/*.json` (**173 pola GT**, w tym **167 pól występujących dosłownie** na stronach 1–4; 6 pól było wspólnych dla wszystkich silników z powodu odmiany gramatycznej w tekście lub wystąpienia na str. 5+).
- **Metryki:**
  - **Recall dosłowny (167 pól):** odsetek pól obecnych dosłownie na stronach 1–4 poprawnie odzyskanych (znormalizowany alnum).
  - **Recall surowy alnum (173 pól):** względem wszystkich 173 pól GT.
  - **Recall dokładny PL (173 pól):** ścisłe zachowanie polskich znaków diakrytycznych (`ą ć ę ł ń ó ś ź ż`).
  - **3 czyste skany (30 pól):** osobny wynik wyłącznie dla 3 prawdziwych skanów bez warstwy tekstowej.

---

## 2. Wyniki zbiorcze (9 konfiguracji OCR, 16 PDF / 63 strony @ 150 DPI)

| Silnik OCR | Środowisko / Rozmiar | Recall dosłowny (167 pól) | Recall surowy alnum (173) | Recall dokładny PL (173) | 3 czyste skany (30 pól: alnum / PL) | Prawdziwe błędy OCR | Czas łączny (63 str.) | Czas / str. |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **DeepSeek V4.1 Flash (Vision)** | Mistral API (UE) | **166 / 167 (99.40%)** | **166 / 173 (95.95%)** | **159 / 173 (91.91%)** | **100.0% / 100.0%** | **1** | **36.8 s** (6x) | **0.58 s** |
| **LightOnOCR-3-4B (`Q8_0`)** | Lokalny RX 7900 GPU (100% GPU, 4.9 GB) | **165 / 167 (98.80%)** | **165 / 173 (95.38%)** | **159 / 173 (91.91%)** | 96.7% / **96.7%** | **2** | 238.9 s (4x) | 3.79 s |
| **PaddleOCR-VL-1.6 (`BF16/F16`)** | Lokalny RX 7900 GPU (100% GPU, 1.7 GB) | **165 / 167 (98.80%)** | **165 / 173 (95.38%)** | 155 / 173 (89.60%) | **100.0%** / 93.3% | **2** | **78.1 s** (4x) | **1.24 s** |
| **DeepSeek-OCR-2 (`Q8_0`)** | Lokalny RX 7900 GPU (100% GPU, 3.8 GB) | 164 / 167 (98.20%) | **165 / 173 (95.38%)** | 157 / 173 (90.75%) | **100.0% / 96.7%** | 3 | 88.7 s (4x) | 1.41 s |
| **LightOnOCR-3-0.8B (`Q8_0`)** | Lokalny RX 7900 GPU (100% GPU, **0.97 GB**) | **165 / 167 (98.80%)** | **165 / 173 (95.38%)** | 155 / 173 (89.60%) | **100.0%** / 90.0% | **2** | 100.3 s (4x) | 1.59 s |
| **LightOnOCR-2-1B (`Q8_0`)** | Lokalny CPU mmproj + RX 7900 GPU (1.4 GB) | **165 / 167 (98.80%)** | **165 / 173 (95.38%)** | 158 / 173 (91.33%) | 96.7% / 93.3% | **2** | 1035.2 s (2x)* | 16.43 s* |
| **Unlimited-OCR-2 (`Q8_0`)** | Lokalny RX 7900 GPU (patched `llama.cpp`, 3.7 GB) | 163 / 167 (97.60%) | 163 / 173 (94.22%) | 155 / 173 (89.60%) | 96.7% / 90.0% | 4 | 449.8 s (1x) | 7.14 s |
| **Tesseract 5.5.4 (`pol+eng`)** | Lokalny CPU (4 wątki) | 161 / 167 (96.41%) | 161 / 173 (93.06%) | 150 / 173 (86.71%) | 96.7% / 93.3% | 6 | 59.0 s (4x) | 0.94 s |
| **Tesseract 5.5.4 (`pol` only)** | Lokalny CPU (4 wątki) | 156 / 167 (93.41%) | 156 / 173 (90.17%) | 143 / 173 (82.66%) | 93.3% / 90.0% | 11 | **12.2 s** (4x) | **0.19 s** |

*\*`LightOnOCR-2-1B` wymagał `--no-mmproj-offload` (enkoder wizyjny na CPU) z powodu błędu CLIP na `ROCm0` w `llama.cpp`. `PaddleOCR-VL-1.6`, `DeepSeek-OCR-2` oraz oba modele `LightOnOCR-3` (`0.8B` i `4B`) działają w 100% na RX 7900 GPU w standardowym `llama.cpp` bez błędów.*

---

## 3. Szczegółowe błędy OCR poszczególnych silników

- **DeepSeek V4.1 Flash (1 błąd):** tytuł zamówienia w `38_zamowienia.szpitalciechanow...pdf`. **30/30 (100%)** dokładności i alnum na 3 prawdziwych skanach.
- **LightOnOCR-3-4B (2 błędy):** tytuł w skanie `02_bip.wszzkielce...pdf` i tytuł w `19_przetargi.propublico...pdf` — **0 błędów na mailach, nazwach firm, KRS, NIP i sygnaturach!** Wyrównuje wynik **DeepSeek V4.1 Flash** w dokładności polskich znaków (**159/173 = 91.91%**, **96.7%** dokładności PL na 3 skanach), przy czasie **3.79 s/str.** (1.9× szybciej niż `Unlimited-OCR-2`).
- **PaddleOCR-VL-1.6 (2 błędy):** tytuły zamówień w `05_zwps` i `32_bip.spmzoz-slupsk` — **0 błędów na mailach, nazwach firm, KRS, NIP i sygnaturach!** **Najszybszy lokalny VLM OCR** (**78.1 s / 1.24 s na stronę**, 100% na RX 7900 GPU), **100% (30/30)** alnum i **93.3%** dokładnych PL na 3 skanach, czysty tekst bez tagów HTML, Apache-2.0 (**1.7 GB**).
- **DeepSeek-OCR-2 (3 błędy):** 2 adresy e-mail (`12`, `48`) oraz 1 numer TED (`30`: `347443-2023`). Najlepszy lokalny wynik na **3 prawdziwych skanach** (**100% alnum / 96.7% dokładnych PL**), bardzo szybki (**88.7 s / 1.41 s na stronę**, 100% RX 7900 GPU), Apache-2.0 (**3.8 GB**).
- **LightOnOCR-3-0.8B (2 błędy):** nazwa kancelarii (`&`) w `04_bip.czestochowa...pdf` oraz e-mail w `12_bip-v1-files...pdf`. **30/30 (100%)** alnum na 3 prawdziwych skanach, **1.59 s/str.** i najmniejszy rozmiar (**972 MB**, Apache-2.0).
- **LightOnOCR-2-1B (2 błędy):** tytuł w skanie `02_bip.wszzkielce...pdf` oraz nazwa kancelarii (`&`) w `04_bip.czestochowa...pdf`. Minimalnie lepsze polskie diakrytyki niż v3-0.8B (91.33% vs 89.60%), ale 10× wolniejszy na ROCm przez bug CLIP.
- **Unlimited-OCR-2 (4 błędy):** tytuł w skanie `18_szpital-lebork...pdf`, **numer KRS `0000005901`** w `32_bip.spmzoz-slupsk...pdf`, nazwy zamawiających w `37` i `45`. Wymaga nieoficjalnego patcha `llama.cpp`.
- **Tesseract `pol+eng` (6 błędów):** sygnatura `IZ.271.1.2020` (`04`), maile pełnomocników (`05`, skan `18`), nazwy firm (`12`, `38`, `45`).
- **Tesseract `pol` only (11 błędów):** ~5× szybszy niż `pol+eng` (**12.2 s** vs 59.0 s), ale bez `eng` masowo psuje adresy e-mail (7 błędnych maili: `01`, `04`, `05`, `18`, `19`, `32`, `45`) oraz nazwy firm (`12`, `38`, `45`) i kancelarii (`04`).

---

## 4. Wnioski

1. **Najlepszy lokalny model OCR: `LightOnOCR-3-0.8B (Q8_0)`** — tylko **972 MB** (Apache-2.0, natywny Qwen3.5 w `llama.cpp` bez patchy), **100% (30/30)** na prawdziwych skanach, **98.80%** recall dosłownego i **1.59 s/str.** na RX 7900 GPU (4.5× szybciej niż `Unlimited-OCR-2` przy wyższej jakości).
2. **Najlepszy przez API (VLM): `DeepSeek V4.1 Flash (Vision)`** — **99.40%** recall dosłownego, **100%/100%** na prawdziwych skanach, **0.58 s/str.** (6x).
3. **Tesseract:** jeśli w ogóle używać Tesseracta na polskich dokumentach z adresami e-mail i nazwami firm, **zawsze `-l pol+eng`**, nigdy samo `-l pol` (samo `pol` psuje maile i obniża recall z 96.4% do 93.4%).
