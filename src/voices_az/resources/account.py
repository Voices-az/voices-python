"""Read-only account figures: balance and transactions."""

from __future__ import annotations

from typing import Mapping

from .._base import Call
from ..types import Balance, Page, Transaction
from ._common import AsyncResource, Op, SyncResource, page_of

__all__ = ["Account", "AsyncAccount"]


def _balance_op() -> Op[Balance]:
    data = yield Call("GET", "/customer/balance")
    return Balance.from_dict(data if isinstance(data, Mapping) else {})


def _transactions_op(page: int) -> Op[Page[Transaction]]:
    if page < 1:
        raise ValueError("page starts at 1")
    data = yield Call("GET", "/customer/transactions", params={"page": int(page)})
    return page_of(data, Transaction.from_dict)


class Account(SyncResource):
    """``client.account`` - the balance that every paid call spends."""

    def balance(self) -> Balance:
        """The current balance (``GET /customer/balance``)."""
        return self._run(_balance_op())

    def transactions(self, *, page: int = 1) -> Page[Transaction]:
        """Balance transactions, newest first, 20 per page (``GET /customer/transactions``)."""
        return self._run(_transactions_op(page))


class AsyncAccount(AsyncResource):
    """Async version of :class:`Account`."""

    async def balance(self) -> Balance:
        """See :meth:`Account.balance`."""
        return await self._run(_balance_op())

    async def transactions(self, *, page: int = 1) -> Page[Transaction]:
        """See :meth:`Account.transactions`."""
        return await self._run(_transactions_op(page))
