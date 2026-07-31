Čia pateiktos Claude Code instrukcijos Interactive brokers ir Swedbank investicinės sąskaitos pavertimui į 
csv failą, kurė priima VMI deklaruojant investicinę sąskaitą.

## 🎯 Greita pradžia

### 1. Sugeneruoti VMI CSV iš šaltinio duomenų

```bash
# Swedbank CSV failas su taisyklėmis
python3 parse_ib.py source/Swedbank_statement.csv --broker swedbank --swedbank-rules rules.yaml

# Interactive Brokers HTML
python3 parse_ib.py source/U15802656_2025_2025.htm
```

### 2. Redaguoti VMI kodus žiniatinklio sąsajoje

Paleiskite Flask GUI redaktorių:

#### Vietoje (lokalioje mašinoje):
```bash
pip install -r requirements.txt
python3 app.py
# Atsidarys http://localhost:5001
```

#### Docker konteineriu (rekomenduojama):

**Greičiausias būdas — paleisti skriptą:**
```bash
./start-docker.sh
```

**Arba rankiniu būdu:**
```bash
docker-compose up
```

Tada atsidarys **http://localhost:5001**

Redaktorius leidžia:
- ✏️ Redaguoti operacijos kodą (rusis) iš dropdown sąrašo
- 🔍 Filtruoti eilutes pagal kodą ir šalį
- 📊 Peržiūrėti statistiką
- ⬇️ Parsisiųsti atnaujintą CSV

---

## 📋 VMI operacijų kodai (rusis)

```
II  = funds deposited into investment account (inašas)
IV  = funds deposited via dividends received (inašas dividendais)
PP  = funds withdrawn from investment account (išmoka)
IA  = initial balance on declaration start date (pradinis likutis)
IS  = pre-2024 financial products assigned to account
IP  = inherited financial products
ID  = gifted financial products
```

---

## 🔧 Išsamūs nustatymai

### Šaltinio duomenys

Šis kodas skaito:
- **Interactive Brokers** HTML format: `<AccountId>_YYYY_YYYY.htm` (metinė ataskaita)
- **Swedbank** CSV format: `Swedbank_statement.csv`

Ataskaitas dėkite į `source/` aplanką.

### CSV stulpeliai

VMI CSV turėtų turėti šiuos stulpelius:
```
saskaita,rusis,data,suma,valstybe
```

- `saskaita` = sąskaitos numeris
- `rusis` = operacijos tipo kodas
- `data` = operacijos data (YYYY-MM-DD)
- `suma` = suma EUR (teigiama)
- `valstybe` = finansų institucijos šalies kodas (pvz. IE, US, LU, LT)

### Taisyklių failas (`rules.yaml`)

Taisykles galite redaguoti `rules.yaml` faile.

### Valstybės žymėjimas (`valstybe`)

`valstybe` stulpelis nustatomas eilutes lygiu: jei aprasyme randamas ISIN,
naudojamas jo salies prefiksas (pvz. `US...` -> `US`, `LU...` -> `LU`),
kitu atveju naudojama numatytoji salis is `rules.yaml` (`country`).

