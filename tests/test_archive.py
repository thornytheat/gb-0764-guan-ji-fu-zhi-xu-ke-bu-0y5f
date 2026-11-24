import sqlite3
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

import pytest

from app.main import create_app
from app.source import bundle
from app.vault.archive import archive, archived_volume, ledger
from app.vault.record import deposit, encode, index, volume


def run_id(client, sample='dirty'):
    return client.post('/api/volumes', json={'sample': sample}).json['run_id']


def stamp(client, run):
    return client.post(f'/api/volumes/{run}/stamp').json['imprint']


def vault_of(client):
    return client.application.vault


def test_draft_cannot_be_archived(client):
    run = run_id(client)
    reply = client.post(f'/api/volumes/{run}/archive')
    assert (reply.status_code, reply.json['error']) == (409, 'DRAFT_ONLY')
    assert volume(vault_of(client), run)['stages'] is not None


def test_archive_clears_online_evidence_but_keeps_certificate(client):
    run = run_id(client)
    imprint = stamp(client, run)
    reply = client.post(f'/api/volumes/{run}/archive')
    assert reply.status_code == 200 and reply.json['reused'] is False
    vault = vault_of(client)
    with vault.session() as conn:
        assert conn.execute('SELECT evidence FROM volumes WHERE id=?', (run,)).fetchone()[0] is None
        stored = conn.execute('SELECT body, digest FROM slips WHERE id=?', (run,)).fetchone()
    # 在线证据已清理，凭证仍可下载且验印通过、指纹与落印时一致。
    export = client.get(f'/api/volumes/{run}/export').json
    assert export['imprint'] == imprint and export['verified'] is True
    assert sha256(encode(export['document']).encode()).hexdigest() == imprint
    assert sha256(stored[0].encode()).hexdigest() == stored[1] == imprint
    report = client.get(f'/api/volumes/{run}').json
    assert report['archived'] is True and report['stages'] is None
    assert report['archive']['imprint'] == imprint
    assert report['archive']['totals']['reconciled'] is True


def test_repeat_archive_is_idempotent_and_keeps_fingerprint(client):
    run = run_id(client)
    imprint = stamp(client, run)
    first = client.post(f'/api/volumes/{run}/archive').json
    second = client.post(f'/api/volumes/{run}/archive').json
    third = archive(vault_of(client), run)
    assert first['imprint'] == second['imprint'] == third['imprint'] == imprint
    assert (first['reused'], second['reused'], third['reused']) == (False, True, True)
    with vault_of(client).session() as conn:
        assert conn.execute('SELECT COUNT(*) FROM archives').fetchone()[0] == 1
        assert conn.execute('SELECT digest FROM slips WHERE id=?', (run,)).fetchone()[0] == imprint


def test_same_incoming_does_not_revive_evidence_or_new_run(client):
    run = run_id(client)
    imprint = stamp(client, run)
    client.post(f'/api/volumes/{run}/archive')
    again = client.post('/api/volumes', json={'sample': 'dirty'})
    assert again.status_code == 200 and again.json['reused'] is True
    assert again.json['run_id'] == run
    with vault_of(client).session() as conn:
        assert conn.execute('SELECT evidence FROM volumes WHERE id=?', (run,)).fetchone()[0] is None
    # 已归档卷重新落印只取回原指纹，不依赖被清理的证据。
    assert client.post(f'/api/volumes/{run}/stamp').json == {
        'run_id': run, 'imprint': imprint, 'reused': True}


def test_archived_annual_ledger_reconciles(client):
    dirty = run_id(client)
    stamp(client, dirty)
    client.post(f'/api/volumes/{dirty}/archive')
    clean = run_id(client, 'clean')
    stamp(client, clean)
    client.post(f'/api/volumes/{clean}/archive')
    books = client.get('/api/archives').json['ledger']
    by_pool = {f"{b['year']}/{b['pool']}": b for b in books}
    report = archived_volume(vault_of(client), dirty)
    for pool, account in report['accounts'].items():
        book = by_pool[pool]
        assert book['limit'] == account['limit']
        assert book['used'] + book['available'] == book['limit'] * book['volume_count']
    assert all(b['reconciled'] for b in books)
    assert sum(b['used'] for b in books) == sum(
        item['totals']['effective'] for item in index(vault_of(client)))
    filtered = ledger(vault_of(client), year='2026')['ledger']
    assert filtered and all(b['year'] == '2026' for b in filtered)


def test_concurrent_archive_commits_once(desk):
    run = deposit(desk.vault, bundle('dirty'))['run_id']
    stamp(desk.test_client(), run)
    with ThreadPoolExecutor(5) as pool:
        results = list(pool.map(lambda _: archive(desk.vault, run), range(10)))
    assert sum(not item['reused'] for item in results) == 1
    with desk.vault.session() as conn:
        assert conn.execute('SELECT COUNT(*) FROM archives').fetchone()[0] == 1
        assert conn.execute('SELECT evidence FROM volumes WHERE id=?', (run,)).fetchone()[0] is None


def test_archive_failure_rolls_back_everything(desk):
    run = deposit(desk.vault, bundle('dirty'))['run_id']
    stamp(desk.test_client(), run)
    with desk.vault.session() as conn:
        conn.execute("CREATE TRIGGER fail_archive BEFORE INSERT ON archives "
                     "BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        archive(desk.vault, run)
    with desk.vault.session() as conn:
        assert conn.execute('SELECT COUNT(*) FROM archives').fetchone()[0] == 0
        assert conn.execute('SELECT evidence FROM volumes WHERE id=?', (run,)).fetchone()[0] is not None


def test_index_flags_archive_lifecycle(client):
    run = run_id(client)

    def current():
        return next(row for row in index(vault_of(client)) if row['run_id'] == run)

    assert current()['stamped'] is False and current()['archived'] is False
    stamp(client, run)
    assert current()['stamped'] is True and current()['archived'] is False
    client.post(f'/api/volumes/{run}/archive')
    assert current()['stamped'] is True and current()['archived'] is True


def test_legacy_database_migrates_and_keeps_evidence(tmp_path):
    path = tmp_path / 'legacy.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE volumes (id TEXT PRIMARY KEY, manifest TEXT NOT NULL, '
                     'evidence TEXT NOT NULL)')
        conn.execute('CREATE TABLE slips (id TEXT PRIMARY KEY REFERENCES volumes(id), '
                     'digest TEXT NOT NULL, body TEXT NOT NULL)')
        conn.execute("INSERT INTO volumes VALUES ('r1','{}','[]')")
    app = create_app(path)
    with app.vault.session() as conn:
        assert conn.execute('SELECT evidence FROM volumes').fetchone()[0] == '[]'
        assert conn.execute("SELECT \"notnull\" FROM pragma_table_info('volumes') "
                            "WHERE name='evidence'").fetchone()[0] == 0
    assert app.test_client().get('/api/volumes/r1').json['archived'] is False
