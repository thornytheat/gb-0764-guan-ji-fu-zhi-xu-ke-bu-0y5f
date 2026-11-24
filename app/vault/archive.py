from datetime import datetime, timezone
import json

from app.problem import DeskError
from app.vault.record import encode


def _decode(row):
    imprint, archived_at, years, accounts, totals = row
    return {'imprint': imprint, 'archived_at': archived_at, 'years': json.loads(years),
            'accounts': json.loads(accounts), 'totals': json.loads(totals)}


def _reconciled(accounts, totals):
    # 归档时复算额度账：限额=占用+剩余，且各池有效占用之和等于卷宗有效页数。
    return (all(a['limit'] == a['used'] + a['available'] for a in accounts.values())
            and sum(a['used'] for a in accounts.values()) == totals['effective']
            and sum(a['gross'] for a in accounts.values()) == totals['licensed'])


def archive(vault, run):
    with vault.session() as conn:
        item = conn.execute('SELECT manifest, evidence FROM volumes WHERE id=?', (run,)).fetchone()
        if item is None:
            raise DeskError('RUN_UNKNOWN', 404)
        existing = conn.execute('SELECT imprint, archived_at, years, accounts, totals '
                                'FROM archives WHERE id=?', (run,)).fetchone()
        if existing is not None:
            # 重复执行或中途重试：直接取回原归档记录，不写任何数据，不动原指纹。
            return dict(_decode(existing), run_id=run, reused=True)
        slip = conn.execute('SELECT digest FROM slips WHERE id=?', (run,)).fetchone()
        if slip is None:
            raise DeskError('DRAFT_ONLY', 409)
        manifest, evidence = item
        if evidence is None:
            raise DeskError('ARCHIVE_STATE', 409)
        report = json.loads(evidence)
        totals = json.loads(manifest)['totals']
        accounts = report['balance']['accounts']
        years = sorted({pool.split('/', 1)[0] for pool in accounts})
        snapshot = dict(totals, reconciled=_reconciled(accounts, totals))
        archived_at = datetime.now(timezone.utc).isoformat()
        inserted = conn.execute('INSERT INTO archives VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                                (run, slip[0], archived_at, encode(years), encode(accounts),
                                 encode(snapshot))).rowcount
        if inserted:
            # 证据清理与归档快照在同一事务内提交；重试不会再次清理。
            conn.execute('UPDATE volumes SET evidence=NULL WHERE id=?', (run,))
        record = conn.execute('SELECT imprint, archived_at, years, accounts, totals '
                              'FROM archives WHERE id=?', (run,)).fetchone()
    return dict(_decode(record), run_id=run, reused=not bool(inserted))


def archived_volume(vault, run):
    with vault.session() as conn:
        row = conn.execute('SELECT imprint, archived_at, years, accounts, totals '
                           'FROM archives WHERE id=?', (run,)).fetchone()
    if row is None:
        raise DeskError('RUN_UNKNOWN', 404)
    return dict(_decode(row), run_id=run)


def ledger(vault, year=None):
    # 额度池限额按卷宗窗口独立生效，因此跨卷汇总时保留各卷剩余之和，
    # 对账口径为：占用合计 + 剩余合计 = 限额 × 卷宗数。
    books = {}
    with vault.session() as conn:
        rows = conn.execute('SELECT id, accounts, totals FROM archives ORDER BY archived_at').fetchall()
    for run, accounts_text, totals_text in rows:
        totals = json.loads(totals_text)
        for pool, account in json.loads(accounts_text).items():
            pool_year, pool_id = pool.split('/', 1)
            if year is not None and pool_year != year:
                continue
            book = books.setdefault((pool_year, pool_id),
                                    {'year': pool_year, 'pool': pool_id, 'limit': account['limit'],
                                     'used': 0, 'gross': 0, 'available': 0, 'volumes': [], 'sound': True})
            if book['limit'] != account['limit']:
                book['sound'] = False
            book['used'] += account['used']
            book['gross'] += account['gross']
            book['available'] += account['available']
            book['sound'] = book['sound'] and totals['reconciled']
            book['volumes'].append(run)
    result = []
    for book in books.values():
        count = len(book['volumes'])
        book['volume_count'] = count
        book['reconciled'] = (book['sound']
                              and book['used'] + book['available'] == book['limit'] * count)
        del book['sound']
        result.append(book)
    return {'ledger': sorted(result, key=lambda b: (b['year'], b['pool']))}
