import pytest

from voice_agent.crm.matching import (
    digits,
    last_name_matches,
    model_matches,
    name_matches,
    normalize_phone,
)


@pytest.mark.parametrize(
    "said",
    [
        "Jana Müller",
        "Jana Mueller",
        "jana muller",
        "Frau Müller",
        "Müller",
        "Dr. Jana Müller",
    ],
)
def test_a_name_matches_after_normalization(said: str) -> None:
    assert name_matches(said, "Jana", "Müller")


@pytest.mark.parametrize("said", ["Anna Müller", "Jana Miller", "Jana", ""])
def test_another_name_doesnt_match(said: str) -> None:
    assert not name_matches(said, "Jana", "Müller")


def test_the_last_name_alone_is_enough_for_tickets() -> None:
    assert last_name_matches("Christina Schroeder", "Schröder")
    assert last_name_matches("Krüger", "Krüger")
    assert not last_name_matches("Krugman", "Krüger")


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("456789", "456789"),
        ("4 5 6 7 8 9", "456789"),
        ("four five six seven eight nine", "456789"),
        ("eins null eins eins fünf", "10115"),
        ("CC-10003", "10003"),
    ],
)
def test_spoken_digits(said: str, expected: str) -> None:
    assert digits(said) == expected


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("+49 151 22000201", "+4915122000201"),
        ("0049 151 22000201", "+4915122000201"),
        ("0151 22000201", "+4915122000201"),
        ("+49 (0) 151 22000201", "+4915122000201"),
    ],
)
def test_german_phone_numbers_become_e164(said: str, expected: str) -> None:
    assert normalize_phone(said) == expected


@pytest.mark.parametrize("said", ["12345", "+44 20 7946 0958", "hello"])
def test_other_numbers_are_not_german_phone_numbers(said: str) -> None:
    assert normalize_phone(said) is None


@pytest.mark.parametrize(
    "said", ["X5", "my new x5", "BMW X5 xDrive50e", "the X5 plug-in", "X 5"]
)
def test_the_model_matches_loosely(said: str) -> None:
    assert model_matches(said, "BMW X5 xDrive50e")


@pytest.mark.parametrize("said", ["iX", "X3", "Touring", "a BMW", ""])
def test_another_model_doesnt_match(said: str) -> None:
    assert not model_matches(said, "BMW X5 xDrive50e")


def test_ix3_and_ix_are_different_models() -> None:
    assert model_matches("iX3", "BMW iX3 50 xDrive")
    assert model_matches("i X 3", "BMW iX3 50 xDrive")
    assert not model_matches("iX", "BMW iX3 50 xDrive")
    assert not model_matches("Touring", "BMW 330e Touring")
    assert model_matches("330e", "BMW 330e Touring")
