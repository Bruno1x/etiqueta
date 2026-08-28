"""One real direct-print attempt, with durable duplicate protection.

The SYSEMP terminal owns routing and document sizes. This code never changes
the default printer and never retries a dispatch whose outcome is uncertain.
"""
from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class OrderIdentity:
    channel: str
    marketplace_order: str
    invoice: str

    @property
    def key(self):
        return hashlib.sha256(f'{self.channel}|{self.marketplace_order}|{self.invoice}'.encode()).hexdigest()


class NoEligibleOrder(RuntimeError):
    """A searched store has no safely recognized visible printing candidate."""


class PrintJournal:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS attempts (key TEXT PRIMARY KEY, state TEXT NOT NULL, updated TEXT NOT NULL)')

    def reserve(self, order):
        try:
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('INSERT INTO attempts VALUES (?, ?, ?)',
                           (order.key, 'reserved', datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError as exc:
            raise RuntimeError('Este pedido já teve uma tentativa registrada. Confira a fila e o papel; o bot não reenviará automaticamente.') from exc

    def attempted(self, order):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT 1 FROM attempts WHERE key=?', (order.key,)).fetchone() is not None

    def state(self, order, value):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE attempts SET state=?, updated=? WHERE key=?',
                       (value, datetime.now(timezone.utc).isoformat(), order.key))


def print_one(backend, journal, allowed_channels, expected_channel=None, *, row=None, require_confirmation=False):
    """Backend implements live checks; injectable so ordering can be tested offline."""
    backend.preflight()
    if row is None:
        row = backend.choose_candidate()
    order = backend.select_and_identify(row)
    if order.channel not in allowed_channels:
        raise RuntimeError(f'Canal não autorizado: {order.channel}. Nenhuma impressão enviada.')
    if expected_channel is not None and order.channel != expected_channel:
        raise RuntimeError(f'A grade pertence a {order.channel}, mas a loja pesquisada é {expected_channel}. Nada foi impresso.')
    if not order.marketplace_order.isdigit() or len(order.marketplace_order) < 8:
        raise RuntimeError('Pedido Marketplace não foi lido com segurança.')
    if not order.invoice.replace('.', '').isdigit():
        raise RuntimeError('Número da nota não foi lido com segurança.')
    backend.verify_candidate(row, order)
    # Record BEFORE clicking. Crashes/focus loss leave a pending record, not a retry.
    journal.reserve(order)
    try:
        backend.dispatch(row, order)
        journal.state(order, 'sent_unconfirmed')
        confirmed = backend.wait_result(row, order)
    except Exception as exc:
        journal.state(order, 'uncertain')
        raise RuntimeError('A tentativa ficou registrada, mas o resultado é incerto. Não repita: confira a Zebra e a fila. Detalhe: ' + str(exc)) from exc
    if confirmed:
        journal.state(order, 'sysemp_marked')
        return 'SYSEMP marcou NF e etiqueta como impressas. Confira fisicamente transporte + DANFE na Zebra. Teste encerrado após um pedido.'
    if require_confirmation:
        raise RuntimeError('Envio sem confirmação do SYSEMP. Ronda interrompida; confira a Zebra e a fila. O pedido não será reenviado automaticamente.')
    return 'Um envio foi acionado, mas o resultado não foi confirmado. Não repita: confira a Zebra e a fila do Windows. O pedido ficou protegido contra reenvio pelo bot.'
