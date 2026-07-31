#!/usr/bin/env python3
"""
Interactive Brokers Activity Statement Parser for VMI (Lithuanian Tax Authority)

Parses IB HTM activity statements and generates:
1. Readable detailed report with all transactions (for verification)
2. CSV file for VMI investment account declaration upload

Usage:
    python3 parse_ib.py source/U15802656_2025_2025.htm [--year 2025]
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


LOGGER = logging.getLogger('parse_ib.openfigi')
if not LOGGER.handlers:
    _openfigi_handler = logging.StreamHandler(sys.stdout)
    _openfigi_handler.setFormatter(logging.Formatter('[OpenFIGI] %(message)s'))
    LOGGER.addHandler(_openfigi_handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    symbol: str
    datetime: str
    quantity: float
    trade_price: float
    close_price: float
    proceeds: float
    commission: float
    basis: float
    realized_pl: float
    mtm_pl: float
    code: str
    currency: str
    asset_class: str  # Stocks, Equity and Index Options, Forex


@dataclass
class Dividend:
    date: str
    description: str
    amount: float
    currency: str


@dataclass
class WithholdingTax:
    date: str
    description: str
    amount: float
    currency: str
    code: str


@dataclass
class Interest:
    date: str
    description: str
    amount: float
    currency: str


@dataclass
class Fee:
    date: str
    description: str
    amount: float
    currency: str


@dataclass
class DepositWithdrawal:
    date: str
    description: str
    amount: float
    currency: str


@dataclass
class OpenPosition:
    symbol: str
    quantity: float
    mult: float
    cost_price: float
    cost_basis: float
    close_price: float
    value: float
    unrealized_pl: float
    currency: str
    asset_class: str


@dataclass
class CorporateAction:
    report_date: str
    datetime: str
    description: str
    quantity: float
    proceeds: float
    value: float
    realized_pl: float
    code: str
    currency: str


@dataclass
class ForexBalance:
    currency: str
    quantity: float
    cost_price: float
    cost_basis_usd: float
    close_price: float
    value_usd: float
    unrealized_pl_usd: float


@dataclass
class ParsedStatement:
    account_id: str = ""
    account_name: str = ""
    base_currency: str = "USD"
    period_start: str = ""
    period_end: str = ""
    nav_total_start: float = 0.0
    nav_total_end: float = 0.0
    trades: list = field(default_factory=list)
    dividends: list = field(default_factory=list)
    withholding_taxes: list = field(default_factory=list)
    interests: list = field(default_factory=list)
    fees: list = field(default_factory=list)
    deposits_withdrawals: list = field(default_factory=list)
    open_positions: list = field(default_factory=list)
    corporate_actions: list = field(default_factory=list)
    forex_balances: list = field(default_factory=list)
    # Currency totals in USD from IB (for cross-checking)
    dividend_total_usd: float = 0.0
    withholding_tax_total_usd: float = 0.0
    interest_total_usd: float = 0.0
    fee_total_usd: float = 0.0
    deposit_total_usd: float = 0.0
    # EUR/USD rate at period end (from forex balances)
    eur_usd_rate: float = 0.0
    # FX rates derived from position Total/Total inUSD pairs
    derived_fx_rates: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_number(s: str) -> float:
    """Parse a number string from IB report (handles commas and empty strings)."""
    if not s or s == '--' or s.strip() == '':
        return 0.0
    s = s.replace(',', '').replace('\xa0', '').strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def extract_account_id(soup: BeautifulSoup) -> str:
    """Extract account ID from any section heading."""
    for div in soup.find_all('div', id=True):
        m = re.search(r'_(U\d+)', div.get('id', ''))
        if m:
            return m.group(1)
    return ""


def extract_period(soup: BeautifulSoup) -> tuple:
    """Extract period start and end from the title."""
    title = soup.find('title')
    if title:
        text = title.get_text()
        # Annual: "January 1, 2025 - December 31, 2025"
        m = re.search(r'(\w+ \d+, \d{4})\s*-\s*(\w+ \d+, \d{4})', text)
        if m:
            start = datetime.strptime(m.group(1), '%B %d, %Y').strftime('%Y-%m-%d')
            end = datetime.strptime(m.group(2), '%B %d, %Y').strftime('%Y-%m-%d')
            return start, end
        # Daily: "December 31, 2024"
        m = re.search(r'(\w+ \d+, \d{4})', text)
        if m:
            d = datetime.strptime(m.group(1), '%B %d, %Y').strftime('%Y-%m-%d')
            return d, d
    return "", ""


def extract_nav(soup: BeautifulSoup, account_id: str) -> tuple:
    """Extract NAV start and end totals."""
    body = soup.find('div', id=f'tblNAV_{account_id}Body')
    if not body:
        return 0.0, 0.0

    table = body.find('table')
    if not table:
        return 0.0, 0.0

    for tr in table.find_all('tr', class_='subtotal'):
        tds = tr.find_all('td')
        if len(tds) >= 5:
            text = tds[0].get_text(strip=True).replace('\xa0', '')
            if 'Total' in text:
                start = parse_number(tds[1].get_text(strip=True))
                end = parse_number(tds[4].get_text(strip=True))
                return start, end
    return 0.0, 0.0


def extract_account_info(soup: BeautifulSoup, account_id: str) -> tuple:
    """Extract account name and base currency."""
    body = soup.find('div', id=f'tblAccountInformation_{account_id}Body')
    name = ""
    base_currency = "USD"
    if body:
        for tr in body.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) >= 2:
                label = tds[0].get_text(strip=True)
                value = tds[1].get_text(strip=True)
                if label == 'Name':
                    name = value
                elif label == 'Base Currency':
                    base_currency = value
    return name, base_currency


def get_table_body(soup: BeautifulSoup, body_id: str):
    """Get the first table within a body div."""
    body = soup.find('div', id=body_id)
    if not body:
        return None
    return body.find('table')


def parse_trades(soup: BeautifulSoup, account_id: str) -> list:
    """Parse all trades from the Transactions section."""
    table = get_table_body(soup, f'tblTransactions_{account_id}Body')
    if not table:
        return []

    trades = []
    current_asset_class = ""
    current_currency = ""

    for tr in table.find_all('tr'):
        ths = tr.find_all('th')
        tds = tr.find_all('td')

        if ths:
            continue

        if not tds:
            continue

        cells = [td.get_text(strip=True).replace('\xa0', '').replace(',', '') for td in tds]

        # Skip empty rows
        if not any(c for c in cells if c):
            continue

        # Single-cell row = asset class or currency header
        non_empty = [c for c in cells if c]
        if len(non_empty) == 1 and len(cells) <= 2:
            text = non_empty[0]
            if text in ('Stocks', 'Equity and Index Options', 'Forex'):
                current_asset_class = text
            elif len(text) <= 4 and text.isalpha() and text.isupper():
                current_currency = text
            continue

        # Skip total/summary rows
        if cells[0].startswith('Total') or cells[0] == '':
            continue

        # Parse actual trade row
        if current_asset_class == 'Forex':
            # Forex has different columns: Symbol, Date/Time, Quantity, T.Price, '', Proceeds, Comm inUSD, '', '', MTM inUSD, Code
            if len(cells) >= 6:
                symbol = cells[0]
                dt = cells[1] if len(cells) > 1 else ''
                quantity = parse_number(cells[2]) if len(cells) > 2 else 0
                trade_price = parse_number(cells[3]) if len(cells) > 3 else 0
                proceeds = parse_number(cells[5]) if len(cells) > 5 else 0
                commission = parse_number(cells[6]) if len(cells) > 6 else 0
                code = cells[-1] if len(cells) > 10 else ''

                trades.append(Trade(
                    symbol=symbol, datetime=dt, quantity=quantity,
                    trade_price=trade_price, close_price=0, proceeds=proceeds,
                    commission=commission, basis=0, realized_pl=0, mtm_pl=0,
                    code=code, currency=current_currency,
                    asset_class=current_asset_class
                ))
        else:
            # Stocks and Options: Symbol, Date/Time, Quantity, T.Price, C.Price, Proceeds, Comm/Fee, Basis, Realized P/L, MTM P/L, Code
            if len(cells) >= 11:
                trades.append(Trade(
                    symbol=cells[0],
                    datetime=cells[1],
                    quantity=parse_number(cells[2]),
                    trade_price=parse_number(cells[3]),
                    close_price=parse_number(cells[4]),
                    proceeds=parse_number(cells[5]),
                    commission=parse_number(cells[6]),
                    basis=parse_number(cells[7]),
                    realized_pl=parse_number(cells[8]),
                    mtm_pl=parse_number(cells[9]),
                    code=cells[10],
                    currency=current_currency,
                    asset_class=current_asset_class
                ))

    return trades


def parse_simple_section(soup, body_id, cls, has_code=False):
    """Parse sections with Date/Description/Amount format (dividends, interest, fees, etc.)."""
    table = get_table_body(soup, body_id)
    if not table:
        return [], 0.0

    items = []
    current_currency = ""
    total_usd = 0.0

    for tr in table.find_all('tr'):
        tds = tr.find_all('td')
        if not tds:
            continue

        cells = [td.get_text(strip=True).replace('\xa0', '').replace(',', '') for td in tds]
        non_empty = [c for c in cells if c]

        if not non_empty:
            continue

        # Currency header (single cell with currency code)
        if len(non_empty) == 1 and len(cells) <= 2:
            text = non_empty[0]
            if len(text) <= 4 and text.isalpha() and text.isupper():
                current_currency = text
                continue
            # Check for "Other Fees" type headers
            if not text[0].isdigit():
                continue

        # Total in USD row
        first = cells[0]
        if 'inUSD' in first or 'in USD' in first:
            total_usd += parse_number(cells[1] if len(cells) > 1 else cells[0].split()[-1])
            continue

        # Skip total rows
        if first.startswith('Total'):
            continue

        # Data row
        if len(cells) >= 3:
            date = cells[0]
            desc = cells[1]
            amount = parse_number(cells[2])

            if has_code:
                code = cells[3] if len(cells) > 3 else ''
                items.append(cls(date=date, description=desc, amount=amount,
                                 currency=current_currency, code=code))
            else:
                items.append(cls(date=date, description=desc, amount=amount,
                                 currency=current_currency))

    return items, total_usd


def parse_deposits_withdrawals(soup, account_id):
    """Parse deposits and withdrawals."""
    return parse_simple_section(soup, f'tblCombDepWith_{account_id}Body', DepositWithdrawal)


def parse_dividends(soup, account_id):
    """Parse dividends."""
    return parse_simple_section(soup, f'tblCombDiv_{account_id}Body', Dividend)


def parse_withholding_tax(soup, account_id):
    """Parse withholding tax."""
    return parse_simple_section(soup, f'tblWithholdingTax_{account_id}Body', WithholdingTax, has_code=True)


def parse_interest(soup, account_id):
    """Parse interest."""
    return parse_simple_section(soup, f'tblCombInt_{account_id}Body', Interest)


def parse_fees(soup, account_id):
    """Parse fees."""
    return parse_simple_section(soup, f'tblCombFees_{account_id}Body', Fee)


def parse_open_positions(soup, account_id):
    """Parse open positions at period end. Also derives FX rates from Total/Total inUSD pairs."""
    table = get_table_body(soup, f'tblOpenPositions_{account_id}Body')
    if not table:
        return [], {}

    positions = []
    derived_rates = {}  # currency -> USD rate derived from position totals
    current_asset_class = ""
    current_currency = ""
    last_currency_total_value = None  # value from the "Total" row in native currency

    for tr in table.find_all('tr'):
        tds = tr.find_all('td')
        if not tds:
            continue

        cells = [td.get_text(strip=True).replace('\xa0', '').replace(',', '') for td in tds]
        non_empty = [c for c in cells if c]

        if not non_empty:
            continue

        if len(non_empty) == 1:
            text = non_empty[0]
            if text in ('Stocks', 'Equity and Index Options'):
                current_asset_class = text
            elif len(text) <= 4 and text.isalpha() and text.isupper():
                current_currency = text
                last_currency_total_value = None
            continue

        first = cells[0]

        # Capture "Total" row (native currency total for this currency group)
        if first == 'Total' and len(cells) >= 7:
            last_currency_total_value = parse_number(cells[5])  # Value column
            continue

        # Capture "Total inUSD" row to derive FX rate
        if ('inUSD' in first or 'in USD' in first) and len(cells) >= 7:
            usd_value = parse_number(cells[5])  # Value in USD
            if last_currency_total_value and last_currency_total_value != 0 and usd_value != 0:
                rate = usd_value / last_currency_total_value
                if current_currency and current_currency != 'USD':
                    derived_rates[current_currency] = rate
            last_currency_total_value = None
            continue

        if first.startswith('Total'):
            continue

        # Position row: Symbol, Quantity, Mult, Cost Price, Cost Basis, Close Price, Value, Unrealized P/L, Code
        if len(cells) >= 9:
            positions.append(OpenPosition(
                symbol=cells[0],
                quantity=parse_number(cells[1]),
                mult=parse_number(cells[2]),
                cost_price=parse_number(cells[3]),
                cost_basis=parse_number(cells[4]),
                close_price=parse_number(cells[5]),
                value=parse_number(cells[6]),
                unrealized_pl=parse_number(cells[7]),
                currency=current_currency,
                asset_class=current_asset_class
            ))

    return positions, derived_rates


def parse_forex_balances(soup, account_id):
    """Parse forex balances at period end."""
    table = get_table_body(soup, f'tblFxPositions_{account_id}Body')
    if not table:
        return []

    balances = []
    for tr in table.find_all('tr'):
        tds = tr.find_all('td')
        if not tds:
            continue

        cells = [td.get_text(strip=True).replace('\xa0', '').replace(',', '') for td in tds]
        non_empty = [c for c in cells if c]

        if not non_empty or len(non_empty) == 1:
            continue
        if cells[0].startswith('Total'):
            continue

        # Row: Currency, Quantity, Cost Price, Cost Basis inUSD, Close Price, Value inUSD, Unrealized P/L inUSD, Code
        if len(cells) >= 7:
            balances.append(ForexBalance(
                currency=cells[0],
                quantity=parse_number(cells[1]),
                cost_price=parse_number(cells[2]),
                cost_basis_usd=parse_number(cells[3]),
                close_price=parse_number(cells[4]),
                value_usd=parse_number(cells[5]),
                unrealized_pl_usd=parse_number(cells[6])
            ))

    return balances


def parse_corporate_actions(soup, account_id):
    """Parse corporate actions."""
    table = get_table_body(soup, f'tblCorporateActions_{account_id}Body')
    if not table:
        return []

    actions = []
    current_currency = ""

    for tr in table.find_all('tr'):
        tds = tr.find_all('td')
        if not tds:
            continue

        cells = [td.get_text(strip=True).replace('\xa0', '').replace(',', '') for td in tds]
        non_empty = [c for c in cells if c]

        if not non_empty:
            continue

        if len(non_empty) == 1:
            text = non_empty[0]
            if text in ('Stocks', 'Equity and Index Options'):
                continue
            elif len(text) <= 4 and text.isalpha() and text.isupper():
                current_currency = text
            continue

        if cells[0].startswith('Total'):
            continue

        if len(cells) >= 8:
            actions.append(CorporateAction(
                report_date=cells[0],
                datetime=cells[1],
                description=cells[2],
                quantity=parse_number(cells[3]),
                proceeds=parse_number(cells[4]),
                value=parse_number(cells[5]),
                realized_pl=parse_number(cells[6]),
                code=cells[7],
                currency=current_currency
            ))

    return actions


def parse_statement(html_path: str) -> ParsedStatement:
    """Parse an IB activity statement HTML file."""
    if BeautifulSoup is None:
        raise RuntimeError("BeautifulSoup4 is required for IB HTML parsing. Install with: pip install beautifulsoup4")

    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    stmt = ParsedStatement()
    stmt.account_id = extract_account_id(soup)
    stmt.period_start, stmt.period_end = extract_period(soup)
    stmt.account_name, stmt.base_currency = extract_account_info(soup, stmt.account_id)
    stmt.nav_total_start, stmt.nav_total_end = extract_nav(soup, stmt.account_id)

    stmt.trades = parse_trades(soup, stmt.account_id)

    stmt.dividends, stmt.dividend_total_usd = parse_dividends(soup, stmt.account_id)
    stmt.withholding_taxes, stmt.withholding_tax_total_usd = parse_withholding_tax(soup, stmt.account_id)
    stmt.interests, stmt.interest_total_usd = parse_interest(soup, stmt.account_id)
    stmt.fees, stmt.fee_total_usd = parse_fees(soup, stmt.account_id)
    stmt.deposits_withdrawals, stmt.deposit_total_usd = parse_deposits_withdrawals(soup, stmt.account_id)

    stmt.open_positions, derived_rates = parse_open_positions(soup, stmt.account_id)
    stmt.forex_balances = parse_forex_balances(soup, stmt.account_id)
    stmt.corporate_actions = parse_corporate_actions(soup, stmt.account_id)

    # Extract EUR/USD rate from forex balances
    for fb in stmt.forex_balances:
        if fb.currency == 'EUR':
            stmt.eur_usd_rate = fb.close_price
            break

    # Store derived rates from position totals (for currencies not in forex balances)
    stmt.derived_fx_rates = derived_rates

    return stmt


def default_swedbank_rules() -> dict:
    """Default Swedbank mapping rules for II/PP/IV classification."""
    return {
        'country': 'LT',
        'exclude_codes': ['AS', 'LS', 'K2', 'M', 'TT', 'X'],
        'exclude_description_contains': [],
        'dividend_description_contains': ['DIVIDENDAI'],
        'force_deposit_description_contains': [],
        'force_withdrawal_description_contains': [],
        'action_rules': [],
    }


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _contains_any(text: str, needles: list) -> bool:
    text_cf = (text or '').casefold()
    for needle in needles:
        if str(needle).casefold() in text_cf:
            return True
    return False


ISIN_RE = re.compile(r'\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b')
DEFAULT_OPENFIGI_URL = 'https://api.openfigi.com/v3/mapping'
COUNTRY_RESPONSE_KEYS = (
    'country',
    'countryCode',
    'country_code',
    'countryIso2',
    'country_iso2',
    'iso2',
    'domicile',
    'domicileCountry',
    'domicile_country',
)


def extract_isin(text: str) -> Optional[str]:
    """Extract the first ISIN found in free text."""
    if not text:
        return None
    m = ISIN_RE.search(text.upper())
    return m.group(1) if m else None


def _normalize_country_code(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    candidate = value.strip().upper()
    if re.fullmatch(r'[A-Z]{2}', candidate):
        return candidate
    return None


def _extract_country_from_api_payload(payload) -> Optional[str]:
    """Search a nested API payload for an ISO-3166 alpha-2 country code."""
    if isinstance(payload, dict):
        for key in COUNTRY_RESPONSE_KEYS:
            country = _normalize_country_code(payload.get(key))
            if country:
                return country
        for value in payload.values():
            country = _extract_country_from_api_payload(value)
            if country:
                return country
        return None

    if isinstance(payload, list):
        for item in payload:
            country = _extract_country_from_api_payload(item)
            if country:
                return country

    return None


class IsinCountryResolver:
    """Resolve row country from ISIN metadata with API lookup and safe fallbacks."""

    def __init__(self,
                 default_country: str,
                 api_url: Optional[str] = None,
                 api_key: Optional[str] = None,
                 timeout: float = 10.0,
                 api_enabled: bool = True):
        self.default_country = (default_country or 'LT').upper()
        self.api_url = api_url or os.getenv('OPENFIGI_API_URL', DEFAULT_OPENFIGI_URL)
        self.api_key = api_key or os.getenv('OPENFIGI_API_KEY')
        self.timeout = timeout
        self.api_enabled = api_enabled
        self.cache = {}

    def resolve_description(self, description: str) -> str:
        isin = extract_isin(description)
        return self.resolve_isin(isin)

    def resolve_isin(self, isin: Optional[str]) -> str:
        if not isin:
            return self.default_country

        isin = isin.upper()
        if isin in self.cache:
            LOGGER.info('OpenFIGI cache hit for ISIN %s -> %s', isin, self.cache[isin])
            return self.cache[isin]

        LOGGER.info('OpenFIGI cache miss for ISIN %s', isin)
        country = None
        if self.api_enabled:
            try:
                LOGGER.info('Accessing OpenFIGI for ISIN %s', isin)
                payload = self._fetch_isin_metadata(isin)
                country = _extract_country_from_api_payload(payload)
                if country:
                    LOGGER.info('OpenFIGI resolved ISIN %s -> %s', isin, country)
                else:
                    LOGGER.info('OpenFIGI returned no country for ISIN %s', isin)
            except RuntimeError as exc:
                LOGGER.warning('OpenFIGI lookup failed for ISIN %s: %s', isin, exc)

        if not country:
            # Fallback to issuer country embedded in the ISIN when the API does not
            # expose an explicit country field or is temporarily unavailable.
            country = isin[:2] if ISIN_RE.fullmatch(isin) else self.default_country
            LOGGER.info('Using fallback country for ISIN %s -> %s', isin, country)

        self.cache[isin] = country
        return country

    def _fetch_isin_metadata(self, isin: str):
        payload = json.dumps([{'idType': 'ID_ISIN', 'idValue': isin}]).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['X-OPENFIGI-APIKEY'] = self.api_key

        request = urllib_request.Request(self.api_url, data=payload, headers=headers, method='POST')
        try:
            with urllib_request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib_error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace') if hasattr(exc, 'read') else ''
            raise RuntimeError(f'HTTP {exc.code}: {body[:200]}') from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(str(exc.reason)) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError('invalid JSON response from ISIN lookup API') from exc


def _load_patterns(patterns_path: Optional[str] = None) -> dict:
    """Load pattern collections from patterns.json.
    
    Returns a dict mapping pattern_name -> list of pattern strings.
    If patterns_path is None, tries to load from 'patterns.json' in current dir.
    """
    if patterns_path is None:
        patterns_path = 'patterns.json'
    
    if not os.path.isfile(patterns_path):
        return {}
    
    try:
        with open(patterns_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        resolved = {}
        if isinstance(data.get('patterns'), dict):
            for name, config in data['patterns'].items():
                if isinstance(config, dict) and 'patterns' in config:
                    resolved[name] = _as_list(config['patterns'])
        return resolved
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load patterns from {patterns_path}: {e}", file=sys.stderr)
        return {}


def _resolve_pattern_references(value_list: list, patterns: dict) -> list:
    """Resolve @pattern_name references to actual patterns.
    
    Converts:
        ['@fund_purchases', 'inline_pattern']
    To:
        ['pattern1_from_fund_purchases', 'pattern2_from_fund_purchases', 'inline_pattern']
    """
    resolved = []
    for item in _as_list(value_list):
        item_str = str(item)
        if item_str.startswith('@'):
            pattern_name = item_str[1:]  # Remove @ prefix
            if pattern_name in patterns:
                resolved.extend(patterns[pattern_name])
            else:
                raise RuntimeError(f"Unknown pattern reference: @{pattern_name}")
        else:
            resolved.append(item_str)
    return resolved


def load_swedbank_rules(path: Optional[str]) -> dict:
    """Load optional Swedbank mapping rules from YAML file.
    
    Supports pattern collection references using @pattern_name syntax.
    Patterns are loaded from patterns.json in the same directory as rules file.
    """
    rules = default_swedbank_rules()
    if not path:
        return rules

    try:
        import yaml
    except ImportError as e:
        raise RuntimeError(
            "PyYAML is required for --swedbank-rules. Install with: pip install pyyaml"
        ) from e

    with open(path, 'r', encoding='utf-8') as f:
        loaded = yaml.safe_load(f) or {}

    if not isinstance(loaded, dict):
        raise RuntimeError(f"Invalid rules file (expected mapping): {path}")

    # Load pattern collections from patterns.json (same directory as rules file)
    rules_dir = os.path.dirname(os.path.abspath(path))
    patterns_file = os.path.join(rules_dir, 'patterns.json')
    patterns = _load_patterns(patterns_file)

    if 'country' in loaded:
        rules['country'] = str(loaded['country']).upper()

    for key in (
        'exclude_codes',
        'exclude_description_contains',
        'dividend_description_contains',
        'force_deposit_description_contains',
        'force_withdrawal_description_contains',
    ):
        if key in loaded:
            raw_list = _as_list(loaded[key])
            resolved_list = _resolve_pattern_references(raw_list, patterns)
            rules[key] = [str(x) for x in resolved_list]

    if 'action_rules' in loaded:
        action_rules = _as_list(loaded['action_rules'])
        normalized = []
        for idx, raw in enumerate(action_rules):
            if not isinstance(raw, dict):
                raise RuntimeError(f"Invalid action_rules[{idx}] in {path}: expected mapping")
            action = str(raw.get('action', 'AUTO')).upper()
            if action not in {'II', 'PP', 'IV', 'IGNORE', 'AUTO'}:
                raise RuntimeError(f"Invalid action '{action}' in action_rules[{idx}] ({path})")
            when = raw.get('when', {})
            if when is None:
                when = {}
            if not isinstance(when, dict):
                raise RuntimeError(f"Invalid when in action_rules[{idx}] ({path}): expected mapping")
            
            # Resolve pattern references in when conditions
            resolved_when = {}
            for condition_key, condition_value in when.items():
                if condition_key in ('description_contains', 'receiver_contains'):
                    resolved_when[condition_key] = _resolve_pattern_references(
                        _as_list(condition_value), patterns
                    )
                else:
                    resolved_when[condition_key] = condition_value
            
            normalized.append({'action': action, 'when': resolved_when})
        rules['action_rules'] = normalized

    return rules


def _swedbank_rule_matches(code: str, dk: str, currency: str, desc: str, receiver: str, when: dict) -> bool:
    """Return True when a row matches an action-rule condition."""
    if 'code' in when and str(when['code']).upper() != code:
        return False
    if 'codes' in when:
        codes = {str(x).upper() for x in _as_list(when['codes'])}
        if code not in codes:
            return False
    if 'dk' in when and str(when['dk']).upper() != dk:
        return False
    if 'currency' in when and str(when['currency']).upper() != currency:
        return False
    if 'description_contains' in when and not _contains_any(desc, _as_list(when['description_contains'])):
        return False
    if 'receiver_contains' in when and not _contains_any(receiver, _as_list(when['receiver_contains'])):
        return False
    return True


def classify_swedbank_row(code: str, dk: str, currency: str, desc: str,
                          receiver: str, signed_amount: float, rules: dict) -> Optional[str]:
    """Classify a Swedbank row into IV/II/PP/IGNORE using configurable rules."""
    code = (code or '').upper()
    dk = (dk or '').upper()
    currency = (currency or '').upper()

    # Highest priority: explicit ordered action rules.
    for rule in rules.get('action_rules', []):
        when = rule.get('when', {})
        if _swedbank_rule_matches(code, dk, currency, desc, receiver, when):
            action = rule.get('action', 'AUTO').upper()
            if action == 'AUTO':
                break
            if action == 'IGNORE':
                return None
            return action

    # Built-in/default fallback mapping.
    if not code:
        return None
    if code in {c.upper() for c in rules.get('exclude_codes', [])}:
        return None
    if _contains_any(desc, rules.get('exclude_description_contains', [])):
        return None
    if _contains_any(desc, rules.get('dividend_description_contains', [])) and signed_amount > 0:
        return 'IV'
    if _contains_any(desc, rules.get('force_deposit_description_contains', [])):
        return 'II'
    if _contains_any(desc, rules.get('force_withdrawal_description_contains', [])):
        return 'PP'
    return 'II' if signed_amount >= 0 else 'PP'


def parse_swedbank_csv(csv_path: str, rules: Optional[dict] = None) -> ParsedStatement:
    """Parse Swedbank CSV export into normalized ParsedStatement structure."""
    rules = rules or default_swedbank_rules()
    stmt = ParsedStatement()
    opening_balances = {}
    all_dates = []
    eur_usd_rate = 0.0

    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            account_id = (row.get('Sąskaitos Nr.') or '').strip()
            date = (row.get('Data') or '').strip()
            receiver = (row.get('Gavėjas') or '').strip()
            desc = (row.get('Paaiškinimai') or '').strip()
            amount = parse_number((row.get('Suma') or '').strip())
            currency = (row.get('Valiuta') or '').strip().upper()
            dk = (row.get('D/K') or '').strip().upper()
            code = (row.get('Kodas') or '').strip().upper()

            if account_id and not stmt.account_id:
                stmt.account_id = account_id
            if date:
                all_dates.append(date)

            # Track opening balances for IA fallback.
            if code == 'AS' and currency:
                opening_balances[currency] = opening_balances.get(currency, 0.0) + amount

            # Parse FX rates from conversion descriptions such as "kursas 1.1994".
            if code == 'X' and desc:
                m = re.search(r'kursas\s+([0-9]+(?:[\.,][0-9]+)?)', desc, flags=re.IGNORECASE)
                if m:
                    eur_usd_rate = parse_number(m.group(1).replace(',', '.'))

            signed_amount = amount if dk == 'K' else -amount

            action = classify_swedbank_row(code, dk, currency, desc, receiver, signed_amount, rules)
            if action is None:
                continue
            if action == 'IV':
                stmt.dividends.append(Dividend(
                    date=date,
                    description=desc,
                    amount=abs(signed_amount),
                    currency=currency or 'EUR'
                ))
                continue

            if action == 'II':
                normalized_amount = abs(signed_amount)
            elif action == 'PP':
                normalized_amount = -abs(signed_amount)
            else:
                normalized_amount = signed_amount

            stmt.deposits_withdrawals.append(DepositWithdrawal(
                date=date,
                description=desc,
                amount=normalized_amount,
                currency=currency or 'EUR'
            ))

    if all_dates:
        stmt.period_start = min(all_dates)
        stmt.period_end = max(all_dates)

    stmt.base_currency = 'EUR' if 'EUR' in opening_balances else (next(iter(opening_balances.keys()), 'EUR'))
    stmt.eur_usd_rate = eur_usd_rate if eur_usd_rate > 0 else 1.0

    # Keep a minimal cash snapshot from opening balances so IA can be generated if requested.
    for cur, qty in opening_balances.items():
        if cur == 'USD':
            value_usd = qty
            close_price = 1.0
        elif cur == 'EUR':
            value_usd = qty * stmt.eur_usd_rate
            close_price = stmt.eur_usd_rate
        else:
            value_usd = qty
            close_price = 0.0
        stmt.forex_balances.append(ForexBalance(
            currency=cur,
            quantity=qty,
            cost_price=0.0,
            cost_basis_usd=value_usd,
            close_price=close_price,
            value_usd=value_usd,
            unrealized_pl_usd=0.0
        ))

    return stmt


def detect_broker(input_path: str) -> str:
    """Best-effort broker detection from file extension/header."""
    lower = input_path.lower()
    if lower.endswith(('.htm', '.html')):
        return 'ib'
    if lower.endswith('.csv'):
        try:
            with open(input_path, 'r', encoding='utf-8-sig') as f:
                header = f.readline()
            if 'Sąskaitos Nr.' in header:
                return 'swedbank'
        except OSError:
            pass
    return 'ib'


def resolve_country_from_instrument_id(description: str, default_country: str) -> str:
    """Resolve country code from free text using ISIN metadata lookup when available."""
    resolver = IsinCountryResolver(default_country=default_country)
    return resolver.resolve_description(description)


# ---------------------------------------------------------------------------
# Currency conversion helpers
# ---------------------------------------------------------------------------

def get_currency_to_usd_rates(stmt: ParsedStatement) -> dict:
    """Build a map of currency -> USD rate from forex balances and derived position rates."""
    rates = {'USD': 1.0}
    # First, add rates derived from position Total/Total inUSD pairs
    for cur, rate in stmt.derived_fx_rates.items():
        rates[cur] = rate
    # Then overlay with forex balance rates (more authoritative for currencies with cash)
    for fb in stmt.forex_balances:
        if fb.close_price > 0:
            rates[fb.currency] = fb.close_price
    return rates


def usd_to_eur(amount_usd: float, eur_usd_rate: float) -> float:
    """Convert USD to EUR using EUR/USD rate."""
    if eur_usd_rate <= 0:
        return amount_usd  # fallback
    return amount_usd / eur_usd_rate


def native_to_usd(amount: float, currency: str, rates: dict) -> float:
    """Convert native currency amount to USD."""
    rate = rates.get(currency, 1.0)
    return amount * rate


def native_to_eur(amount: float, currency: str, rates: dict, eur_usd_rate: float) -> float:
    """Convert native currency amount to EUR."""
    usd = native_to_usd(amount, currency, rates)
    return usd_to_eur(usd, eur_usd_rate)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_readable_report(stmt: ParsedStatement, output_path: str):
    """Generate a detailed readable report for verification."""
    rates = get_currency_to_usd_rates(stmt)
    eur_rate = stmt.eur_usd_rate

    lines = []
    w = lines.append

    def sep(char='='):
        w(char * 100)

    def money(val, decimals=2):
        return f"{val:,.{decimals}f}"

    sep()
    w(f"  VMI INVESTMENT ACCOUNT REPORT")
    w(f"  Account: {stmt.account_id} ({stmt.account_name})")
    w(f"  Period:  {stmt.period_start} to {stmt.period_end}")
    w(f"  Base Currency: {stmt.base_currency}")
    w(f"  EUR/USD Rate (period end): {eur_rate}")
    sep()

    # --- NAV Summary ---
    w("")
    w("1. NET ASSET VALUE (NAV) SUMMARY")
    sep('-')
    nav_start_eur = usd_to_eur(stmt.nav_total_start, eur_rate)
    nav_end_eur = usd_to_eur(stmt.nav_total_end, eur_rate)
    nav_change = stmt.nav_total_end - stmt.nav_total_start
    nav_change_eur = usd_to_eur(nav_change, eur_rate)

    w(f"  {'':40s} {'USD':>15s} {'EUR':>15s}")
    w(f"  {'NAV at start':40s} {money(stmt.nav_total_start):>15s} {money(nav_start_eur):>15s}")
    w(f"  {'NAV at end':40s} {money(stmt.nav_total_end):>15s} {money(nav_end_eur):>15s}")
    w(f"  {'Change':40s} {money(nav_change):>15s} {money(nav_change_eur):>15s}")

    # --- Deposits & Withdrawals ---
    w("")
    w("2. DEPOSITS & WITHDRAWALS")
    sep('-')
    total_dep_eur = 0.0
    total_wd_eur = 0.0
    if stmt.deposits_withdrawals:
        w(f"  {'Date':12s} {'Currency':5s} {'Amount':>15s} {'EUR':>15s} Description")
        w(f"  {'-'*12} {'-'*5} {'-'*15} {'-'*15} {'-'*30}")
        for dw in stmt.deposits_withdrawals:
            eur = native_to_eur(dw.amount, dw.currency, rates, eur_rate)
            w(f"  {dw.date:12s} {dw.currency:5s} {money(dw.amount):>15s} {money(eur):>15s} {dw.description}")
            if dw.amount >= 0:
                total_dep_eur += eur
            else:
                total_wd_eur += eur
        w(f"  {'':18s} {'TOTAL DEPOSITS':>15s} {money(total_dep_eur):>15s} EUR")
        w(f"  {'':18s} {'TOTAL WITHDRAWALS':>15s} {money(total_wd_eur):>15s} EUR")
        w(f"  {'':18s} {'NET':>15s} {money(total_dep_eur + total_wd_eur):>15s} EUR")
    else:
        w("  No deposits or withdrawals.")

    # --- Trades ---
    w("")
    w("3. TRADES")
    sep('-')

    # Group by asset class
    for asset_class in ['Stocks', 'Equity and Index Options', 'Forex']:
        class_trades = [t for t in stmt.trades if t.asset_class == asset_class]
        if not class_trades:
            continue

        w(f"\n  --- {asset_class} ---")

        # Group by currency
        currencies = sorted(set(t.currency for t in class_trades))
        total_realized_eur = 0.0
        total_commission_eur = 0.0

        for cur in currencies:
            cur_trades = [t for t in class_trades if t.currency == cur]
            w(f"\n  [{cur}]")

            if asset_class == 'Forex':
                w(f"  {'Symbol':15s} {'Date/Time':20s} {'Qty':>10s} {'Price':>12s} {'Proceeds':>15s} {'Comm':>10s}")
                w(f"  {'-'*15} {'-'*20} {'-'*10} {'-'*12} {'-'*15} {'-'*10}")
                for t in cur_trades:
                    w(f"  {t.symbol:15s} {t.datetime:20s} {money(t.quantity):>10s} "
                      f"{money(t.trade_price, 4):>12s} {money(t.proceeds):>15s} {money(t.commission):>10s}")
            else:
                w(f"  {'Symbol':20s} {'Date/Time':20s} {'Qty':>8s} {'Price':>10s} {'Proceeds':>12s} "
                  f"{'Comm':>8s} {'Realized P/L':>12s} {'P/L EUR':>12s} {'Code':8s}")
                w(f"  {'-'*20} {'-'*20} {'-'*8} {'-'*10} {'-'*12} {'-'*8} {'-'*12} {'-'*12} {'-'*8}")
                for t in cur_trades:
                    pl_eur = native_to_eur(t.realized_pl, cur, rates, eur_rate)
                    comm_eur = native_to_eur(t.commission, cur, rates, eur_rate)
                    total_realized_eur += pl_eur
                    total_commission_eur += comm_eur
                    w(f"  {t.symbol:20s} {t.datetime:20s} {money(t.quantity):>8s} "
                      f"{money(t.trade_price, 4):>10s} {money(t.proceeds):>12s} "
                      f"{money(t.commission):>8s} {money(t.realized_pl):>12s} "
                      f"{money(pl_eur):>12s} {t.code:8s}")

        if asset_class != 'Forex':
            w(f"\n  {asset_class} TOTALS:")
            w(f"    Total Realized P/L (EUR): {money(total_realized_eur)}")
            w(f"    Total Commissions (EUR):  {money(total_commission_eur)}")

    # --- Dividends ---
    w("")
    w("4. DIVIDENDS")
    sep('-')
    total_div_eur = 0.0
    if stmt.dividends:
        w(f"  {'Date':12s} {'Cur':4s} {'Amount':>12s} {'EUR':>12s} Description")
        w(f"  {'-'*12} {'-'*4} {'-'*12} {'-'*12} {'-'*50}")
        for d in stmt.dividends:
            eur = native_to_eur(d.amount, d.currency, rates, eur_rate)
            total_div_eur += eur
            w(f"  {d.date:12s} {d.currency:4s} {money(d.amount):>12s} {money(eur):>12s} {d.description}")
        w(f"\n  TOTAL DIVIDENDS: {money(total_div_eur)} EUR (IB total USD: {money(stmt.dividend_total_usd)})")

    # --- Withholding Tax ---
    w("")
    w("5. WITHHOLDING TAX")
    sep('-')
    total_wht_eur = 0.0
    if stmt.withholding_taxes:
        w(f"  {'Date':12s} {'Cur':4s} {'Amount':>12s} {'EUR':>12s} Description")
        w(f"  {'-'*12} {'-'*4} {'-'*12} {'-'*12} {'-'*50}")
        for wt in stmt.withholding_taxes:
            eur = native_to_eur(wt.amount, wt.currency, rates, eur_rate)
            total_wht_eur += eur
            w(f"  {wt.date:12s} {wt.currency:4s} {money(wt.amount):>12s} {money(eur):>12s} {wt.description}")
        w(f"\n  TOTAL WITHHOLDING TAX: {money(total_wht_eur)} EUR (IB total USD: {money(stmt.withholding_tax_total_usd)})")

    # --- Interest ---
    w("")
    w("6. INTEREST")
    sep('-')
    total_int_credit_eur = 0.0
    total_int_debit_eur = 0.0
    if stmt.interests:
        w(f"  {'Date':12s} {'Cur':4s} {'Amount':>12s} {'EUR':>12s} Description")
        w(f"  {'-'*12} {'-'*4} {'-'*12} {'-'*12} {'-'*50}")
        for i in stmt.interests:
            eur = native_to_eur(i.amount, i.currency, rates, eur_rate)
            if i.amount >= 0:
                total_int_credit_eur += eur
            else:
                total_int_debit_eur += eur
            w(f"  {i.date:12s} {i.currency:4s} {money(i.amount):>12s} {money(eur):>12s} {i.description}")
        w(f"\n  TOTAL CREDIT INTEREST: {money(total_int_credit_eur)} EUR")
        w(f"  TOTAL DEBIT INTEREST:  {money(total_int_debit_eur)} EUR")
        w(f"  NET INTEREST:          {money(total_int_credit_eur + total_int_debit_eur)} EUR")
        w(f"  (IB total USD: {money(stmt.interest_total_usd)})")

    # --- Fees ---
    w("")
    w("7. FEES")
    sep('-')
    total_fees_eur = 0.0
    if stmt.fees:
        w(f"  {'Date':12s} {'Cur':4s} {'Amount':>12s} {'EUR':>12s} Description")
        w(f"  {'-'*12} {'-'*4} {'-'*12} {'-'*12} {'-'*50}")
        for f_ in stmt.fees:
            eur = native_to_eur(f_.amount, f_.currency, rates, eur_rate)
            total_fees_eur += eur
            w(f"  {f_.date:12s} {f_.currency:4s} {money(f_.amount):>12s} {money(eur):>12s} {f_.description}")
        w(f"\n  TOTAL FEES: {money(total_fees_eur)} EUR (IB total USD: {money(stmt.fee_total_usd)})")

    # --- Corporate Actions ---
    if stmt.corporate_actions:
        w("")
        w("8. CORPORATE ACTIONS")
        sep('-')
        for ca in stmt.corporate_actions:
            w(f"  {ca.report_date} | {ca.description} | Qty: {ca.quantity} | P/L: {ca.realized_pl}")

    # --- Open Positions ---
    w("")
    w("9. OPEN POSITIONS AT PERIOD END")
    sep('-')
    total_value_eur = 0.0
    total_unrealized_eur = 0.0

    for asset_class in ['Stocks', 'Equity and Index Options']:
        class_pos = [p for p in stmt.open_positions if p.asset_class == asset_class]
        if not class_pos:
            continue

        w(f"\n  --- {asset_class} ---")
        currencies = sorted(set(p.currency for p in class_pos))

        for cur in currencies:
            cur_pos = [p for p in class_pos if p.currency == cur]
            w(f"\n  [{cur}]")
            w(f"  {'Symbol':20s} {'Qty':>8s} {'Cost':>10s} {'Value':>12s} {'Unreal P/L':>12s} {'EUR Value':>12s}")
            w(f"  {'-'*20} {'-'*8} {'-'*10} {'-'*12} {'-'*12} {'-'*12}")

            for p in cur_pos:
                val_eur = native_to_eur(p.value, cur, rates, eur_rate)
                upl_eur = native_to_eur(p.unrealized_pl, cur, rates, eur_rate)
                total_value_eur += val_eur
                total_unrealized_eur += upl_eur
                w(f"  {p.symbol:20s} {money(p.quantity):>8s} {money(p.cost_price, 4):>10s} "
                  f"{money(p.value):>12s} {money(p.unrealized_pl):>12s} {money(val_eur):>12s}")

    w(f"\n  TOTAL POSITIONS VALUE: {money(total_value_eur)} EUR")
    w(f"  TOTAL UNREALIZED P/L: {money(total_unrealized_eur)} EUR")

    # --- Forex Balances ---
    w("")
    w("10. FOREX (CASH) BALANCES AT PERIOD END")
    sep('-')
    total_cash_eur = 0.0
    if stmt.forex_balances:
        w(f"  {'Currency':8s} {'Quantity':>15s} {'USD Value':>15s} {'EUR Value':>15s}")
        w(f"  {'-'*8} {'-'*15} {'-'*15} {'-'*15}")
        for fb in stmt.forex_balances:
            eur_val = usd_to_eur(fb.value_usd, eur_rate)
            total_cash_eur += eur_val
            w(f"  {fb.currency:8s} {money(fb.quantity):>15s} {money(fb.value_usd):>15s} {money(eur_val):>15s}")
        w(f"\n  TOTAL CASH: {money(total_cash_eur)} EUR")

    # --- Grand Summary ---
    w("")
    sep('=')
    w("  GRAND SUMMARY FOR VMI")
    sep('=')
    total_account_value_eur = total_value_eur + total_cash_eur
    nav_eur = usd_to_eur(stmt.nav_total_end, eur_rate)
    w(f"  {'':45s} {'EUR':>15s}")
    w(f"  {'NAV total (IB authoritative)':45s} {money(nav_eur):>15s}")
    w(f"")
    w(f"  Cross-check (positions + cash):")
    w(f"  {'  Positions value':45s} {money(total_value_eur):>15s}")
    w(f"  {'  Cash balances':45s} {money(total_cash_eur):>15s}")
    w(f"  {'  Sum':45s} {money(total_account_value_eur):>15s}")
    diff = abs(nav_eur - total_account_value_eur)
    w(f"  {'  Difference (accruals, lending adj.)':45s} {money(nav_eur - total_account_value_eur):>15s}")
    w(f"")
    w(f"  >>> VMI CSV uses NAV total: {money(nav_eur)} EUR <<<")
    w(f"")
    w(f"  {'Total deposits':45s} {money(total_dep_eur):>15s}")
    w(f"  {'Total withdrawals':45s} {money(total_wd_eur):>15s}")
    w(f"  {'Net deposits':45s} {money(total_dep_eur + total_wd_eur):>15s}")
    w(f"")

    # Income summary
    stock_trades = [t for t in stmt.trades if t.asset_class == 'Stocks']
    option_trades = [t for t in stmt.trades if t.asset_class == 'Equity and Index Options']

    stock_pl = sum(native_to_eur(t.realized_pl, t.currency, rates, eur_rate) for t in stock_trades)
    option_pl = sum(native_to_eur(t.realized_pl, t.currency, rates, eur_rate) for t in option_trades)
    total_comm = sum(native_to_eur(t.commission, t.currency, rates, eur_rate)
                     for t in stmt.trades if t.asset_class != 'Forex')

    w(f"  {'Realized P/L from stocks':45s} {money(stock_pl):>15s}")
    w(f"  {'Realized P/L from options':45s} {money(option_pl):>15s}")
    w(f"  {'Total trading commissions':45s} {money(total_comm):>15s}")
    w(f"  {'Dividends (gross)':45s} {money(total_div_eur):>15s}")
    w(f"  {'Withholding tax':45s} {money(total_wht_eur):>15s}")
    w(f"  {'Dividends (net)':45s} {money(total_div_eur + total_wht_eur):>15s}")
    w(f"  {'Net interest':45s} {money(total_int_credit_eur + total_int_debit_eur):>15s}")
    w(f"  {'Fees':45s} {money(total_fees_eur):>15s}")
    w(f"")
    w(f"  EUR/USD rate used: {eur_rate} (IB period-end rate)")
    w(f"  Note: For official VMI submission, verify with Lietuvos Bankas rates")
    w(f"        if required by tax regulations.")
    sep('=')

    report = '\n'.join(lines)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)

    return report


def generate_vmi_csv(stmt: ParsedStatement, output_path: str, year: int,
                     declaration_start_date: Optional[str] = None,
                     balance_stmt: Optional[ParsedStatement] = None,
                     country: str = 'IE',
                     country_resolver: Optional[IsinCountryResolver] = None):
    """Generate VMI CSV for investment account declaration.

    VMI codes (rusis):
        II = funds deposited into investment account (inasas)
        IV = funds deposited via dividends received (inasas dividendais)
        PP = funds withdrawn from investment account (ismoka)
        IA = initial balance on declaration start date (pradinis likutis)
        IS = pre-2024 financial products assigned to account
        IP = inherited financial products
        ID = gifted financial products

    Each deposit/withdrawal/dividend is a separate row. Amounts in EUR.
    IA uses COST BASIS (not market value).
    Country = IE (Interactive Brokers Ireland).
    """
    eur_rate = stmt.eur_usd_rate
    if eur_rate <= 0:
        print("WARNING: EUR/USD rate not found, using 1.0")
        eur_rate = 1.0

    rates = get_currency_to_usd_rates(stmt)
    rows = []
    country_resolver = country_resolver or IsinCountryResolver(default_country=country)

    # If declaration_start_date provided, add IA (cash) and IS (positions cost basis)
    # as ONE consolidated row each (pre-2025 balances are not itemized)
    if declaration_start_date:
        bal = balance_stmt if balance_stmt else stmt
        bal_rates = get_currency_to_usd_rates(bal)
        bal_eur_rate = bal.eur_usd_rate if bal.eur_usd_rate > 0 else eur_rate

        # IA = consolidated cash balance
        cash_eur = sum(
            usd_to_eur(fb.value_usd, bal_eur_rate)
            for fb in bal.forex_balances
        )
        cash_usd = sum(fb.value_usd for fb in bal.forex_balances)
        cash_parts = ', '.join(
            f'{fb.currency} {fb.quantity:,.2f}' for fb in bal.forex_balances
        )
        rows.append({
            'saskaita': stmt.account_id,
            'rusis': 'IA',
            'data': declaration_start_date,
            'suma': f'{cash_eur:.2f}',
            'valstybe': country,
            '_description': f'Grynųjų likutis ${cash_usd:,.2f} ({cash_parts})'
        })

        # IS = consolidated cost basis of all positions
        positions_cost_eur = sum(
            native_to_eur(p.cost_basis, p.currency, bal_rates, bal_eur_rate)
            for p in bal.open_positions
        )
        positions_cost_usd = sum(
            native_to_usd(p.cost_basis, p.currency, bal_rates)
            for p in bal.open_positions
        )
        n_pos = len(bal.open_positions)
        rows.append({
            'saskaita': stmt.account_id,
            'rusis': 'IS',
            'data': declaration_start_date,
            'suma': f'{positions_cost_eur:.2f}',
            'valstybe': country,
            '_description': f'Visu instrumentu cost basis ${positions_cost_usd:,.2f} ({n_pos} pozicijos)'
        })

    # Add each deposit/withdrawal as individual row
    for dw in stmt.deposits_withdrawals:
        amount_eur = native_to_eur(dw.amount, dw.currency, rates, eur_rate)
        row_country = country_resolver.resolve_description(dw.description)
        # Positive = deposit (II), negative = withdrawal (PP)
        if dw.amount >= 0:
            code = 'II'
        else:
            code = 'PP'
            amount_eur = abs(amount_eur)  # VMI expects positive amounts for withdrawals

        rows.append({
            'saskaita': stmt.account_id,
            'rusis': code,
            'data': dw.date,
            'suma': f'{amount_eur:.2f}',
            'valstybe': row_country,
            '_description': f'{dw.description} ({dw.currency} {dw.amount:,.2f})'
        })

    # Add each dividend as deposit (IV) - dividends received into investment account
    for div in stmt.dividends:
        amount_eur = native_to_eur(div.amount, div.currency, rates, eur_rate)
        row_country = country_resolver.resolve_description(div.description)
        rows.append({
            'saskaita': stmt.account_id,
            'rusis': 'IV',
            'data': div.date,
            'suma': f'{amount_eur:.2f}',
            'valstybe': row_country,
            '_description': f'Dividendas: {div.description} ({div.currency} {div.amount:,.2f})'
        })

    # Sort by date
    rows.sort(key=lambda r: r['data'])

    # Write CSV
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['saskaita', 'rusis', 'data', 'suma', 'valstybe'])
        for row in rows:
            writer.writerow([row['saskaita'], row['rusis'], row['data'],
                             row['suma'], row['valstybe']])

    # Write annotated version for verification
    annotated_path = output_path.replace('.csv', '_annotated.csv')
    with open(annotated_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['saskaita', 'rusis', 'data', 'suma', 'valstybe', 'aprasymas'])
        for row in rows:
            writer.writerow([row['saskaita'], row['rusis'], row['data'],
                             row['suma'], row['valstybe'], row['_description']])

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Parse broker statements for VMI')
    parser.add_argument('input', help='Path to broker statement (IB HTM/HTML or Swedbank CSV)')
    parser.add_argument('--year', type=int, default=None,
                        help='Tax year (default: extracted from statement)')
    parser.add_argument('--broker', choices=['auto', 'ib', 'swedbank'], default='auto',
                        help='Input broker format (default: auto detect)')
    parser.add_argument('--swedbank-rules', default=None,
                        help='Path to YAML rules for Swedbank transaction mapping')
    parser.add_argument('--output-dir', default='output',
                        help='Output directory (default: output)')
    parser.add_argument('--declaration-start', default=None,
                        help='Declaration start date (YYYY-MM-DD) for initial balance (IA) row. '
                             'Use when first declaring the investment account.')
    parser.add_argument('--balance-statement', default=None,
                        help='Path to IB statement for initial balance date (e.g. 2024-12-31 daily). '
                             'Used to calculate cost basis for IA row. If omitted, uses main statement.')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: File not found: {args.input}")
        sys.exit(1)

    broker = detect_broker(args.input) if args.broker == 'auto' else args.broker
    print(f"Parsing: {args.input}")
    print(f"Detected broker: {broker}")

    if broker == 'swedbank':
        swedbank_rules = load_swedbank_rules(args.swedbank_rules)
        stmt = parse_swedbank_csv(args.input, rules=swedbank_rules)
        country = swedbank_rules.get('country', 'LT')
    else:
        stmt = parse_statement(args.input)
        country = 'IE'

    year = args.year or int(stmt.period_end[:4])
    print(f"Account: {stmt.account_id} ({stmt.account_name})")
    print(f"Period: {stmt.period_start} to {stmt.period_end}")
    print(f"Tax year: {year}")
    print(f"EUR/USD rate: {stmt.eur_usd_rate}")
    if stmt.derived_fx_rates:
        print(f"Derived FX rates: {stmt.derived_fx_rates}")

    # Parse balance statement for initial balance if provided
    balance_stmt = None
    if args.balance_statement:
        print(f"\nParsing balance statement: {args.balance_statement}")
        if broker == 'swedbank':
            balance_stmt = parse_swedbank_csv(args.balance_statement, rules=swedbank_rules)
        else:
            balance_stmt = parse_statement(args.balance_statement)
        print(f"Balance date: {balance_stmt.period_end}")
        print(f"Balance EUR/USD rate: {balance_stmt.eur_usd_rate}")
        if balance_stmt.derived_fx_rates:
            print(f"Balance derived FX rates: {balance_stmt.derived_fx_rates}")

    os.makedirs(args.output_dir, exist_ok=True)

    # Generate readable report
    report_path = os.path.join(args.output_dir, f'report_{year}.txt')
    report = generate_readable_report(stmt, report_path)
    print(f"\nReadable report: {report_path}")

    # Generate VMI CSV (individual rows per transaction)
    csv_path = os.path.join(args.output_dir, f'vmi_{year}.csv')
    rows = generate_vmi_csv(stmt, csv_path, year,
                            declaration_start_date=args.declaration_start,
                            balance_stmt=balance_stmt,
                            country=country)
    annotated_path = csv_path.replace('.csv', '_annotated.csv')
    print(f"VMI CSV: {csv_path}")
    print(f"VMI CSV (annotated): {annotated_path}")

    # Show VMI CSV contents
    print(f"\nVMI CSV entries ({len(rows)} rows):")
    print(f"  {'Kodas':5s} {'Data':12s} {'Suma EUR':>12s} Aprasymas")
    print(f"  {'-'*5} {'-'*12} {'-'*12} {'-'*40}")
    for row in rows:
        print(f"  {row['rusis']:5s} {row['data']:12s} {row['suma']:>12s} {row['_description']}")

    # Print summary stats
    print(f"\nParsed: {len(stmt.trades)} trades, {len(stmt.dividends)} dividends, "
          f"{len(stmt.withholding_taxes)} WHT entries, {len(stmt.interests)} interest entries, "
          f"{len(stmt.fees)} fee entries, {len(stmt.deposits_withdrawals)} deposits/withdrawals, "
          f"{len(stmt.open_positions)} open positions, {len(stmt.corporate_actions)} corporate actions")


if __name__ == '__main__':
    main()
