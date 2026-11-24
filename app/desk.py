from flask import Blueprint, current_app, render_template, request

from app.problem import DeskError
from app.settings import EDITION
from app.source import bundle
from app.vault.archive import ledger
from app.vault.record import index
from app.workflow import steps

desk = Blueprint('desk', __name__)
SECTIONS = {'balance': '签发请求对账', 'intake': '授权材料采信', 'registry': '刊号与机构映射',
            'licenses': '许可版本裁决', 'pages': '拆页与额度占用', 'volumes': '批次留档复跑',
            'stamp': '许可证据签发', 'archives': '归档台账'}


@desk.get('/')
@desk.get('/folio/<view>')
def folio(view='balance'):
    if view not in SECTIONS:
        raise DeskError('SAMPLE_UNKNOWN', 404)
    sample = request.args.get('sample', 'dirty')
    data = steps(bundle(sample), view)
    volumes = index(current_app.vault) if view in ('volumes', 'stamp', 'archives') else []
    archive_book = ledger(current_app.vault) if view == 'archives' else {'ledger': []}
    return render_template('base.html', view=view, sections=SECTIONS, data=data, sample=sample,
                           volumes=volumes, active=request.args.get('run'), edition=EDITION,
                           archive_book=archive_book)
