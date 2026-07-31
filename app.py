#!/usr/bin/env python3
"""
Flask GUI for VMI CSV editing.
Allows manual assignment of VMI codes (rusis) via web interface.
"""

import csv
import json
import os
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Configuration
OUTPUT_DIR = Path(__file__).parent / 'output'
SOURCE_DIR = Path(__file__).parent / 'source'
RULES_PATH = Path(__file__).parent / 'rules.yaml'
DEFAULT_SOURCE_CSV = SOURCE_DIR / 'Swedbank_statement.csv'
CSV_PATH_OVERRIDE = os.getenv('VMI_ANNOTATED_CSV_PATH')

# VMI codes available for selection
VMI_CODES = {
    'II': 'Lėšų įnešimas (inašas)',
    'IV': 'Lėšų įnešimas (dividendai)',
    'PP': 'Lėšų išėmimas (išmoka)',
    'IA': 'Pradinis likutis (grynos lėšos)',
    'IS': 'Finansinės priemonės (pradinis likutis)',
    'IP': 'Paveldėtos finansinės priemonės',
    'ID': 'Padovanotos finansinės priemonės',
}


def _active_csv_paths():
    """Resolve active annotated/plain CSV paths, preferring explicit env path or newest output file."""
    if CSV_PATH_OVERRIDE:
        annotated = Path(CSV_PATH_OVERRIDE)
    else:
        candidates = sorted(OUTPUT_DIR.glob('vmi_*_annotated.csv'), key=lambda p: p.stat().st_mtime, reverse=True)
        annotated = candidates[0] if candidates else (OUTPUT_DIR / 'vmi_2025_annotated.csv')

    plain_name = annotated.name.replace('_annotated.csv', '.csv')
    plain = annotated.with_name(plain_name)
    backup = annotated.with_suffix('.backup.csv')
    return annotated, plain, backup


def _refresh_outputs_if_source_newer():
    """Regenerate output CSV when default source CSV is newer than current annotated output."""
    source_path = Path(os.getenv('SWEDBANK_SOURCE_CSV_PATH', str(DEFAULT_SOURCE_CSV)))
    if not source_path.exists():
        return

    annotated_path, _, _ = _active_csv_paths()
    if annotated_path.exists() and source_path.stat().st_mtime <= annotated_path.stat().st_mtime:
        return

    try:
        from parse_ib import load_swedbank_rules, parse_swedbank_csv, generate_vmi_csv

        rules = load_swedbank_rules(str(RULES_PATH) if RULES_PATH.exists() else None)
        stmt = parse_swedbank_csv(str(source_path), rules=rules)
        year = int(stmt.period_end[:4]) if stmt.period_end else datetime.now().year
        output_path = OUTPUT_DIR / f'vmi_{year}.csv'
        generate_vmi_csv(stmt, str(output_path), year, country=rules.get('country', 'LT'))
        print(f"[GUI] Refreshed output from source: {source_path}")
    except Exception as exc:
        print(f"[GUI] Warning: could not refresh output from source ({source_path}): {exc}")


def load_csv():
    """Load annotated CSV file."""
    _refresh_outputs_if_source_newer()
    csv_path, _, _ = _active_csv_paths()
    if not csv_path.exists():
        return []

    rows = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            row['_id'] = i
            rows.append(row)
    return rows


def save_csv(rows):
    """Save rows back to annotated CSV file."""
    csv_path, plain_csv_path, backup_path = _active_csv_paths()

    # Create backup
    if csv_path.exists():
        with open(csv_path, 'r', encoding='utf-8') as src:
            with open(backup_path, 'w', encoding='utf-8') as dst:
                dst.write(src.read())

    # Write updated CSV
    fieldnames = ['saskaita', 'rusis', 'data', 'suma', 'valstybe', 'aprasymas']
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            # Remove internal _id field
            clean_row = {k: v for k, v in row.items() if k != '_id'}
            writer.writerow(clean_row)

    # Also update non-annotated version
    fieldnames_plain = ['saskaita', 'rusis', 'data', 'suma', 'valstybe']
    with open(plain_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames_plain)
        writer.writeheader()
        for row in rows:
            clean_row = {k: v for k, v in row.items() if k in fieldnames_plain}
            writer.writerow(clean_row)


@app.route('/')
def index():
    """Serve main page."""
    rows = load_csv()
    return render_template('index.html',
                          rows=rows,
                          vmi_codes=VMI_CODES,
                          total_rows=len(rows))


@app.route('/api/rows')
def api_rows():
    """API endpoint to get all rows as JSON."""
    rows = load_csv()
    return jsonify(rows)


@app.route('/api/update', methods=['POST'])
def api_update():
    """API endpoint to update a single row's VMI code."""
    data = request.json
    row_id = int(data.get('id'))
    new_rusis = data.get('rusis')

    if new_rusis not in VMI_CODES:
        return jsonify({'error': f'Invalid VMI code: {new_rusis}'}), 400

    rows = load_csv()
    if row_id >= len(rows):
        return jsonify({'error': f'Row {row_id} not found'}), 404

    rows[row_id]['rusis'] = new_rusis
    save_csv(rows)

    return jsonify({
        'success': True,
        'message': f'Row {row_id} updated to {new_rusis}',
        'row': rows[row_id]
    })


@app.route('/api/bulk-update', methods=['POST'])
def api_bulk_update():
    """API endpoint to bulk update rows."""
    data = request.json
    updates = data.get('updates', [])

    rows = load_csv()
    updated_count = 0

    for update in updates:
        row_id = int(update.get('id'))
        new_rusis = update.get('rusis')

        if new_rusis not in VMI_CODES:
            continue

        if row_id < len(rows):
            rows[row_id]['rusis'] = new_rusis
            updated_count += 1

    if updated_count > 0:
        save_csv(rows)

    return jsonify({
        'success': True,
        'message': f'{updated_count} rows updated',
        'updated_count': updated_count
    })


@app.route('/api/export')
def api_export():
    """API endpoint to export CSV (triggers download)."""
    rows = load_csv()

    fieldnames = ['saskaita', 'rusis', 'data', 'suma', 'valstybe', 'aprasymas']
    csv_content = ','.join(fieldnames) + '\n'

    for row in rows:
        values = [
            row.get('saskaita', ''),
            row.get('rusis', ''),
            row.get('data', ''),
            row.get('suma', ''),
            row.get('valstybe', ''),
            f'"{row.get("aprasymas", "").replace(chr(34), chr(34)*2)}"'  # Escape quotes
        ]
        csv_content += ','.join(values) + '\n'

    return csv_content, 200, {
        'Content-Disposition': 'attachment; filename=vmi_2025_annotated.csv',
        'Content-type': 'text/csv; charset=utf-8'
    }


@app.route('/api/stats')
def api_stats():
    """API endpoint to get statistics."""
    rows = load_csv()

    stats = {
        'total': len(rows),
        'by_code': {},
        'by_country': {},
        'by_date': {}
    }

    for row in rows:
        code = row.get('rusis', 'UNKNOWN')
        country = row.get('valstybe', 'UNKNOWN')
        date = row.get('data', 'UNKNOWN')

        stats['by_code'][code] = stats['by_code'].get(code, 0) + 1
        stats['by_country'][country] = stats['by_country'].get(country, 0) + 1
        stats['by_date'][date] = stats['by_date'].get(date, 0) + 1

    return jsonify(stats)


if __name__ == '__main__':
    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Create templates directory if needed
    templates_dir = Path(__file__).parent / 'templates'
    templates_dir.mkdir(exist_ok=True)

    # Run Flask app (allow port override via FLASK_PORT env var)
    import os
    port = int(os.getenv('FLASK_PORT', '5001'))
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
