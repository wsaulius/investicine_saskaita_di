from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from parse_ib import (
    _load_patterns,
    _resolve_pattern_references,
    _extract_country_from_api_payload,
    IsinCountryResolver,
    classify_swedbank_row,
    default_swedbank_rules,
    extract_isin,
    generate_vmi_csv,
    load_swedbank_rules,
    parse_swedbank_csv,
    resolve_country_from_instrument_id,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _write_rules(tmp_path: Path, body: str) -> Path:
    rules_path = tmp_path / 'rules.yaml'
    rules_path.write_text(textwrap.dedent(body).strip() + '\n', encoding='utf-8')
    return rules_path


def test_load_patterns_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert _load_patterns(str(tmp_path / 'missing-patterns.json')) == {}


def test_load_patterns_reads_named_collections(tmp_path: Path) -> None:
    patterns_path = tmp_path / 'patterns.json'
    _write_json(
        patterns_path,
        {
            'patterns': {
                'funds': {'type': 'literal', 'patterns': ['alpha', 'beta']},
                'providers': {'type': 'literal', 'patterns': 'synergy'},
            }
        },
    )

    assert _load_patterns(str(patterns_path)) == {
        'funds': ['alpha', 'beta'],
        'providers': ['synergy'],
    }


def test_resolve_pattern_references_expands_mixed_values() -> None:
    patterns = {
        'fund_purchases': ['Fondų pirkimas', 'Už įsigyjamus fondo vienetus'],
        'providers': ['SYNERGY FINANCE'],
    }

    resolved = _resolve_pattern_references(
        ['@fund_purchases', 'inline literal', '@providers'],
        patterns,
    )

    assert resolved == [
        'Fondų pirkimas',
        'Už įsigyjamus fondo vienetus',
        'inline literal',
        'SYNERGY FINANCE',
    ]


def test_extract_isin_finds_first_isin_in_text() -> None:
    assert extract_isin('DIVIDENDAI / AGNC INVESTMENT CORP / US00123Q1040 / 0.12 USD') == 'US00123Q1040'
    assert extract_isin('no isin here') is None


def test_extract_country_from_api_payload_finds_nested_country_code() -> None:
    payload = [
        {
            'data': [
                {'meta': {'countryCode': 'lu'}},
            ]
        }
    ]

    assert _extract_country_from_api_payload(payload) == 'LU'


def test_load_swedbank_rules_resolves_pattern_references(tmp_path: Path) -> None:
    _write_json(
        tmp_path / 'patterns.json',
        {
            'patterns': {
                'dividends': {'type': 'literal', 'patterns': ['DIVIDENDAI']},
                'fund_providers': {'type': 'literal', 'patterns': ['SYNERGY FINANCE']},
                'real_estate': {'type': 'literal', 'patterns': ['rontgen.lt']},
            }
        },
    )
    rules_path = _write_rules(
        tmp_path,
        """
        country: lt
        dividend_description_contains:
          - "@dividends"
        action_rules:
          - action: II
            when:
              code: MK
              receiver_contains:
                - "@fund_providers"
              description_contains:
                - "@real_estate"
                - inline trigger
        """,
    )

    rules = load_swedbank_rules(str(rules_path))

    assert rules['country'] == 'LT'
    assert rules['dividend_description_contains'] == ['DIVIDENDAI']
    assert rules['action_rules'] == [
        {
            'action': 'II',
            'when': {
                'code': 'MK',
                'receiver_contains': ['SYNERGY FINANCE'],
                'description_contains': ['rontgen.lt', 'inline trigger'],
            },
        }
    ]


def test_load_swedbank_rules_raises_for_unknown_pattern_reference(tmp_path: Path) -> None:
    _write_json(tmp_path / 'patterns.json', {'patterns': {}})
    rules_path = _write_rules(
        tmp_path,
        """
        action_rules:
          - action: II
            when:
              description_contains:
                - "@missing_collection"
        """,
    )

    with pytest.raises(RuntimeError, match='Unknown pattern reference: @missing_collection'):
        load_swedbank_rules(str(rules_path))


def test_isin_country_resolver_uses_api_country_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_fetch(self, isin: str):
        calls.append(isin)
        return [{'data': [{'country': 'US'}]}]

    monkeypatch.setattr(IsinCountryResolver, '_fetch_isin_metadata', fake_fetch)

    resolver = IsinCountryResolver(default_country='LT')

    assert resolver.resolve_description('AGNC / US00123Q1040') == 'US'
    assert resolver.resolve_description('Again / US00123Q1040') == 'US'
    assert calls == ['US00123Q1040']


def test_isin_country_resolver_logs_access_and_cache(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def fake_fetch(self, isin: str):
        return [{'data': [{'country': 'US'}]}]

    monkeypatch.setattr(IsinCountryResolver, '_fetch_isin_metadata', fake_fetch)

    resolver = IsinCountryResolver(default_country='LT')
    with caplog.at_level('INFO', logger='parse_ib.openfigi'):
        resolver.resolve_description('AGNC / US00123Q1040')
        resolver.resolve_description('AGNC / US00123Q1040')

    assert 'OpenFIGI cache miss for ISIN US00123Q1040' in caplog.text
    assert 'Accessing OpenFIGI for ISIN US00123Q1040' in caplog.text
    assert 'OpenFIGI resolved ISIN US00123Q1040 -> US' in caplog.text
    assert 'OpenFIGI cache hit for ISIN US00123Q1040 -> US' in caplog.text


def test_isin_country_resolver_falls_back_to_isin_prefix_when_api_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(self, isin: str):
        raise RuntimeError('temporary failure')

    monkeypatch.setattr(IsinCountryResolver, '_fetch_isin_metadata', fake_fetch)

    resolver = IsinCountryResolver(default_country='LT')
    assert resolver.resolve_description('UBS ETF / LU0446734369') == 'LU'
    assert resolver.resolve_description('no isin') == 'LT'


def test_isin_country_resolver_logs_failure_and_fallback(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def fake_fetch(self, isin: str):
        raise RuntimeError('temporary failure')

    monkeypatch.setattr(IsinCountryResolver, '_fetch_isin_metadata', fake_fetch)

    resolver = IsinCountryResolver(default_country='LT')
    with caplog.at_level('INFO', logger='parse_ib.openfigi'):
        result = resolver.resolve_description('UBS ETF / LU0446734369')

    assert result == 'LU'
    assert 'OpenFIGI lookup failed for ISIN LU0446734369: temporary failure' in caplog.text
    assert 'Using fallback country for ISIN LU0446734369 -> LU' in caplog.text


def test_resolve_country_from_instrument_id_uses_api_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(self, isin: str):
        return [{'data': [{'countryIso2': 'IE'}]}]

    monkeypatch.setattr(IsinCountryResolver, '_fetch_isin_metadata', fake_fetch)

    assert resolve_country_from_instrument_id('Instrument / US00123Q1040', 'LT') == 'IE'


@pytest.mark.parametrize(
    ('signed_amount', 'expected_action'),
    [
        (100.0, 'II'),
        (-100.0, 'PP'),
    ],
)
def test_classify_swedbank_row_auto_rule_falls_back_to_default_mapping(
    signed_amount: float,
    expected_action: str,
) -> None:
    rules = default_swedbank_rules()
    rules['exclude_codes'] = []
    rules['action_rules'] = [
        {
            'action': 'AUTO',
            'when': {'code': 'MK', 'description_contains': ['fallback trigger']},
        }
    ]

    action = classify_swedbank_row(
        code='MK',
        dk='K' if signed_amount > 0 else 'D',
        currency='EUR',
        desc='fallback trigger',
        receiver='Example',
        signed_amount=signed_amount,
        rules=rules,
    )

    assert action == expected_action


def test_classify_swedbank_row_honors_ordered_action_rules_before_fallback() -> None:
    rules = default_swedbank_rules()
    rules['exclude_codes'] = []
    rules['action_rules'] = [
        {'action': 'IGNORE', 'when': {'code': 'MK', 'description_contains': ['skip me']}},
        {'action': 'II', 'when': {'code': 'MK', 'description_contains': ['skip me']}},
    ]

    action = classify_swedbank_row(
        code='MK',
        dk='K',
        currency='EUR',
        desc='Please skip me completely',
        receiver='Example',
        signed_amount=100.0,
        rules=rules,
    )

    assert action is None


def test_classify_swedbank_row_maps_dividends_and_forced_rules() -> None:
    rules = default_swedbank_rules()
    rules['exclude_codes'] = []
    rules['force_deposit_description_contains'] = ['manual deposit']
    rules['force_withdrawal_description_contains'] = ['manual withdrawal']

    dividend = classify_swedbank_row(
        code='MK',
        dk='K',
        currency='USD',
        desc='DIVIDENDAI / AGNC',
        receiver='Broker',
        signed_amount=84.0,
        rules=rules,
    )
    forced_deposit = classify_swedbank_row(
        code='MK',
        dk='D',
        currency='EUR',
        desc='manual deposit despite debit direction',
        receiver='Broker',
        signed_amount=-25.0,
        rules=rules,
    )
    forced_withdrawal = classify_swedbank_row(
        code='MK',
        dk='K',
        currency='EUR',
        desc='manual withdrawal despite credit direction',
        receiver='Broker',
        signed_amount=25.0,
        rules=rules,
    )

    assert dividend == 'IV'
    assert forced_deposit == 'II'
    assert forced_withdrawal == 'PP'


def test_parse_swedbank_csv_real_statement_matches_expected_business_cases() -> None:
    rules = load_swedbank_rules(str(ROOT / 'rules.yaml'))

    stmt = parse_swedbank_csv(str(ROOT / 'source' / 'Swedbank_statement.csv'), rules=rules)

    assert stmt.account_id == 'LT657300010191116240'
    assert stmt.period_start == '2025-01-01'
    assert stmt.period_end == '2025-12-31'
    assert stmt.base_currency == 'EUR'
    assert stmt.eur_usd_rate == pytest.approx(1.1994)

    assert len(stmt.deposits_withdrawals) == 132
    assert len(stmt.dividends) == 13
    assert sum(1 for row in stmt.deposits_withdrawals if row.amount > 0) == 124
    assert sum(1 for row in stmt.deposits_withdrawals if row.amount < 0) == 8

    assert any('rontgen.lt' in row.description and row.amount == 1000.0 for row in stmt.deposits_withdrawals)
    assert any('Synergy Finance' in row.description and row.amount == 100.0 for row in stmt.deposits_withdrawals)
    assert any('Už išperkamus Fondo vienetus' in row.description and row.amount > 0 for row in stmt.deposits_withdrawals)
    assert any('DIVIDENDAI' in row.description for row in stmt.dividends)
    assert not any('III pakopos' in row.description for row in stmt.deposits_withdrawals)


def test_generate_vmi_csv_uses_supplied_country_resolver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rules = load_swedbank_rules(str(ROOT / 'rules.yaml'))
    stmt = parse_swedbank_csv(str(ROOT / 'source' / 'Swedbank_statement.csv'), rules=rules)

    def fake_fetch(self, isin: str):
        mapping = {
            'US00123Q1040': [{'data': [{'country': 'US'}]}],
            'LU0446734369': [{'data': [{'country': 'LU'}]}],
            'US69181V1070': [{'data': [{'country': 'US'}]}],
            'US0423157058': [{'data': [{'country': 'US'}]}],
        }
        return mapping.get(isin, [{'data': []}])

    monkeypatch.setattr(IsinCountryResolver, '_fetch_isin_metadata', fake_fetch)

    output_path = tmp_path / 'vmi.csv'
    rows = generate_vmi_csv(
        stmt,
        str(output_path),
        year=2025,
        country='LT',
        country_resolver=IsinCountryResolver(default_country='LT'),
    )

    assert any(row['rusis'] == 'IV' and row['valstybe'] == 'US' and 'AGNC INVESTMENT CORP' in row['_description'] for row in rows)
    assert any(row['rusis'] == 'IV' and row['valstybe'] == 'LU' and 'UBS MSCI EMU VALUE UCITS ETF' in row['_description'] for row in rows)


