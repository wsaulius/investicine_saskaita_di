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

### 3. Paleisti testus

```bash
pip install -r requirements.txt
python3 -m pytest
```

---

## ✅ Kas patobulinta šiame projekte

- Pridėtas **Swedbank CSV palaikymas** šalia Interactive Brokers HTM ataskaitų, su brokerio auto-detekcija ir tuo pačiu VMI eksporto srautu.
- Įdiegtas **konfigūruojamas operacijų klasifikavimo sluoksnis** per `rules.yaml`, leidžiantis lanksčiai žymėti operacijas kaip `II`, `IV`, `PP` arba ignoruoti.
- Pridėtos **pakartotinai naudojamos pattern kolekcijos** per `patterns.json`, kad taisyklėse būtų galima naudoti `@pattern_name` nuorodas vietoje pasikartojančių literalų.
- Įdiegta **ISIN pagrindu veikianti šalies (`valstybe`) rezoliucija** per OpenFIGI API, su cache, fallback logika ir aiškiais log pranešimais.
- Sukurtas **Flask GUI redaktorius**, leidžiantis peržiūrėti sugeneruotą anotuotą CSV, ranka koreguoti `rusis`, filtruoti eilutes, matyti statistiką ir eksportuoti rezultatą.
- Patobulintas GUI veikimo modelis į **manual-save** režimą: pakeitimai pažymimi, o išsaugojimas vyksta tik paspaudus veiksmų mygtuką.
- Sutvarkytas **eilutės būsenų atvaizdavimas GUI**: taškas (`•`) neįrašytam pakeitimui, varnelė (`✓`) sėkmingam įrašymui, kryžiukas (`✗`) klaidai.
- Pašalintos **šalių filtravimo dubliavimo problemos** GUI ir išlaikyta mygtukų būsena po filtravimo ar lentelės perpiešimo.
- Projektas **dockerizuotas** per `Dockerfile`, `docker-compose.yml` ir `start-docker.sh`, kad Flask redaktorių būtų galima paleisti konteineryje.
- Pakeistas Flask portas į **5001**, kad būtų išvengta tipinio macOS konflikto su 5000 portu.
- Pridėtas **OpenFIGI logavimas**, matomas tiek lokaliame paleidime, tiek Docker konteinerio loguose.
- Sukurtas **pytest testų rinkinys** Swedbank parseriui, taisyklėms, pattern kolekcijoms, OpenFIGI rezoliucijai ir galutiniam VMI CSV generavimui.
- Papildyta dokumentacija apie **taisyklių konfigūravimą, pattern kolekcijas, testų paleidimą ir OpenFIGI naudojimą**.

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
instrumentas pirmiausia tikrinamas per OpenFIGI API pagal tą ISIN kodą.
Jei API grąžina šalies kodą, naudojama jis; jei API laikinai nepasiekiamas
arba negrąžina šalies lauko, naudojamas ISIN prefiksas (pvz. `US...` -> `US`,
`LU...` -> `LU`). Jei ISIN apskritai nėra, naudojama numatytoji šalis iš
`rules.yaml` (`country`).

Jei reikia didesnių OpenFIGI limitų, galite nustatyti `OPENFIGI_API_KEY`
aplinkos kintamąjį prieš paleidžiant `parse_ib.py`.

Kai randamas ISIN, paleidimo metu loge matysite OpenFIGI užklausas ir Docker
konteinerio loguose, pvz.: `[OpenFIGI] OpenFIGI cache miss for ISIN ...`,
`[OpenFIGI] Accessing OpenFIGI for ISIN ...`,
`[OpenFIGI] OpenFIGI resolved ISIN ... -> US` arba fallback / klaidos žinutes.

