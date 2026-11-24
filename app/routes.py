from flask import Blueprint, current_app, jsonify, request

from app.certificate.slip import certificate, stamp
from app.source import read_request
from app.vault.archive import archive, archived_volume, ledger
from app.vault.record import deposit, index, volume
from app.workflow import steps

rights = Blueprint('rights', __name__)


def review(name):
    return steps(read_request(), name)[name]


@rights.route('/api/intake', methods=['GET', 'POST'])
def intake():
    return review('intake')


@rights.route('/api/registry', methods=['GET', 'POST'])
def registry():
    return review('registry')


@rights.route('/api/licenses', methods=['GET', 'POST'])
def choose():
    return review('licenses')


@rights.route('/api/pages', methods=['GET', 'POST'])
def pages():
    return review('pages')


@rights.route('/api/balance', methods=['GET', 'POST'])
def balance():
    return review('balance')


@rights.get('/api/volumes')
def volumes():
    return {'volumes': index(current_app.vault)}


@rights.post('/api/volumes')
def file():
    result = deposit(current_app.vault, read_request())
    return result, 200 if result['reused'] else 201


@rights.get('/api/volumes/<run>')
def get_volume(run):
    report = volume(current_app.vault, run)
    if report['archived']:
        report['archive'] = archived_volume(current_app.vault, run)
    return report


@rights.post('/api/volumes/<run>/archive')
def archive_volume(run):
    return archive(current_app.vault, run)


@rights.get('/api/archives')
def archive_ledger():
    return ledger(current_app.vault, request.args.get('year'))


@rights.post('/api/volumes/<run>/stamp')
def issue(run):
    return stamp(current_app.vault, run)


@rights.get('/api/volumes/<run>/export')
def download(run):
    result = jsonify(certificate(current_app.vault, run))
    result.headers['Content-Disposition'] = f'attachment; filename="license-{run}.json"'
    return result
