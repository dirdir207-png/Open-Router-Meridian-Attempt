"""Stable, authenticated HTTP read models for Meridian."""

from functools import wraps

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required

from meridian.models import AccountRecord, TransactionRecord
from meridian.services.activity import get_activity, get_transaction
from meridian.services.today import build_today, data_freshness

meridian_api = Blueprint("meridian_api", __name__)


def _repository():
    return current_app.config["MERIDIAN_REPOSITORY_FACTORY"]()


def _error(
    code: str,
    message: str,
    recovery_action: str,
    status: int,
    *,
    freshness: dict[str, object] | None = None,
):
    return (
        jsonify(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "recovery_action": recovery_action,
                },
                "data_freshness": freshness
                or {"status": "unavailable", "last_updated_at": None},
            }
        ),
        status,
    )


def _safe_read(view):
    """Keep provider/repository failures out of browser contracts and logs."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except Exception:
            return _error(
                "financial_data_unavailable",
                "Financial data is temporarily unavailable.",
                "Try again after your provider reconnects.",
                503,
            )

    return wrapped


def _account_payload(account: AccountRecord) -> dict[str, object]:
    return {
        "id": account.id,
        "provider": account.provider,
        "name": account.name,
        "account_type": account.account_type,
        "balance": account.balance,
        "available_balance": account.available_balance,
        "currency": account.currency,
        "is_active": account.is_active,
        "source_updated_at": account.source_updated_at,
        "synced_at": account.synced_at,
    }


def _transaction_payload(transaction: TransactionRecord) -> dict[str, object]:
    return {
        "id": transaction.id,
        "account_id": transaction.account_id,
        "provider": transaction.provider,
        "amount": transaction.amount,
        "currency": transaction.currency,
        "occurred_at": transaction.occurred_at,
        "posted_at": transaction.posted_at,
        "description": transaction.description,
        "merchant": transaction.merchant,
        "status": transaction.status,
        "source_updated_at": transaction.source_updated_at,
        "synced_at": transaction.synced_at,
    }


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise ValueError
    return parsed


@meridian_api.get("/today")
@login_required
@_safe_read
def today():
    return jsonify(build_today(_repository()))


@meridian_api.get("/accounts")
@login_required
@_safe_read
def accounts():
    repository = _repository()
    records = repository.list_accounts()
    return jsonify(
        {
            "accounts": [_account_payload(account) for account in records],
            "data_freshness": data_freshness(
                repository,
                account_ids=[account.id for account in records],
            ),
        }
    )


@meridian_api.get("/activity")
@login_required
@_safe_read
def activity():
    limit_value = request.args.get("limit", "50")
    try:
        limit = _positive_int(limit_value)
        if limit > 200:
            raise ValueError
    except ValueError:
        return _error(
            "invalid_request",
            "limit must be an integer between 1 and 200.",
            "Use a limit between 1 and 200 and try again.",
            400,
        )
    account_id_value = request.args.get("account_id")
    try:
        account_id = _positive_int(account_id_value) if account_id_value else None
    except ValueError:
        return _error(
            "invalid_request",
            "account_id must be a positive integer.",
            "Use a positive account_id and try again.",
            400,
        )

    try:
        page = get_activity(
            _repository(),
            limit=limit,
            cursor=request.args.get("cursor"),
            account_id=account_id,
        )
    except ValueError:
        return _error(
            "invalid_request",
            "The activity cursor is invalid.",
            "Restart from the first Activity page and try again.",
            400,
        )
    return jsonify(
        {
            "transactions": [
                _transaction_payload(transaction) for transaction in page["transactions"]
            ],
            "next_cursor": page["next_cursor"],
            "data_freshness": page["data_freshness"],
        }
    )


@meridian_api.get("/transactions/<transaction_id>")
@login_required
@_safe_read
def transaction_detail(transaction_id: str):
    try:
        repository = _repository()
        transaction = get_transaction(repository, _positive_int(transaction_id))
    except ValueError:
        return _error(
            "invalid_request",
            "transaction_id must be a positive integer.",
            "Choose a transaction from Activity and try again.",
            400,
        )
    if transaction is None:
        return _error(
            "transaction_not_found",
            "The requested transaction is not available.",
            "Return to Activity and choose another transaction.",
            404,
            freshness=data_freshness(repository),
        )
    return jsonify(
        {
            "transaction": _transaction_payload(transaction),
            "data_freshness": data_freshness(
                repository,
                transaction_ids=[transaction.id],
            ),
        }
    )
