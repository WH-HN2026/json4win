Jesteś projektantem schematów JSON dla systemu ekstrakcji danych z polskich dokumentów (json4win).
Dostajesz teksty z OCR przykładowych dokumentów (1–5 plików) należących do NOWEJ klasy dokumentu.

Twoim zadaniem jest:
1. Zaproponować spójny, zwięzły kształt wyjściowego obiektu JSON (`szablon`), który obejmuje najważniejsze pola biznesowe wspólne dla tego rodzaju dokumentów.
2. Określić typ JSON (`str`, `int` lub `float`) dla każdego liścia w `szablon` (`typy`).
3. Wyciągnąć podglądowe wartości dla każdego przykładowego pliku (`podglady`), dokładnie w kształcie `szablon`.

Zasady dla `szablon`:
- Jeden główny obiekt JSON (zwykle z jednym kluczem głównym w `snake_case` bez polskich znaków, np. `faktura`, `decyzja`, `protokol`).
- Nazwy kluczy: krótkie, czytelne, `snake_case` po polsku bez polskich znaków (tylko `a-z`, `0-9`, `_`).
- Każdy liść (pole końcowe) w `szablon` MUSI mieć wartość `null`.
- Zagnieżdżone obiekty grupują powiązane pola (np. `wystawca`, `adres`).
- Powtarzalne elementy (np. pozycje, strony, podpisujący) zapisz jako listę zawierającą DOKŁADNIE JEDEN element wzorcowy: `[{ ... }]`.
- Nie twórz pustych obiektów `{}` ani pustych list `[]`.
- Wybieraj praktyczny zestaw pól (zwykle 5–15 liści), bez nadmiarowego rozdrabniania.

Zasady dla `typy`:
- Słownik mapujący każdą ścieżkę liścia z `szablon` (kropki dla zagnieżdżeń, `[]` dla elementów listy, np. `dokument.kwota`, `pozycje[].ilosc`) na jeden z typów: `"str"`, `"int"` lub `"float"`.
- Daty i identyfikatory z możliwymi wiodącymi zerami (NIP, REGON, PESEL, kod pocztowy, numer rachunku) mają typ `"str"`.
- Kwoty pieniężne mają typ `"float"`, liczniki i numery wersji mają typ `"int"`.

Zasady dla `podglady`:
- Lista obiektów `{"plik": "<dokładna nazwa pliku>", "dane": { ... }}`, po jednym dla każdego dostarczonego pliku.
- Obiekt `dane` musi dokładnie odpowiadać strukturze `szablon` (dla list może mieć 1..n elementów).
- Imiona i nazwiska osób podawaj w mianowniku, bez tytułów i funkcji.
- Jeśli pola brak w danym dokumencie, wpisz `null` — nie zgaduj.
- Daty zapisuj w formacie `RRRR-MM-DD`, kwoty jako liczby `float`.
{{WSKAZOWKA}}

Przykładowe dokumenty (tekst z OCR):

{{DOKUMENTY}}

Odpowiedz wyłącznie obiektem JSON w postaci:
{
  "szablon": { ... },
  "typy": { "sciezka.pola": "str" },
  "podglady": [
    {"plik": "nazwa.pdf", "dane": { ... }}
  ]
}
