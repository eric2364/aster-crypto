"""Original-release BLS CPI events in the fixed one-year research window.

Defaults to verified existing cache; --offline prohibits HTTP, --refresh obtains
original HTML where BLS permits access. Never substitutes revised time series.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests

START = datetime(2025, 10, 5, tzinfo=timezone.utc)
END = datetime(2026, 10, 5, tzinfo=timezone.utc)
INDEX_URL = 'https://www.bls.gov/bls/news-release/cpi.htm'


class Page(HTMLParser):
    """Collect observed anchors, visible text and table cells without a DOM library."""
    def __init__(self, text):
        super().__init__()
        self.text = []
        self.links = []
        self.rows = []
        self.anchor = None
        self.row = None
        self.cell = None
        self.skip = 0
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'a':
            self.anchor = [attrs.get('href', ''), []]
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)
        if self.anchor is not None:
            self.anchor[1].append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip -= 1
        if tag == 'a' and self.anchor is not None:
            self.links.append((self.anchor[0], ''.join(self.anchor[1]).strip()))
            self.anchor = None
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_source(out, source):
    path = out / source['file']
    if digest(path) != source['sha256']:
        raise ValueError(f'Pinned response hash mismatch: {path}')
    return path.read_text(encoding='utf-8')


def parse_source(source, response):
    rendered = not source['publisher_original_html']
    if rendered:
        text = re.sub(r'L\d+:\s*', '', response)
        rows = [line.split('|') for line in text.splitlines() if '|' in line]
    else:
        page = Page(response)
        text = ' '.join(page.text)
        rows = page.rows
    text = ' '.join(text.split())
    embargo = re.search(r'8:30\s*a\.m\.\s*\(ET\)\s+(\w+),\s+(\w+)\s+(\d{1,2}),\s+(\d{4})', text)
    reference = re.search(r'CONSUMER PRICE INDEX\s*[-–]\s*(\w+)\s+(\d{4})', text)
    if embargo is None or reference is None:
        raise ValueError(f'Missing actual embargo paragraph/reference month: {source["url"]}')
    weekday, month, day, year = embargo.groups()
    date = datetime.strptime(f'{month} {day} {year}', '%B %d %Y')
    if date.strftime('%A') != weekday:
        raise ValueError(f'Embargo weekday mismatch: {source["url"]}')
    release = date.replace(hour=8, minute=30, tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
    reference_month = datetime.strptime(' '.join(reference.groups()), '%B %Y').strftime('%Y-%m')

    def table_values(label):
        matches = [row for row in rows if row and row[0].strip() == label]
        # First matching row is Table A, not later detailed current-index tables.
        if not matches or len(matches[0]) != 9:
            raise ValueError(f'Missing/unexpected Table A row {label}: {source["url"]}')
        current_mom, current_yoy = [cell.strip() for cell in matches[0][-2:]]
        def number(cell):
            if cell in ('-', '—', '–', ''):
                return None
            if not re.fullmatch(r'-?\d+(?:\.\d+)?', cell):
                raise ValueError(f'Unrecognized rate {cell!r}: {source["url"]}')
            return float(cell)
        return number(current_mom), number(current_yoy)

    headline_mom, headline_yoy = table_values('All items')
    core_mom, core_yoy = table_values('All items less food and energy')
    if headline_yoy is None or core_yoy is None:
        raise ValueError(f'Current YoY values unavailable: {source["url"]}')
    return dict(release_time=release, available_at=release + timedelta(minutes=1),
                reference_month=reference_month, headline_yoy=headline_yoy,
                core_yoy=core_yoy, headline_mom=headline_mom, core_mom=core_mom,
                rate_unit='published_percent_points', yoy_adjustment='not_seasonally_adjusted',
                mom_adjustment='seasonally_adjusted', value_vintage='as_reported_in_original_release',
                source_url=source['url'], source_response_sha256=source['sha256'],
                source_transport=source['transport'],
                release_time_source='BLS stated embargo paragraph; America/New_York timezone',
                availability_assumption='stated release time plus one-minute ingestion lag')


def fetch_html(out):
    """Discover links from the actual archive index, never a guessed date grid."""
    raw = out / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    index = session.get(INDEX_URL, timeout=30)
    index.raise_for_status()
    index_path = raw / 'archive_index.html'
    index_path.write_bytes(index.content)
    page = Page(index.text)
    sources = []
    for href, label in page.links:
        url = urljoin(INDEX_URL, href)
        match = re.search(r'/news\.release/archives/cpi_(\d{8})\.htm$', url)
        if not match or urlparse(url).hostname != 'www.bls.gov':
            continue
        # Filename only bounds the observed candidates; actual time comes from body.
        candidate_date = datetime.strptime(match.group(1), '%m%d%Y').replace(tzinfo=timezone.utc)
        if not START <= candidate_date < END:
            continue
        if any(source['url'] == url for source in sources):
            continue
        response = session.get(url, timeout=30)
        response.raise_for_status()
        path = raw / Path(urlparse(url).path).name
        path.write_bytes(response.content)
        sources.append(dict(url=url, file=str(path.relative_to(out)), sha256=digest(path),
                            transport='direct BLS HTTPS original HTML response',
                            publisher_original_html=True, observed_archive_label=label))
    missing = []
    if 'October 2025 Consumer Price Index' in ' '.join(page.text) and 'Not published because of 2025 lapse' in ' '.join(page.text):
        missing.append(dict(reference_month='2025-10', reason='Not published because of 2025 lapse in federal government appropriations', source_url=INDEX_URL))
    return dict(archive_index_url=INDEX_URL, archive_index_file=str(index_path.relative_to(out)),
                archive_index_sha256=digest(index_path), sources=sources,
                retrieved_at=datetime.now(timezone.utc).isoformat(), missing_reference_months=missing,
                requested_start=START.isoformat(), requested_end_exclusive=END.isoformat(),
                discovery='Actual HTML anchors in official archive index; no guessed release calendar')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('data_cache/external-factors-1y/cpi'))
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--offline', action='store_true', help='Use only the hash-pinned existing source cache')
    group.add_argument('--refresh', action='store_true', help='Fetch original BLS HTML; fail on HTTP blocks')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / 'source_manifest.json'
    if args.offline and not manifest_path.exists():
        raise FileNotFoundError('Offline mode needs source_manifest.json and its pinned raw responses')
    if manifest_path.exists() and not args.refresh:
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = fetch_html(out)
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    if digest(out / manifest['archive_index_file']) != manifest['archive_index_sha256']:
        raise ValueError('Pinned archive index hash mismatch')
    events = []
    for source in manifest['sources']:
        if urlparse(source['url']).hostname != 'www.bls.gov':
            raise ValueError('Only original official BLS sources are accepted')
        event = parse_source(source, checked_source(out, source))
        if START <= event['release_time'] < END:
            events.append(event)
    frame = pd.DataFrame(events).sort_values('release_time').reset_index(drop=True)
    if len(frame) != 11 or frame.reference_month.duplicated().any() or frame.release_time.duplicated().any():
        raise ValueError('Expected 11 unique actually published releases in the fixed window')
    if frame.reference_month.eq('2025-10').any():
        raise ValueError('October2025 reference month must remain unpublished')
    frame.to_parquet(out / 'releases.parquet', index=False)
    frame.to_csv(out / 'releases.csv', index=False)
    coverage = dict(events=len(frame), first_release=frame.release_time.iloc[0].isoformat(),
                    last_release=frame.release_time.iloc[-1].isoformat(),
                    missing_reference_months=manifest['missing_reference_months'],
                    missing_headline_mom_reference_months=frame.loc[frame.headline_mom.isna(), 'reference_month'].tolist(),
                    consensus_available=False, interpolation=False, values='original-release current-reference-month Table A values',
                    time_assumption='actual stated 08:30 ET converted with DST; available one minute later',
                    source_manifest_sha256=digest(manifest_path),
                    releases_parquet_sha256=digest(out / 'releases.parquet'),
                    releases_csv_sha256=digest(out / 'releases.csv'))
    (out / 'coverage.json').write_text(json.dumps(coverage, indent=2) + '\n')
    print(frame[['reference_month', 'release_time', 'available_at', 'headline_yoy', 'core_yoy', 'headline_mom']].to_string(index=False))


if __name__ == '__main__':
    main()
