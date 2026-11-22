# Dodawanie nowej klasy dokumentu i nowych pól (wyłącznie konfiguracja)

Aplikacja `json4win` oddziela **silnik przetwarzania** od **wiedzy o typach dokumentów**
(architektura D6, D12). Cały kod w `json4win/json4win/` (`config.py`, `prompts.py`, `decide.py`,
`extract.py`, `validate.py`, `pipeline.py`) jest generyczny: klasyfikacja, doczytywanie stron OCR,
prompt ekstrakcji, normalizacja i walidacja są generowane automatycznie z plików YAML.

Dodanie **nowego typu dokumentu** albo **nowego pola** w istniejącym dokumencie nie wymaga żadnej
zmiany w kodzie Pythona.

> Gotowy, działający przykład nowej klasy z tej samej domeny (ogłoszenie o zamówieniu z Biuletynu
> Zamówień Publicznych) znajduje się w
> [`json4win/config_examples/ogloszenie_bzp.yaml`](../json4win/config_examples/ogloszenie_bzp.yaml).
> Plik leży poza `json4win/config/`, ponieważ w domyślnej ewaluacji konkursowej dokumenty spoza
> trzech klas podstawowych muszą zwracać `{}`. Można go włączyć bez kopiowania plików zmienną
> środowiskową `JSON4WIN_CONFIG_DIRS`.

---

## Kreator w GUI („Nowa klasa”)

Nową klasę dokumentu można utworzyć także z poziomu lokalnego interfejsu webowego (`python -m json4win --gui`,
pozycja **Nowa klasa** w menu po lewej lub adres `/wizard`). Kreator prowadzi przez trzy etapy (lewy panel;
etap otwiera się, gdy poprzedni ma wynik). Pole **Wskazówka dla LLM** w lewym panelu (opcjonalne) trafia do
propozycji kształtu JSON i YAML; **Nowa sesja** usuwa przykłady i szkic po potwierdzeniu:

1. **Przykłady PDF** — wgranie 1–5 przykładowych plików PDF nowej klasy (do osobnego katalogu roboczego
   poza `output/` i `input/`). Każda strona do limitu `N` (domyślnie 2, edytowalne) przechodzi przez
   lokalny OCR (`json4win.ocr`, z cache; warstwa tekstowa PDF nie jest używana; pole **Strony OCR**). Tekst
   OCR każdej strony można rozwinąć na liście plików, a przykład z błędem usunąć przyciskiem **Usuń**.
2. **Kształt JSON** — model LLM proponuje `szablon` (obiekty, listy, liście `null`), typy pól (`str`, `int`,
   `float`) oraz podgląd wartości wyciągniętych z przykładów. Interaktywny edytor struktury pól
   (**Dodaj pole**, zmiana nazw, **Wyżej**/**Niżej**, **Usuń**, obiekt vs. lista, typ liścia) działa dwukierunkowo
   z edytorem surowego JSON-a (z walidacją składni na żywo). Przycisk **Odśwież podgląd** ponownie
   odpytuje LLM o podgląd dla zmodyfikowanego kształtu.
3. **Konfiguracja YAML** — model LLM generuje resztę pliku YAML (`id`, `nazwa`, `opis`, `cechy`,
   `nie_mylic_z`, `czytanie`, reguły `pola` dla każdego liścia ze zmyślonymi `przyklady` oraz `instrukcje`).
   Edytor YAML waliduje plik na żywo przez właściwy loader (`json4win.config.load_class`) z numerami linii,
   testuje regex `czytanie.znacznik` na odczytanych stronach OCR (zakładka **Znacznik**), a przycisk **Testuj**
   uruchamia pełny potok (decyzja + czytanie + ekstrakcja) na wgranych przykładach (zakładka **Test**).

**Gdzie kreator zapisuje plik:** kliknięcie **Zapisz** zapisuje `<id>.yaml` w pierwszym katalogu
wskazanym w zmiennej środowiskowej `JSON4WIN_CONFIG_DIRS`, a jeśli nie jest ustawiona — w `json4win/config/`.
Istniejący plik nigdy nie jest nadpisywany bez wyraźnego potwierdzenia na stronie. Dostępna jest również
akcja **Pobierz YAML**. Zapisany plik jest od razu ładowany przez standardowy loader bez zmian w kodzie.

---

## Część 1. Nowa klasa dokumentu — krok po kroku

### Krok 1. Skopiuj wzór pliku klasy

Skopiuj istniejący plik klasy (np. [`json4win/config/przelew.yaml`](../json4win/config/przelew.yaml))
albo przykład [`json4win/config_examples/ogloszenie_bzp.yaml`](../json4win/config_examples/ogloszenie_bzp.yaml)
pod nową nazwą `<id>.yaml`:

- **Do trwałego włączenia** w aplikacji: zapisz plik w `json4win/config/<id>.yaml`.
- **Do testów / demonstracji bez zmiany domyślnego zachowania**: zapisz plik w osobnym katalogu
  (np. `json4win/config_examples/<id>.yaml`) i przekaż ten katalog w zmiennej `JSON4WIN_CONFIG_DIRS`.

Zasady nazewnictwa:
- wartość `id` wewnątrz pliku musi być identyczna z nazwą pliku bez rozszerzenia `.yaml` / `.yml`,
- identyfikator `inne` jest zarezerwowany dla dokumentów nierozpoznanych (wynik `{}`),
- pozostałe pliki w `json4win/config/` (`README.md`, `prompt_*.md`) są przez loader ignorowane.

### Krok 2. Opisz klasę dla modelu decyzyjnego

Na etapie klasyfikacji silnik buduje prompt z `json4win/config/prompt_decyzja.md`, wstawiając
opisy wszystkich załadowanych klas. Model decyzyjny dostaje tekst pierwszej strony z OCR i zwraca
`{"klasa": "<id>"}` albo `{"klasa": "inne"}`.

Wypełnij sekcję identyfikującą klasę:

```yaml
id: ogloszenie_bzp
nazwa: Ogłoszenie o zamówieniu (BZP)

opis: >-
  Ogłoszenie o zamówieniu publicznym opublikowane w Biuletynie Zamówień Publicznych (BZP)
  na platformie eZamówienia (eZamowienia.gov.pl), oznaczone numerem w formacie RRRR/BZP NNNNNNNN
  i podzielone na numerowane sekcje („SEKCJA I - ZAMAWIAJĄCY”, „SEKCJA II – INFORMACJE
  PODSTAWOWE” itd.).

cechy:
  - "nagłówek z numerem w formacie RRRR/BZP NNNNNNNN oraz tytuł „Ogłoszenie o zamówieniu”"
  - "stopka zawierająca nazwę „Biuletyn Zamówień Publicznych”"
  - "numerowane sekcje formularza BZP: SEKCJA I, SEKCJA II, SEKCJA IV"

nie_mylic_z:
  - "odwołanie do KIO, nawet jeśli w treści przywołuje numer ogłoszenia BZP"
  - "ogłoszenie z Dziennika Urzędowego UE (TED / OJ S)"
  - "pełnomocnictwo ani potwierdzenie przelewu bankowego"
```

- `id`, `nazwa`, `opis` są **wymagane**.
- `cechy` i `nie_mylic_z` są opcjonalne, ale znacząco zmniejszają liczbę pomyłek (fałszywych trafień)
  między podobnymi dokumentami.

### Krok 3. Ustaw strategię czytania stron OCR (`czytanie`)

Lokalny OCR na CPU jest najwolniejszym etapem potoku, dlatego każda klasa określa, ile stron
maksymalnie czytać i kiedy zatrzymać OCR wcześniej:

```yaml
czytanie:
  max_stron: 3
  znacznik: '(?i)SEKCJA\s+IV\b'
  stron_po_znaczniku: 0
```

Dostępne pola sekcji `czytanie`:

| Klucz | Wymagany | Działanie |
|---|---|---|
| `max_stron` | tak (`>= 1`) | Twardy limit stron czytanych przez OCR dla tej klasy. |
| `znacznik` | nie | Wyrażenie regularne (`re.search`) na dotąd odczytanym tekście. Po pierwszym dopasowaniu silnik doczyta jeszcze `stron_po_znaczniku` stron i przerywa OCR. |
| `stron_po_znaczniku` | nie (domyślnie `0`) | Liczba dodatkowych stron po stronie ze znacznikiem. |
| `kompletny_gdy` | nie | Pytanie po polsku dla modelu decyzyjnego (`prompt_kompletnosc.md`), używane gdy `znacznik` nie jest ustawiony albo jeszcze nie dopasował. Odpowiedź twierdząca przerywa OCR. |

W przykładzie `ogloszenie_bzp.yaml` wszystkie wymagane pola mieszczą się w sekcjach I, II i IV
(zwykle strony 1–2). Znacznik `(?i)SEKCJA\s+IV\b` zatrzymuje OCR po 2. stronie i pomija resztę
dokumentu. Jeśli ani `znacznik`, ani `kompletny_gdy` nie są ustawione, silnik czyta do `max_stron`
(np. `max_stron: 1` dla jednostronicowego przelewu).

### Krok 4. Zdefiniuj kształt wyniku (`szablon`)

Sekcja `szablon` definiuje dokładny kształt obiektu JSON zwracanego przez aplikację — nazwy kluczy,
ich kolejność, zagnieżdżenia obiektów i listy:

```yaml
szablon:
  ogloszenie_bzp:
    numer_bzp: null
    wersja: null
    data_publikacji: null
    tytul: null
    rodzaj_zamowienia: null
    numer_referencyjny: null
    glowny_kod_cpv: null
    zamawiajacy:
      nazwa: null
      regon: null
      miejscowosc: null
      kod_pocztowy: null
      email: null
```

Zasady dla `szablon`:
- każdy liść (pole końcowe) musi mieć wartość `null`,
- zagnieżdżone obiekty w wyniku nigdy nie są `null` (brak danych oznacza `null` w ich liściach),
- jeżeli klasa zwraca listę obiektów (np. wielu wykonawców lub pełnomocników), w szablonie lista ma
  **dokładnie jeden** element będący wzorem każdego elementu listy (w wyniku może być `1..n` elementów):

```yaml
szablon:
  wykonawcy:
    - nazwa: null
      nip: null
```

### Krok 5. Opisz pola (`pola`) i ewentualne `instrukcje`

Sekcja `pola` zawiera **dokładnie jeden wpis dla każdego liścia** z `szablon` (loader sprawdza
zgodność 1:1). Ścieżki łączą nazwy kluczy kropką (`a.b`), a element listy oznaczają przez `[]`
(np. `wykonawcy[].nip`).

```yaml
pola:
  ogloszenie_bzp.numer_bzp:
    opis: >-
      Numer ogłoszenia w BZP w formacie RRRR/BZP NNNNNNNN z pola „2.5.) Numer ogłoszenia”.
      Zwróć null, jeśli brak numeru.
    typ: str
    normalizacja: text
    format: '^\d{4}/BZP \d{8}$'
    przyklady: ["2029/BZP 00412345"]
    poprawki_ocr: "W cyfrach poprawiaj literówki OCR (O→0, l/I→1, S→5, B→8)."

  ogloszenie_bzp.wersja:
    opis: Numer wersji ogłoszenia jako liczba całkowita (np. „01” → 1).
    typ: int
    normalizacja: int
    przyklady: [1, 2]

  ogloszenie_bzp.data_publikacji:
    opis: Data publikacji ogłoszenia w formacie RRRR-MM-DD (pole „2.7.) Data ogłoszenia”).
    typ: str
    normalizacja: date
    format: '^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$'
    przyklady: ["2029-06-18"]

  ogloszenie_bzp.rodzaj_zamowienia:
    opis: Rodzaj zamówienia z pierwszej strony lub pola „4.1.3.) Rodzaj zamówienia”.
    typ: str
    normalizacja: text
    wartosci:
      uslugi: "Usługi"
      dostawy: "Dostawy"
      roboty_budowlane: "Roboty budowlane"

  ogloszenie_bzp.glowny_kod_cpv:
    opis: Główny kod CPV (8 cyfr, myślnik, 1 cyfra) z pola „4.2.6.) Główny kod CPV”.
    typ: str
    normalizacja: regex_sub
    parametry:
      pattern: '^\s*(\d{8}-\d)\b.*$'
      repl: '\1'
    format: '^\d{8}-\d$'
    przyklady: ["30200000-1"]
```

Wszystkie atrybuty pojedynczego pola w `pola`:

| Atrybut | Wymagany | Opis |
|---|---|---|
| `opis` | tak | Co oznacza pole, gdzie go szukać w dokumencie i kiedy zwrócić `null`. |
| `typ` | nie (domyślnie `str`) | Typ wartości w JSON: `str`, `int` lub `float`. |
| `normalizacja` | nie | Deterministyczny normalizator uruchamiany po odpowiedzi LLM (tabela poniżej). |
| `parametry` | tylko dla `regex_sub` | Parametry normalizatora (`pattern` i `repl` dla `regex_sub`). |
| `format` | nie | Twarde wyrażenie regularne (`re.fullmatch` po normalizacji). Naruszenie uruchamia poprawkę u modelu (`prompt_poprawka.md`, maks. 2 próby); po niepowodzeniu pole dostaje `null`. |
| `wartosci` | nie | Zbiór zamknięty: słownik `dozwolona_wartość: opis`. Klucze muszą mieć typ zgodny z `typ`. |
| `przyklady` | nie | Lista krótkich, **zmyślonych** przykładów zgodnych z `typ` i `format`. |
| `poprawki_ocr` | nie | Wskazówka, jakie literówki OCR model może korygować w tym polu. |

Dostępne normalizatory (`normalizacja`, zaimplementowane w `json4win/json4win/normalize.py`):

| Nazwa | Działanie |
|---|---|
| `text` | Scala wielokrotne spacje i znaki nowej linii w pojedynczą spację, przycina brzegi; pusty ciąg → `null`. |
| `digits` | Zostawia wyłącznie cyfry ASCII (NIP, KRS z wiodącymi zerami, REGON, PESEL, 26-cyfrowy NRB). |
| `date` | Zamienia datę (`YYYY-MM-DD`, `DD.MM.YYYY`, polskie nazwy miesięcy, rzymskie miesiące) na `YYYY-MM-DD`. |
| `amount` | Parsuje kwotę (`"1 234,56 PLN"`, `"50,00 zł"`) na liczbę `float`. |
| `int` | Parsuje liczbę całkowitą (`"01"`, `"4."`, `4.0`) na `int`. |
| `regex_sub` | Wykonuje `re.sub(parametry.pattern, parametry.repl, str(wartość))` (np. wycięcie samego kodu CPV). |

Na końcu pliku możesz dodać opcjonalną sekcję `instrukcje` — dodatkowe reguły dla całej klasy
dołączane do promptu ekstrakcji (`prompt_ekstrakcja.md`).

### Krok 6. Uruchom i sprawdź wynik

1. **Szybka walidacja pliku YAML** (bez uruchamiania OCR ani LLM — sprawdza format, regexy, typy
   i zgodność `szablon` ↔ `pola`):

   ```bash
   cd json4win
   python -c "from pathlib import Path; from json4win.config import load_class; print(load_class(Path('config_examples/ogloszenie_bzp.yaml')).id)"
   ```

2. **Uruchomienie aplikacji z dodatkowym katalogiem klas (`JSON4WIN_CONFIG_DIRS`)** bez przenoszenia
   plików do `json4win/config/`:

   Linux / macOS:
   ```bash
   cd json4win
   JSON4WIN_CONFIG_DIRS=config_examples python -m json4win --input /sciezka/do/pdf --output /sciezka/wynik -v
   ```

   Windows (wiersz poleceń `cmd`):
   ```bat
   cd json4win
   set JSON4WIN_CONFIG_DIRS=config_examples
   python -m json4win --input C:\sciezka\do\pdf --output C:\sciezka\wynik -v
   ```

   Zmienna `JSON4WIN_CONFIG_DIRS` przyjmuje jedną lub więcej ścieżek rozdzielonych separatorem
   systemowym (`:` na Linux/macOS, `;` na Windows), ładowanych po `json4win/config/`. Powtórzenie
   identyfikatora klasy (`id`) kończy się czytelnym błędem `ConfigError`.

3. **Sprawdzenie wyniku**: w logu (`-v`) pojawi się rozpoznana klasa i liczba odczytanych stron, np.:

   ```text
   ogloszenie.pdf: class=ogloszenie_bzp pages=2 retries=0 nulled=-
   ```

   a w katalogu wyjściowym powstanie odpowiadający plik JSON zgodny z `szablon`:

   ```json
   {
     "ogloszenie_bzp": {
       "numer_bzp": "2029/BZP 00412345",
       "wersja": 1,
       "data_publikacji": "2029-06-18",
       "tytul": "Dostawa sprzętu komputerowego dla Urzędu Gminy w Przykładowie",
       "rodzaj_zamowienia": "dostawy",
       "numer_referencyjny": "ZP.271.14.2029",
       "glowny_kod_cpv": "30200000-1",
       "zamawiajacy": {
         "nazwa": "Gmina Przykładowo",
         "regon": "123456789",
         "miejscowosc": "Przykładowo",
         "kod_pocztowy": "00-950",
         "email": "zamowienia@przykladowo.example.pl"
       }
     }
   }
   ```

---

## Część 2. Dodanie pojedynczego pola do istniejącej klasy

Żeby dodać nowe pole do już działającej klasy (np. pole `waluta` w `json4win/config/przelew.yaml`),
wystarczą **dwie zmiany w tym jednym pliku YAML**:

1. **Dodaj klucz w `szablon`** (z wartością `null`):

   ```yaml
   szablon:
     przelew_bankowy:
       data_operacji: null
       kwota: null
       waluta: null          # <-- nowy klucz
       na_rachunek: null
       ...
   ```

2. **Dodaj odpowiadający wpis w `pola`**:

   ```yaml
   pola:
     ...
     przelew_bankowy.waluta:
       opis: Trzyliterowy kod waluty przelewu (np. PLN, EUR). Zwróć null, jeśli brak waluty.
       typ: str
       normalizacja: text
       wartosci:
         PLN: "polski złoty (PLN, zł)"
         EUR: "euro (EUR, €)"
       przyklady: ["PLN"]
   ```

Po zapisaniu pliku silnik automatycznie:
- zweryfikuje spójność `szablon` i `pola` przy starcie,
- dopisze nowe pole (wraz z opisem, typem, formatem i dozwolonymi wartościami) do promptu ekstrakcji,
- znormalizuje i zwaliduje jego wartość (z ewentualną poprawką przez model),
- zapisze je w wyjściowym pliku JSON w dokładnie tym miejscu, w którym zostało dodane w `szablon`.

---

## Najczęstsze błędy wykrywane automatycznie przez loader

Loader (`json4win/json4win/config.py`) sprawdza każdy plik klasy przed uruchomieniem przetwarzania
i zgłasza czytelny błąd `ConfigError` w przypadku:
- niezgodności `id` z nazwą pliku lub użycia zarezerwowanego `id: inne`,
- braku wpisu w `pola` dla któregokolwiek liścia z `szablon` (albo nadmiarowego klucza w `pola`),
- liścia w `szablon` o wartości innej niż `null` albo listy w `szablon` zawierającej inną liczbę
  wzorów niż 1,
- nieznanego `typ` lub `normalizacja`, braku `pattern`/`repl` dla `regex_sub` albo niepoprawnego
  wyrażenia regularnego w `znacznik`, `format` lub `parametry.pattern`,
- klucza w `wartosci` o typie niezgodnym z `typ` pola (np. napis `"1"` przy `typ: int`),
- duplikatu `id` między `json4win/config/` a katalogiem z `JSON4WIN_CONFIG_DIRS` lub nieistniejącego
  katalogu w `JSON4WIN_CONFIG_DIRS`.
