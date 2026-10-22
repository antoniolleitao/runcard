from runcard.yamlinputs import parse_scalar, parse_simulation_inputs, resolved_inputs_from_yaml

from conftest import SIM_INPUTS_YAML


def test_parses_blocks_with_value_and_units():
    r = resolved_inputs_from_yaml(SIM_INPUTS_YAML.format(temperature=350))
    assert r["Na"]["value"] == 2e15
    assert r["Na"]["units"] == "1 / centimeter ** 3"
    assert r["Na"]["min"] == 1 and r["Na"]["max"] == 2e22
    assert r["temperature"]["value"] == 350
    assert r["temperature"]["units"] == "kelvin"
    assert r["materialp"]["value"] == "Si"
    assert r["materialp"]["units"] is None
    assert r["impurity"]["value"] is False
    assert r["n_node"]["value"] == 120 and isinstance(r["n_node"]["value"], int)


def test_every_input_listed():
    r = resolved_inputs_from_yaml(SIM_INPUTS_YAML.format(temperature=300))
    assert set(r) == {"Na", "Nd", "temperature", "vsweep_high", "materialp", "impurity", "n_node"}


def test_inline_scalar_and_quotes_and_comments():
    text = "# header comment\nfoo: 'bar'\nbaz:\n    value: \"1e3\"\n    units: K   \n\nqux: 7\n"
    r = parse_simulation_inputs(text)
    assert r["foo"] == {"value": "bar"}
    assert r["baz"]["value"] == "1e3"  # quoted stays string
    assert r["baz"]["units"] == "K"
    assert r["qux"] == {"value": 7}


def test_lists_and_colons_in_values():
    text = "a:\n    value: 1:2:3\n    options:\n        - x\n        - 2\n"
    r = parse_simulation_inputs(text)
    assert r["a"]["value"] == "1:2:3"
    assert r["a"]["options"] == ["x", 2]


def test_scalars():
    assert parse_scalar("2e15") == 2e15
    assert parse_scalar("-5") == -5
    assert parse_scalar("0.6") == 0.6
    assert parse_scalar("true") is True
    assert parse_scalar("null") is None
    assert parse_scalar("[1, 2]") == [1, 2]
    assert parse_scalar("Si") == "Si"


def test_empty_and_garbage_do_not_raise():
    assert parse_simulation_inputs("") == {}
    assert parse_simulation_inputs(None) == {}
    assert parse_simulation_inputs("just text without colon\n    - orphan\n") == {}
