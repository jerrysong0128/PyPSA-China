"""Rebuild steel evidence tables from preserved raw sources (Python stdlib only).

Run from the repository: python workflow/scripts/industry_data/build_inputs.py
Raw XLSX parsing preserves unknown/N/A markers, source rows, and status; capacity
is never substituted for production. NBS image transcription is reviewed input.
"""
from __future__ import annotations
import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import urllib.request
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'data/industry'
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def xlsx_rows(path, sheet):
    """Yield (Excel row number, values by column letter) without office deps."""
    with ZipFile(path) as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(t.itertext()) for t in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        workbook = ET.fromstring(z.read('xl/workbook.xml'))
        rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        found = next(s for s in workbook.find('m:sheets', NS) if s.get('name') == sheet)
        target = rels[found.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
        target = target.lstrip('/') if target.startswith('/') else 'xl/' + target
        for row in ET.fromstring(z.read(target)).findall('m:sheetData/m:row', NS):
            values = {}
            for cell in row:
                val = cell.find('m:v', NS)
                inline = cell.find('m:is', NS)
                value = val.text if val is not None else ''.join(inline.itertext()) if inline is not None else ''
                if cell.get('t') == 's':
                    value = strings[int(value)]
                values[re.sub(r'\d+', '', cell.get('r'))] = value or ''
            yield int(row.get('r')), values


def number(value, factor=1):
    try:
        val = Decimal(value)
        return str(val * factor) if val.is_finite() else ''
    except (InvalidOperation, TypeError):
        return ''


def write_csv(name, rows, fields=None):
    rows = list(rows)
    fields = fields or list(rows[0])
    with (DATA / 'processed' / name).open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def province_mapping():
    with (ROOT / 'resources/data/regions/province_codes.csv').open() as f:
        return {r['Full name']: r['Code'] for r in csv.DictReader(f)}


def normalize_province(value):
    return {'Inner Mongolia': 'InnerMongolia', 'Shaanxi province': 'Shaanxi'}.get(value, value)


def process_gem():
    codes = province_mapping()
    path = DATA / 'raw/gem/Global-Steel-Plant-Tracker-April-2024-Standard-Copy-V1.xlsx'
    raw = list(xlsx_rows(path, 'Steel Plants'))
    rows, plants = [], {}
    for rownum, r in raw[1:]:
        if r.get('Q') != 'China':
            continue
        province = normalize_province(r.get('P', ''))
        record = dict(plant_id=r.get('A'), plant_name=r.get('B'), province=province,
                      province_code=codes.get(province, ''), status=r.get('W'),
                      start_year_raw=r.get('AA'), coordinates=r.get('T'),
                      route_raw=r.get('AY'), source_id='gem_2024_plants',
                      source_locator=f'Steel Plants!{rownum}', reference_year=2024,
                      source_row_id=f'gem2024-{rownum}', wiki_url=r.get('V'))
        for col, label in [('AE','crude_steel'),('AF','bof'),('AG','eaf'),('AK','bf'),('AL','dri')]:
            record[label + '_capacity_tpy'] = number(r.get(col, ''), 1000)
            record[label + '_capacity_raw'] = r.get(col, '')
        rows.append(record)
        plants[r['A']] = record
    write_csv('gem_china_plant_capacity_2024.csv', rows)
    production = []
    raw = list(xlsx_rows(path, 'Yearly Production'))
    headers = raw[1][1]
    for rownum, r in raw[2:]:
        if r.get('A') not in plants:
            continue
        plant = plants[r['A']]
        for col, header in headers.items():
            match = re.match(r'(.*?) production (\d{4}) \(ttpa\)', header)
            if not match:
                continue
            production.append(dict(plant_id=r['A'], province=plant['province'],
                province_code=plant['province_code'], year=int(match[2]),
                variable=match[1].lower().replace(' ', '_')+'_production',
                value=number(r.get(col, ''), 1000), unit='t/year',
                raw_value=r.get(col, ''), estimate_flag=False,
                source_id='gem_2024_plants', source_locator=f'Yearly Production!{col}{rownum}'))
    write_csv('gem_china_plant_production_2019_2022.csv', production)
    rows = []
    for rownum, r in xlsx_rows(DATA / 'raw/gem/operating_steel_capacity_provinces_2026_09.xlsx', 'MethodChinaCapacitySteel'):
        province = normalize_province(r.get('A', ''))
        if province not in codes:
            continue
        for col, route in [('B','total'),('C','BOF'),('D','EAF'),('E','IF'),('F','other')]:
            rows.append(dict(province=province, province_code=codes[province], year=2026,
                route=route, value=number(r.get(col, ''), 1000), unit='t/year',
                variable='operating_capacity', estimate_flag=False,
                source_id='gem_2026_province_capacity', source_locator=f'MethodChinaCapacitySteel!{col}{rownum}'))
    write_csv('gem_province_capacity_2026.csv', rows)


def process_nbs():
    rows = []
    with (DATA / 'sources/nbs_2020_transcription.csv').open() as f:
        for r in csv.DictReader(f):
            for var in ['pig_iron', 'crude_steel']:
                raw = r[var + '_10000t']
                rows.append(dict(province=r['province'], province_code=r['province_code'], year=2020,
                    variable=var+'_production', value=number(raw, 10000), unit='t/year', raw_value=raw,
                    source_id='nbs_2021_table13_13', source_locator='C13-13.jpg:'+r['source_row'],
                    estimate_flag=False, method='manual_image_transcription_visual_review',
                    missing_reason='' if raw else 'blank_in_source_not_assumed_zero'))
    write_csv('nbs_province_steel_production_2020.csv', rows)


def process_henan():
    # HTML tag stripping is enough for this published static table; retain exact
    # source row label and require five numeric/label cells to reject other rows.
    from html import unescape
    text = (DATA / 'raw/nea_henan/t20250120_275548.html').read_text()
    labels = {'全社会用电总计':'total', '第一产业':'primary', '第二产业':'secondary',
              '第三产业':'tertiary', '城乡居民生活用电合计':'residential',
              '工业':'industry', '制造业':'manufacturing',
              '黑色金属冶炼和压延加工业':'ferrous_smelting_rolling'}
    rows=[]
    for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>', text, re.S|re.I):
        cells = [re.sub(r'\s+', '', unescape(re.sub('<[^>]+>', '', td))) for td in re.findall(r'<t[dh]\b[^>]*>(.*?)</t[dh]>', tr, re.S|re.I)]
        if len(cells)==5 and cells[0] in labels:
            rows.append(dict(province='Henan', province_code='HA', year=2024, sector=labels[cells[0]],
                value=number(cells[3],100000), unit='MWh/year', raw_value=cells[3], raw_unit='亿千瓦时',
                source_id='nea_henan_2024', source_locator='annual cumulative:'+cells[0], estimate_flag=False,
                boundary_note='ferrous includes rolling and ferroalloys; not identical to crude steel' if labels[cells[0]]=='ferrous_smelting_rolling' else 'published electricity consumption'))
    assert len(rows)==8, f'Unexpected Henan source structure: {len(rows)} rows'
    write_csv('henan_sector_electricity_2024.csv', rows)



def process_technology():
    rows=[]
    routes={'Avg BF-BOF':'BF-BOF','EAF':'scrap-EAF','DRI-EAF_100% green H2':'H2-DRI-EAF'}
    with (DATA/'raw/literature/mpp_technology_business_cases.csv').open(encoding='utf-8-sig') as f:
        for line,r in enumerate(csv.DictReader(f),2):
            for source_route,route in routes.items():
                value=r[source_route]
                unit=r['Unit']
                if unit=='GJ/t steel':
                    value=str(Decimal(value)/Decimal('3.6'))
                    unit='MWh/t steel'
                rows.append(dict(route=route,parameter=r['Material'],value=value,unit=unit,
                    source_id='mpp_business_cases',source_locator=f'row {line}; column {source_route}',
                    source_year='2022 model; fixed commit 9eca52d',estimate_flag=True,
                    readiness='candidate_requires_boundary_review',
                    note='BF electricity is net purchased (negative export); coal/coke/byproduct gases must not be summed as independent primary inputs. H2 LHV basis and electricity boundary require review.'))
    for sheet in ['GF capex','Renewal capex','Other Opex']:
        for num,r in xlsx_rows(DATA/'raw/literature/mpp_capex_opex.xlsx',sheet):
            if r.get('A') in routes:
                rows.append(dict(route=routes[r['A']],parameter=sheet,value=r.get('L'),
                    unit='source cost unit requires confirmation',source_id='mpp_capex_opex',
                    source_locator=f'{sheet}!L{num}',source_year='2030 column; 2020 money per PyPSA technology-data',
                    estimate_flag=True,readiness='candidate_requires_currency_and_boundary_review',
                    note='Do not treat Other Opex as FOM before checking fixed/variable coverage; annuity and currency conversion not applied.'))
    write_csv('route_parameter_candidates.csv',rows)


def process_bachorz():
    """Extract REMIND assumptions with line provenance; no automatic model inputs."""
    path=DATA/'raw/literature/remind-steel-LockIn-051c3ec4.zip'
    with ZipFile(path) as z:
        name=next(n for n in z.namelist() if n.endswith('37_industry/subsectors/datainput.gms'))
        lines=z.read(name).decode().splitlines()
    selected=[
        ('H2-DRI','pellets_t_per_tdri','p37_specMatDem("dripell","idr","h2")','t/tDRI'),
        ('DRI-EAF','dri_t_per_tsteel','p37_specMatDem("driron","eaf","pri")','tDRI/tsteel'),
        ('scrap-EAF','scrap_t_per_tsteel','p37_specMatDem("eafscrap","eaf","sec")','t/tsteel'),
        ('BF','ore_t_per_tpigiron','p37_specMatDem("ironore","bf","standard")','t/tpigiron'),
        ('BOF','pigiron_t_per_tsteel','p37_specMatDem("pigiron","bof","unheated")','tpigiron/tsteel'),
        ('H2-DRI','hydrogen_lhv_mwh_per_tdri','p37_specFeDemTarget("feh2s","idr","h2")','MWh_LHV/tDRI'),
        ('H2-DRI','electricity_mwh_per_tdri','p37_specFeDemTarget("feels","idr","h2")','MWh/tDRI'),
        ('DRI-EAF','electricity_mwh_per_tsteel','p37_specFeDemTarget("feels","eaf","pri")','MWh/tsteel'),
        ('scrap-EAF','electricity_mwh_per_tsteel','p37_specFeDemTarget("feels","eaf","sec")','MWh/tsteel'),
        ('BF','coal_mwh_per_tpigiron','p37_specFeDemTarget("fesos","bf","standard")','MWh/tpigiron'),
    ]
    rows=[]
    for route,parameter,key,unit in selected:
        hits=[(i+1,line) for i,line in enumerate(lines) if line.startswith(key)]
        if len(hits)!=1: raise ValueError('REMIND source structure changed: '+key)
        num,line=hits[0]
        value=re.search(r'=\s*([0-9.]+)',line)[1]
        rows.append(dict(route=route,parameter=parameter,value=value,unit=unit,
            source_id='bachorz_remind_code',source_locator=f'{name}:{num}',estimate_flag=True,
            readiness='candidate_model_assumption_not_observation',
            boundary_note='EAF excludes casting/rolling; H2 excludes electrolysis; BF electricity uses near-zero net power approximation. Source TODO flags integrated-plant boundary; do not use as gross electricity set.'))
    write_csv('bachorz_process_parameter_candidates.csv',rows)


def process_national_electricity():
    text=(DATA/'raw/nea_henan/nea_national_2020.html').read_text()
    rows=[]
    # Values from official sentence, asserted against raw text before export.
    for sector,value in [('total','75110'),('primary','859'),('secondary','51215'),('tertiary','12087'),('residential','10949')]:
        if value not in text: raise ValueError('NEA source text changed')
        rows.append(dict(province='China',province_code='CN',year=2020,sector=sector,
            value=number(value,100000),unit='MWh/year',source_id='nea_national_2020',
            source_locator='annual electricity paragraph',estimate_flag=False,
            boundary_note='secondary includes construction; national share is not measured provincial share'))
    write_csv('national_sector_electricity_2020.csv',rows)


def verify_raw():
    manifest=json.loads((DATA / 'sources/manifest.json').read_text())
    for source in manifest['sources']:
        p=DATA / source['original_path']
        actual=hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != source['sha256']:
            raise ValueError(f"Checksum mismatch for {p}; do not silently process changed source")


def download():
    """Exact URLs and expected hashes pin versions; mutable URLs can fail closed."""
    manifest=json.loads((DATA / 'sources/manifest.json').read_text())
    for source in manifest['sources']:
        p=DATA / source['original_path']
        if not p.exists():
            p.parent.mkdir(parents=True,exist_ok=True)
            if source.get('download_url'):
                with urllib.request.urlopen(urllib.request.Request(source['download_url'], headers={'User-Agent': 'Mozilla/5.0'})) as response:
                    body=response.read()
            elif source.get('local_origin') and Path(source['local_origin']).is_file():
                body=Path(source['local_origin']).read_bytes()
            else:
                raise FileNotFoundError('Restore original research archive for '+source['source_id'])
            if hashlib.sha256(body).hexdigest()!=source['sha256']:
                raise ValueError('Downloaded source changed: '+source['source_id'])
            p.write_bytes(body)
    verify_raw()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--download',action='store_true')
    args=parser.parse_args()
    if args.download: download()
    verify_raw()
    (DATA/'processed').mkdir(exist_ok=True)
    process_gem(); process_nbs(); process_henan(); process_technology(); process_national_electricity(); process_bachorz()

if __name__ == '__main__': main()
