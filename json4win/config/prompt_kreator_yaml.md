Jesteś ekspertem od konfiguracji klas dokumentów w systemie json4win.
Na podstawie podanego szablonu JSON (`szablon`) oraz przykładowych tekstów z OCR wygeneruj kompletną konfigurację nowej klasy dokumentu jako obiekt JSON (który zostanie zapisany do pliku YAML zgodnego ze schematem `json4win/config/README.md`).

Szablon JSON wybrany przez użytkownika (NIE zmieniaj jego kluczy ani struktury):
```json
{{SZABLON}}
```

Ścieżki liści i ich wymagane typy (każda ścieżka MUSI mieć dokładnie jeden wpis w `pola`):
{{SCIEZKI}}

Istniejące identyfikatory klas w systemie (nowe `id` musi być inne niż te oraz inne niż `inne`):
{{ISTNIEJACE_KLASY}}
{{WSKAZOWKA}}

Wymagane pola odpowiedzi JSON:
- `id`: krótki identyfikator klasy w ASCII (`^[a-z][a-z0-9_]*$`), unikalny, różny od `inne`.
- `nazwa`: czytelna polska nazwa klasy dokumentu.
- `opis`: 1–4 zdania po polsku opisujące dokument dla modelu decyzyjnego (co to jest, skąd pochodzi, jakie ma główne elementy).
- `cechy`: lista 2–5 krótkich, konkretnych cech układu lub treści typowych dla tej klasy (wskazówki dla modelu decyzyjnego).
- `nie_mylic_z`: lista 2–4 podobnych typów dokumentów, które NIE należą do tej klasy.
- `czytanie`: obiekt sterujący liczbą stron OCR:
  - `max_stron`: liczba całkowita >= 1 (twardy limit stron czytanych dla tej klasy).
  - `znacznik`: opcjonalne wyrażenie regularne Pythona (`re.search`), np. `"(?i)SEKCJA\\s+IV\\b"` lub charakterystyczna fraza zamykająca obszar danych; albo `null`, jeśli niepotrzebny (np. dokument jednostronicowy).
  - `stron_po_znaczniku`: liczba całkowita >= 0 (domyślnie `0`).
  - `kompletny_gdy`: opcjonalne pytanie/warunek po polsku dla modelu decyzyjnego (albo `null`).
- `pola`: słownik zawierający DOKŁADNIE jeden wpis dla każdej ścieżki z listy powyżej (bez pominięć i bez dodatkowych kluczy). Każdy wpis ma:
  - `opis` (wymagane): po polsku — co oznacza pole, gdzie zwykle występuje w dokumencie i kiedy zwrócić `null`. Dla imion i nazwisk osób wyraźnie wskaż mianownik bez tytułów i funkcji.
  - `typ`: dokładnie typ z listy ścieżek (`"str"`, `"int"` albo `"float"`).
  - `normalizacja`: jeden z `"text"`, `"digits"`, `"date"`, `"amount"`, `"int"`, `"regex_sub"` albo `null`.
  - `parametry`: tylko gdy `normalizacja` to `"regex_sub"` — `{"pattern": "...", "repl": "..."}`, w przeciwnym razie `null`.
  - `format`: opcjonalne wyrażenie regularne Pythona (`re.fullmatch` po normalizacji) WYŁĄCZNIE dla pól o sztywnym formacie (daty `^\\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\\d|3[01])$`, NIP `^\\d{10}$`, kod pocztowy `^\\d{2}-\\d{3}$` itp.). Dla tekstu wolnego (nazwy, adresy, tytuły) wpisz `null`!
  - `wartosci`: opcjonalny słownik `{wartosc: "znaczenie"}` WYŁĄCZNIE dla zbioru zamkniętego (klucze muszą być zgodne z `typ`); inaczej `null`.
  - `przyklady`: lista 1–2 krótkich przykładów w poprawnym formacie (zgodnych z `typ` i `format`).
  - `poprawki_ocr`: opcjonalna krótka wskazówka korekty literówek OCR (np. `"W cyfrach poprawiaj O→0, l/I→1."`) lub `null`.
- `instrukcje`: opcjonalny krótki akapit instrukcji ekstrakcji dla całej klasy (lub `null`).

KRYTYCZNA ZASADA (D9 — brak kopiowania danych z przykładów):
- Wszystkie wartości w `przyklady` (a także przykładowe numery czy nazwy w `opis`, `cechy`, `instrukcje`) MUSZĄ być **całkowicie zmyślone** (fikcyjne, w poprawnym formacie, np. `"Jan Kowalski"`, `"2031-04-17"`, `"1234567890"`, `"Spółka Przykładowa sp. z o.o."`, `"00-950"`).
- **NIGDY nie kopiuj** żadnych rzeczywistych nazwisk, nazw firm, NIP-ów, numerów spraw, numerów rachunków, dat, adresów ani tytułów z przykładowych dokumentów poniżej!

Przykładowe dokumenty (tekst z OCR):

{{DOKUMENTY}}

Odpowiedz wyłącznie obiektem JSON zawierającym klucze: `id`, `nazwa`, `opis`, `cechy`, `nie_mylic_z`, `czytanie`, `pola`, `instrukcje`.
