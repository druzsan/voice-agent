import pytest

from voice_agent.usage import TokenPrice, Usage, combine


def test_calls_of_one_model_are_added_up() -> None:
    sentence = Usage(
        service="tts",
        model="tts-model",
        input_tokens=10,
        audio_out_s=1.5,
        duration_ms=400,
        cost_usd=0.01,
    )
    llm = Usage(service="llm", model="llm-model", output_tokens=30, cost_usd=0.002)

    totals = combine([sentence, llm, None, sentence])

    assert totals == [
        Usage(
            service="tts",
            model="tts-model",
            calls=2,
            input_tokens=20,
            audio_out_s=3.0,
            duration_ms=800,
            cost_usd=0.02,
        ),
        llm,
    ]


def test_one_unknown_price_makes_the_total_unknown() -> None:
    known = Usage(service="stt", model="m", cost_usd=0.01)
    unknown = Usage(service="stt", model="m", cost_usd=None)

    assert combine([known, unknown])[0].cost_usd is None


def test_cached_tokens_cost_less() -> None:
    price = TokenPrice(input=2e-6, cached_input=1e-7, output=1e-5)

    assert price.cost(1000, 400, 100) == pytest.approx(
        600 * 2e-6 + 400 * 1e-7 + 100 * 1e-5
    )


def test_costs_carry_no_float_noise() -> None:
    usage = Usage(service="stt", model="m", cost_usd=9.0 * 0.017 / 60)

    assert usage.cost_usd == 0.00255
