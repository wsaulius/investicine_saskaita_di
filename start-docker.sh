#!/bin/bash

##############################################################################
# VMI Investicinės sąskaitos redaktoriaus paleistuvas (Docker)
#
# Šis skriptą paleidžia Flask VM redaktorių Docker konteineryje.
#
# Naudojimas:
#   ./start-docker.sh
#
# Aplikacija bus pasiekiama: http://localhost:5001
#
# Stabdymas: Ctrl+C
##############################################################################

set -e

# Spalvų nustatymai
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║    VMI Investicinės sąskaitos redaktorius - Docker Paleistas    ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Patikrinimas ar Docker yra instaliuotas
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Klaida: Docker nėra instaliuotas arba neprieinamas.${NC}"
    echo "  Parsisiųskite Docker iš: https://www.docker.com/"
    exit 1
fi

# Patikrinimas ar docker-compose yra instaliuotas
if ! command -v docker-compose &> /dev/null; then
    # Bandome docker compose (naujesnė versija)
    if ! docker compose version &> /dev/null; then
        echo -e "${RED}✗ Klaida: docker-compose nėra instaliuotas.${NC}"
        echo "  Instaliuokite: brew install docker-compose  (macOS)"
        echo "  arba: https://docs.docker.com/compose/install/"
        exit 1
    fi
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

echo -e "${YELLOW}Pradedama...${NC}"
echo ""

# Patikrinimas ar docker-compose.yml egzistuoja
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}✗ Klaida: docker-compose.yml nėra rasta.${NC}"
    echo "  Įsitikinkite, kad esate projekto root aplanke."
    exit 1
fi

# Pradedame docker-compose
echo -e "${GREEN}✓ Paleidžiamas Docker konteineris...${NC}"
echo -e "${BLUE}Prisijungimas URL: http://localhost:5001${NC}"
echo ""

$DOCKER_COMPOSE up

# Jei vartotojas išėjo iš docker-compose
echo ""
echo -e "${YELLOW}Sustabdytas.${NC}"

