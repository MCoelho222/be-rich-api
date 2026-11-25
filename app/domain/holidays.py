"""Brazilian national bank holidays (specs/schemas.md §17.1).

Used to seed the `holiday` table. Includes national holidays plus the days banks
close nationwide (Carnival Monday/Tuesday, Good Friday, Corpus Christi).
Municipal and state holidays are out of scope.
Verify against the FEBRABAN calendar when the list is reviewed.
"""

from datetime import date, timedelta


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm / Meeus-Jones-Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - name from the published algorithm
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def brazil_bank_holidays(year: int) -> dict[date, str]:
    """National bank holidays for `year`, keyed by date."""
    easter = easter_sunday(year)
    holidays = {
        date(year, 1, 1): "Confraternização Universal",
        easter - timedelta(days=48): "Carnaval (segunda-feira)",
        easter - timedelta(days=47): "Carnaval (terça-feira)",
        easter - timedelta(days=2): "Sexta-feira Santa",
        date(year, 4, 21): "Tiradentes",
        date(year, 5, 1): "Dia do Trabalho",
        easter + timedelta(days=60): "Corpus Christi",
        date(year, 9, 7): "Independência do Brasil",
        date(year, 10, 12): "Nossa Senhora Aparecida",
        date(year, 11, 2): "Finados",
        date(year, 11, 15): "Proclamação da República",
        date(year, 12, 25): "Natal",
    }
    if year >= 2024:  # national holiday since Lei 14.759/2023
        holidays[date(year, 11, 20)] = "Dia Nacional de Zumbi e da Consciência Negra"
    return holidays
