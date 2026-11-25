import pytest

from app.domain.br import UFS, is_valid_cep, is_valid_cpf, normalize_phone


@pytest.mark.parametrize("cpf", ["12345678909", "11144477735"])
def test_valid_cpfs(cpf):
    assert is_valid_cpf(cpf)


@pytest.mark.parametrize(
    "cpf",
    ["12345678900", "11111111111", "00000000000", "123.456.789-09", "1234567890", "1234567890a"],
)
def test_invalid_cpfs(cpf):
    assert not is_valid_cpf(cpf)


def test_cep():
    assert is_valid_cep("88303575")
    assert not is_valid_cep("88303-575")


def test_ufs():
    assert len(UFS) == 27 and "SC" in UFS and "DF" in UFS


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+5548999999999", "+5548999999999"),  # BR mobile
        ("+55 (48) 3333-4444", "+554833334444"),  # BR landline, formatted
        ("+12025550123", "+12025550123"),  # US
        ("+5548999", None),  # too short
        ("48999999999", None),  # no country code
        ("+abc", None),
    ],
)
def test_phone(raw, expected):
    assert normalize_phone(raw) == expected
