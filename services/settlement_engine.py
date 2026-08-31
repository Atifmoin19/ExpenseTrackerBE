"""Min-transaction settlement optimizer (standard min-cash-flow / greedy
max-creditor vs max-debtor matching), per CONTRACT.md:

    1. Compute net balance per member = sum(paid) - sum(owed) - settled.
    2. Repeatedly match the max creditor with the max debtor, settle
       min(|credit|, |debit|), push the resulting transaction, zero out the
       smaller side, repeat until all balances are ~0 (epsilon 0.01).

Pure function, independently unit-testable — no Firestore/FastAPI imports.
"""
from typing import TypedDict

EPSILON = 0.01


class SettlementSuggestion(TypedDict):
    fromUid: str
    toUid: str
    amount: float


def optimize(balances: dict[str, float]) -> list[SettlementSuggestion]:
    """balances: uid -> net balance (positive = creditor/is owed money,
    negative = debtor/owes money). Returns the minimal list of
    {fromUid, toUid, amount} transactions that settle every balance to ~0.
    """
    working = {uid: round(bal, 2) for uid, bal in balances.items() if abs(bal) > EPSILON}
    transactions: list[SettlementSuggestion] = []

    while working:
        creditor = max(working, key=lambda uid: working[uid])
        debtor = min(working, key=lambda uid: working[uid])
        credit = working[creditor]
        debit = working[debtor]

        # No more meaningful creditor/debtor pair left (remaining balances are
        # within epsilon of zero, or floating-point drift left mismatched signs).
        if credit <= EPSILON or debit >= -EPSILON:
            break

        amount = round(min(credit, -debit), 2)
        if amount <= EPSILON:
            break

        transactions.append({"fromUid": debtor, "toUid": creditor, "amount": amount})

        working[creditor] = round(credit - amount, 2)
        working[debtor] = round(debit + amount, 2)

        if abs(working[creditor]) <= EPSILON:
            del working[creditor]
        if debtor in working and abs(working[debtor]) <= EPSILON:
            del working[debtor]

    return transactions
